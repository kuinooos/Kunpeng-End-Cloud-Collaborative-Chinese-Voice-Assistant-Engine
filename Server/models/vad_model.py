import numpy as np
from collections import deque


class VADModel:
    """
    WebRTC VAD 封装，面向流式处理，返回约定的状态码：
      0 - 正常处理，继续接收
      1 - 检测到语音结束（end-of-speech）
      2 - 无语音活动（长时间静音且未触发过语音）
      3 - 缓冲区已满（说话过长，主动截断）

    说明：
    - 输入为任意长度的 int16 PCM（单声道，采样率16k）。内部切分为 WebRTC 支持的帧（10/20/30ms）。
    - 使用一个简单的状态机：NOT_TRIGGERED -> TRIGGERED -> NOT_TRIGGERED。
    - 触发条件：在滑动窗口中有足够多的 voiced 帧。
    - 结束条件：在 TRIGGERED 状态下累计静音超过阈值，返回 1。
    - 无语音：累计静音超过阈值且从未触发过语音  ，返回 2。
    - 过长截断：单次语音段累计时长超过上限，返回 3。
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        frame_ms: int = 20,
        vad_aggressiveness: int = 2,
        trigger_window_ms: int = 200,
        trigger_ratio: float = 0.6,
        silence_end_ms: int = 1000,
        nospeech_timeout_ms: int = 5000,
        max_utterance_ms: int = 10000,
    ):
        """
        :param sample_rate: 采样率，必须是 8000/16000/32000/48000（WebRTC 支持）。
        :param frame_ms: 单帧长度（10/20/30ms）。
        :param vad_aggressiveness: 0-3，越大越激进（更容易判为非语音）。
        :param trigger_window_ms: 触发窗口大小（用于平滑启动）。
        :param trigger_ratio: 在窗口中判为语音的比例阈值，超过则进入 TRIGGERED。
        :param silence_end_ms: 在 TRIGGERED 状态下，累计静音超过该阈值则判定语音结束。
        :param nospeech_timeout_ms: 未触发语音前，累计静音超过该阈值则返回 2。
        :param max_utterance_ms: 单次语音段的最大时长，超过则返回 3。
        """
        assert frame_ms in (10, 20, 30)
        self.sample_rate = sample_rate
        self.frame_ms = frame_ms
        self.frame_len = int(sample_rate * frame_ms / 1000)
        self.bytes_per_sample = 2  # int16

        # 延迟加载 webrtcvad，避免在未安装环境报静态导入错误
        import importlib
        spec = importlib.util.find_spec("webrtcvad")
        if spec is None:
            raise RuntimeError("webrtcvad 未安装，请先安装依赖: pip install webrtcvad")
        webrtcvad = importlib.import_module("webrtcvad")
        self.vad = webrtcvad.Vad(vad_aggressiveness)

        # 状态机
        self.NOT_TRIGGERED = 0
        self.TRIGGERED = 1
        self.state = self.NOT_TRIGGERED

        # 窗口与计数
        self.window_frames = int(trigger_window_ms / frame_ms)
        self.window = deque(maxlen=self.window_frames)
        self.total_unvoiced_ms = 0
        self.total_voiced_ms = 0
        self.triggered_voiced_ms = 0
        self.triggered_silence_ms = 0
        self.has_ever_triggered = False

        self.silence_end_ms = silence_end_ms
        self.nospeech_timeout_ms = nospeech_timeout_ms
        self.max_utterance_ms = max_utterance_ms
        self.trigger_ratio = trigger_ratio

    def reset(self):
        self.state = self.NOT_TRIGGERED
        self.window.clear()
        self.total_unvoiced_ms = 0
        self.total_voiced_ms = 0
        self.triggered_voiced_ms = 0
        self.triggered_silence_ms = 0
        self.has_ever_triggered = False

    def _frame_iter(self, audio: np.ndarray):
        """
        将任意长度的 int16 PCM 分割为 frame_ms 帧；丢弃不足一帧的尾巴。
        """
        if audio.dtype != np.int16:
            audio = audio.astype(np.int16, copy=False)
        n = len(audio)
        step = self.frame_len
        for i in range(0, n - n % step, step):
            frame = audio[i : i + step]
            yield frame.tobytes()

    def process_audio_frame(self, audio_frame: np.ndarray) -> int:
        """
        :param audio_frame: 单声道 PCM，numpy int16，一次可传入任意长度（内部按 20ms 切片）。
        :return: 0/1/2/3（见类注释）
        """
        # 将传入的数据切分为 WebRTC 支持的帧
        for frame_bytes in self._frame_iter(audio_frame):
            is_speech = self.vad.is_speech(frame_bytes, self.sample_rate)

            # 窗口与全局计时
            self.window.append(is_speech)
            if is_speech:
                self.total_voiced_ms += self.frame_ms
            else:
                self.total_unvoiced_ms += self.frame_ms

            if self.state == self.NOT_TRIGGERED:
                # 长时间无语音，直接返回 2
                if not self.has_ever_triggered and self.total_unvoiced_ms >= self.nospeech_timeout_ms:
                    self.reset()
                    return 2

                # 进入触发：窗口内语音比例超过阈值
                if len(self.window) == self.window_frames:
                    voiced_ratio = sum(self.window) / float(self.window_frames)
                    if voiced_ratio >= self.trigger_ratio:
                        self.state = self.TRIGGERED
                        self.has_ever_triggered = True
                        self.triggered_voiced_ms = 0
                        self.triggered_silence_ms = 0

            else:  # TRIGGERED
                if is_speech:
                    self.triggered_voiced_ms += self.frame_ms
                    self.triggered_silence_ms = 0
                else:
                    self.triggered_silence_ms += self.frame_ms

                # 结束条件：静音超过阈值
                if self.triggered_silence_ms >= self.silence_end_ms:
                    self.reset()
                    return 1

                # 过长截断
                if (self.triggered_voiced_ms + self.triggered_silence_ms) >= self.max_utterance_ms:
                    self.reset()
                    return 3

        # 默认继续
        return 0
