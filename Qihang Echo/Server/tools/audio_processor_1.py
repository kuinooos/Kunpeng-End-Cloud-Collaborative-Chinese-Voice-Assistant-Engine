import struct
import ctypes
import sys
import os
sys.path.append("..")
from tools.logger import logger

# === 终极解决方案：手动定义 OpusEncoder/Decoder ===
# 如果 PyOgg 实在无法工作，我们直接使用 ctypes 调用 libopus
# 这是一个最小化的 Opus 封装，绕过 PyOgg 的复杂性

try:
    from pyogg import OpusEncoder, OpusDecoder
except ImportError:
    # logger.warning("PyOgg import failed. Falling back to ctypes implementation.")
    
    # 加载库
    try:
        _lib = ctypes.CDLL("/usr/lib64/libopus.so")
    except OSError:
        try:
            _lib = ctypes.CDLL("libopus.so")
        except OSError:
            raise ImportError("Could not load libopus.so")

    # 定义常量
    OPUS_APPLICATION_VOIP = 2048
    OPUS_OK = 0

    # 定义函数原型
    _lib.opus_encoder_create.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_int)]
    _lib.opus_encoder_create.restype = ctypes.c_void_p

    _lib.opus_encoder_ctl.argtypes = [ctypes.c_void_p, ctypes.c_int]
    _lib.opus_encoder_ctl.restype = ctypes.c_int

    _lib.opus_encode.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_short), ctypes.c_int, ctypes.POINTER(ctypes.c_ubyte), ctypes.c_int]
    _lib.opus_encode.restype = ctypes.c_int

    _lib.opus_decoder_create.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_int)]
    _lib.opus_decoder_create.restype = ctypes.c_void_p

    _lib.opus_decode.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ubyte), ctypes.c_int, ctypes.POINTER(ctypes.c_short), ctypes.c_int, ctypes.c_int]
    _lib.opus_decode.restype = ctypes.c_int

    class OpusEncoder:
        def __init__(self):
            self._encoder = None
            self._channels = 1
            self._rate = 16000
            self._app = OPUS_APPLICATION_VOIP

        def set_sampling_frequency(self, rate):
            self._rate = rate

        def set_channels(self, channels):
            self._channels = channels

        def set_application(self, app):
            # 简化处理，只支持 voip
            pass

        def _init_encoder(self):
            if self._encoder: return
            error = ctypes.c_int()
            self._encoder = _lib.opus_encoder_create(self._rate, self._channels, self._app, ctypes.byref(error))
            if error.value != OPUS_OK:
                raise Exception(f"Failed to create Opus encoder: {error.value}")

        def encode(self, pcm_data):
            self._init_encoder()
            frame_size = len(pcm_data) // 2 // self._channels # int16 samples per channel
            pcm_ptr = ctypes.cast(pcm_data, ctypes.POINTER(ctypes.c_short))
            max_bytes = len(pcm_data) # conservative
            out_buf = (ctypes.c_ubyte * max_bytes)()
            
            ret = _lib.opus_encode(self._encoder, pcm_ptr, frame_size, out_buf, max_bytes)
            if ret < 0:
                raise Exception(f"Opus encode failed: {ret}")
            return bytes(out_buf[:ret])

    class OpusDecoder:
        def __init__(self):
            self._decoder = None
            self._channels = 1
            self._rate = 16000

        def set_sampling_frequency(self, rate):
            self._rate = rate

        def set_channels(self, channels):
            self._channels = channels

        def _init_decoder(self):
            if self._decoder: return
            error = ctypes.c_int()
            self._decoder = _lib.opus_decoder_create(self._rate, self._channels, ctypes.byref(error))
            if error.value != OPUS_OK:
                raise Exception(f"Failed to create Opus decoder: {error.value}")

        def decode(self, encoded_data):
            self._init_decoder()
            # 假设最大帧长 5760 (120ms @ 48k), 这里给够 buffer
            max_samples = 5760 
            out_buf = (ctypes.c_short * (max_samples * self._channels))()
            
            if encoded_data is None:
                # Packet loss concealment
                data_ptr = None
                data_len = 0
            else:
                # 确保 encoded_data 是 bytes 类型
                if not isinstance(encoded_data, bytes):
                    if isinstance(encoded_data, (bytearray, memoryview)):
                        encoded_data = bytes(encoded_data)
                    else:
                        raise TypeError(f"encoded_data must be bytes, not {type(encoded_data)}")

                data_ptr = ctypes.cast(encoded_data, ctypes.POINTER(ctypes.c_ubyte))
                data_len = len(encoded_data)

            ret = _lib.opus_decode(self._decoder, data_ptr, data_len, out_buf, max_samples, 0)
            if ret < 0:
                raise Exception(f"Opus decode failed: {ret}")
            # out_buf 是 c_short 数组，直接 bytes(out_buf) 会尝试把每个 short 当作 byte 值（0-255），导致 ValueError
            # 正确做法是使用 memoryview 或 string_at 来获取原始字节流
            return ctypes.string_at(ctypes.byref(out_buf), ret * self._channels * ctypes.sizeof(ctypes.c_short))

# 默认音频配置参数
SAMPLE_RATE = 16000
CHANNELS = 1
FRAME_DURATION_MS = 40

