import os
import numpy as np
from funasr import AutoModel
from tools.logger import logger
import re

class ASRModel:
    def __init__(self, device="cpu"):
        # 处理 cpu-torch 这种情况
        if device == "cpu-torch":
            device = "cpu"
            
        self.device = device
        self.audio_buffer = np.array([], dtype=np.float32)
        
        # 获取 Server 根目录
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        
        # 强制指定本地 PyTorch 模型绝对路径
        local_torch_path = "/home/openEuler/KunpengChat/Server/models/FunAudioLLM/iic/SenseVoiceSmall"
        
        self.model = None
        
        # 只加载本地 PyTorch 模型 (ONNX 由 ASRModelNPU 接管)
        if os.path.exists(local_torch_path):
            logger.info(f"Loading local PyTorch ASR model from: {local_torch_path}")
            try:
                self.model = AutoModel(
                    model=local_torch_path,
                    device=device,
                    trust_remote_code=True, 
                    disable_update=True,
                    disable_pbar=True,
                    log_level="ERROR"
                )
                logger.info("PyTorch ASR Model loaded successfully.")
            except Exception as e:
                logger.error(f"Failed to load PyTorch model: {e}")
        else:
            logger.error(f"PyTorch model path not found: {local_torch_path}")

        # 3. 如果本地都失败，直接报错退出 (不尝试云端)
        if self.model is None:
            logger.error("All local models failed to load. Cloud download is disabled.")
            raise RuntimeError("Failed to load any local ASR model.")

    def clear_audio_buffer(self):
        self.audio_buffer = np.array([], dtype=np.float32)

    def add_audio_buffer(self, audio_data):
        """
        添加音频数据到缓冲区
        :param audio_data: bytes (int16 PCM) or np.ndarray
        """
        if isinstance(audio_data, bytes):
            data = np.frombuffer(audio_data, dtype=np.int16)
        else:
            data = audio_data
        
        # 转换为 float32 并归一化
        if isinstance(data, np.ndarray):
             if data.dtype == np.int16:
                 data = data.astype(np.float32) / 32768.0
             elif data.dtype == np.float32:
                 pass
             else:
                 data = data.astype(np.float32)
        
        self.audio_buffer = np.concatenate((self.audio_buffer, data))

    def ASR_generate_text(self, audio_data):
        """
        生成文本
        :param audio_data: float32 numpy array
        """
        try:
            # input 长度检查 (FunASR 可能会报错如果太短)
            if len(audio_data) < 1600: # 0.1s
                return None

            # SenseVoiceSmall 参数
            res = self.model.generate(
                input=audio_data,
                cache={},
                language="auto", 
                use_itn=False,
                batch_size_s=60,
                merge_vad=True,
                merge_thr_s=0.5,
            )
            
            # res 格式通常是List[Dict]： [{'key': 'wav', 'text': '识别结果'}]
            if res and isinstance(res, list) and len(res) > 0:
                text = res[0].get("text", "")
                # 清理标签 (SenseVoice 输出包含情感和语言标签)
                clean_text = re.sub(r'<\|.*?\|>', '', text).strip()
                return clean_text if clean_text else None
            return None
        except Exception as e:
            logger.error(f"ASR Inference Error: {e}")
            return None