class AudioProcessor:
    HEADER_FORMAT = "!HHI"  # 版本 (2 字节) + 类型 (2 字节) + 负载大小 (4 字节)
    HEADER_SIZE = struct.calcsize(HEADER_FORMAT)

    def __init__(self, sample_rate=SAMPLE_RATE, channels=CHANNELS, frame_duration_ms=FRAME_DURATION_MS):
        self.sample_rate = sample_rate
        self.channels = channels
        self.frame_duration_ms = frame_duration_ms
        self.frame_size = sample_rate // 1000 * frame_duration_ms

        # 检查帧持续时间是否为 Opus 支持的值
        if self.frame_duration_ms not in [2.5, 5, 10, 20, 40, 60]:
            raise ValueError("Frame duration must be one of 2.5, 5, 10, 20, 40, or 60 ms.")

        # 初始化 Opus 编解码器
        self.encoder = OpusEncoder()
        self.encoder.set_sampling_frequency(sample_rate)
        self.encoder.set_channels(channels)
        self.encoder.set_application('voip')

        self.decoder = OpusDecoder()
        self.decoder.set_sampling_frequency(sample_rate)
        self.decoder.set_channels(channels)

    def pack_bin_frame(self, version, type, payload):
        """
        打包 BinProtocol 消息
        :param version: 协议版本 (2 字节)
        :param type: 消息类型 (2 字节)
        :param payload: 消息负载 (字节)
        :return: 打包后的二进制数据
        """
        header = struct.pack(self.HEADER_FORMAT, version, type, len(payload))
        return header + payload

    def unpack_bin_frame(self, data):
        """
        解包 BinProtocol 消息
        :param data: 接收到的二进制数据
        :return: BinProtocol 对象或 None
        """
        if len(data) < self.HEADER_SIZE:
            logger.error("Data too short to contain BinProtocol header")
            return None

        version, type, payload_size = struct.unpack(self.HEADER_FORMAT, data[:self.HEADER_SIZE])
        if len(data) < self.HEADER_SIZE + payload_size:
            logger.error("Data size does not match payload_size")
            return None

        payload = data[self.HEADER_SIZE:self.HEADER_SIZE + payload_size]
        if len(payload) != payload_size:
            logger.error("Payload size mismatch")
            return None

        return (version, type, payload)

    def encode_audio(self, pcm_data):
        """
        编码 PCM 音频数据为 Opus 数据
        :param pcm_data: PCM 音频数据 (字节)
        :return: 编码后的 Opus 数据 (字节)
        """
        # 计算可以完整处理的帧数
        full_frames = len(pcm_data) // (self.frame_size * 2)
        total_bytes_to_process = full_frames * self.frame_size * 2

        if full_frames == 0:
            logger.error("PCM data size is less than one frame size")
            return None

        opus_data = b''
        for i in range(0, total_bytes_to_process, self.frame_size * 2):
            frame = pcm_data[i:i + self.frame_size * 2]
            encoded_frame = self.encoder.encode(frame)
            opus_data += encoded_frame

        # # 如果有剩余未处理的数据，则记录警告
        # remaining_bytes = len(pcm_data) % (self.frame_size * 2)
        # if remaining_bytes > 0:
        #     logger.warning(f"Skipped {remaining_bytes} bytes of PCM data that did not fit into a complete frame")

        return opus_data

    def decode_audio(self, opus_data):
        """
        解码 Opus 数据为 PCM 音频数据
        :param opus_data: Opus 数据 (字节)
        :return: 解码后的 PCM 音频数据 (字节)
        """
        pcm_data = b''
        start = 0
        while start < len(opus_data):
            # 解码一帧 Opus 数据
            encoded_frame_size = min(len(opus_data) - start, 1536)
            encoded_frame = bytearray(opus_data[start:start + encoded_frame_size])
            decoded_frame = self.decoder.decode(encoded_frame)
            pcm_data += decoded_frame
            start += encoded_frame_size

        return pcm_data

    def set_audio_params(self, sample_rate=SAMPLE_RATE, channels=CHANNELS, frame_duration_ms=FRAME_DURATION_MS):
        """
        设置音频参数
        :param sample_rate: 采样率
        :param channels: 声道数
        :param frame_duration_ms: 每帧的持续时间（可选）
        """
        self.sample_rate = sample_rate
        self.channels = channels
        if frame_duration_ms is not None:
            self.frame_duration_ms = frame_duration_ms
        self.frame_size = sample_rate // 1000 * self.frame_duration_ms

        # 重新初始化编解码器
        self.encoder.set_sampling_frequency(sample_rate)
        self.encoder.set_channels(channels)
        self.decoder.set_sampling_frequency(sample_rate)
        self.decoder.set_channels(channels)

    def load_audio_from_file(self, file_path):
        """
        从文件中加载 PCM 音频数据
        :param file_path: PCM 文件路径
        :return: 音频数据队列
        """

        with open(file_path, 'rb') as f:
            pcm_data = f.read()

        frames = []
        for i in range(0, len(pcm_data), self.frame_size * 2):
            frame = pcm_data[i:i + self.frame_size * 2]
            frames.append(frame)

        return frames

    def save_audio_to_file(self, pcm_data, file_path):
        """
        将 PCM 音频数据保存到文件
        :param pcm_data: PCM 音频数据 (字节)
        :param file_path: 保存的文件路径
        """
        with open(file_path, 'wb') as f:
            f.write(pcm_data)

    def get_audio_params(self):
        """
        获取当前音频参数
        :return: 采样率, 声道数, 每帧持续时间
        """
        return self.sample_rate, self.channels, self.frame_duration_ms
