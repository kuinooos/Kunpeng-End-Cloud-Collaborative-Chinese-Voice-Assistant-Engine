"""
ASR Model with Ascend NPU acceleration for Orange Pi Kunpeng Pro.
专门适配 FunASR SenseVoiceSmall 模型。

使用方式：
1. 确保已安装 CANN Toolkit 和 onnxruntime-ascend
2. 使用 export_sensevoice_onnx.py 将 SenseVoiceSmall 转换为 ONNX
3. (可选) 使用 atc 工具将 ONNX 转换为 .om 文件
4. 在 settings.py 中设置 ASR_DEVICE = "npu" 或 "acl"

依赖安装：
pip install onnxruntime torchaudio
# 或者安装昇腾版本：
# pip install onnxruntime-ascend
"""

import numpy as np
import json
import os
import time
import struct
from tools.logger import logger

# ACL 常量定义
ACL_MEM_MALLOC_HUGE_FIRST = 0
ACL_MEM_MALLOC_HUGE_ONLY = 1
ACL_MEM_MALLOC_NORMAL_ONLY = 2
ACL_MEMCPY_HOST_TO_DEVICE = 1
ACL_MEMCPY_DEVICE_TO_HOST = 2

# 全局变量，防止重复初始化
_ACL_INITIALIZED = False

class ASRModelNPU:
    """
    基于 Ascend NPU 的 SenseVoiceSmall ASR 模型封装。
    支持两种后端：
    1. onnxruntime (CPU/NPU) - 加载 .onnx
    2. acl (纯 NPU) - 加载 .om
    """
    
    def __init__(self, model_path: str = None, vocab_path: str = None, device: str = "cpu-onnx"):
        """
        :param model_path: ONNX 模型路径或 .om 模型路径
        :param vocab_path: 词表文件路径 (tokens.json 或 vocab.txt)
        :param device: "cpu-onnx", "acl"
        """
        self.device = device
        self.model_path = model_path
        self.vocab_path = vocab_path
        self.session = None
        self.audio_buffer = np.array([], dtype=np.float32)
        self.vocab = self._load_vocab(vocab_path)
        
        # ACL 资源
        self.model_id = None
        self.context = None
        self.stream = None
        self.model_desc = None
        self.input_dataset = None
        self.output_dataset = None
        self.input_buffers = []  # 保存输入 buffer 指针以便释放
        self.output_buffers = [] # 保存输出 buffer 指针以便释放
        
        if device == "acl":
            self._init_acl()
        else:
            # cpu-onnx
            self._init_onnxruntime_cpu()
    
    def _load_vocab(self, vocab_path):
        """加载 SenseVoice 词表"""
        if not vocab_path or not os.path.exists(vocab_path):
            logger.warning(f"Vocab path not found: {vocab_path}, decoding will return raw IDs")
            return {}
        
        vocab = {}
        try:
            # 尝试解析 json 格式 (tokens.json)
            if vocab_path.endswith('.json'):
                with open(vocab_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # 假设格式是 list 或 dict
                    if isinstance(data, list):
                        for i, token in enumerate(data):
                            vocab[i] = token
                    elif isinstance(data, dict):
                        for k, v in data.items():
                            if isinstance(v, int):
                                vocab[v] = k
                            else:
                                try:
                                    vocab[int(k)] = v
                                except:
                                    pass
            else:
                # 尝试解析文本格式 (每行一个 token)
                with open(vocab_path, 'r', encoding='utf-8') as f:
                    for i, line in enumerate(f):
                        token = line.strip()
                        parts = token.split()
                        if len(parts) == 2 and parts[1].isdigit():
                            vocab[int(parts[1])] = parts[0]
                        else:
                            vocab[i] = token
                            
            logger.info(f"Loaded vocab with {len(vocab)} tokens")
        except Exception as e:
            logger.error(f"Failed to load vocab: {e}")
        return vocab

    def _init_onnxruntime_cpu(self):
        """使用 ONNX Runtime CPU 后端"""
        try:
            import onnxruntime as ort
            if self.model_path:
                so = ort.SessionOptions()

                # Optional: control threading to avoid oversubscription when taskset pins to a small cpuset.
                # Keep defaults if env vars are not set.
                intra = os.environ.get("ORT_INTRA_OP_NUM_THREADS")
                inter = os.environ.get("ORT_INTER_OP_NUM_THREADS")
                if intra and intra.isdigit():
                    so.intra_op_num_threads = int(intra)
                if inter and inter.isdigit():
                    so.inter_op_num_threads = int(inter)

                exec_mode = os.environ.get("ORT_EXECUTION_MODE", "").strip().upper()
                if exec_mode == "SEQUENTIAL":
                    so.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
                elif exec_mode == "PARALLEL":
                    so.execution_mode = ort.ExecutionMode.ORT_PARALLEL

                self.session = ort.InferenceSession(
                    self.model_path,
                    sess_options=so,
                    providers=['CPUExecutionProvider']
                )
                logger.info(
                    "ASR Model loaded with ONNX Runtime (CPU)"
                    f" | intra={getattr(so, 'intra_op_num_threads', None)}"
                    f" inter={getattr(so, 'inter_op_num_threads', None)}"
                    f" exec={getattr(so, 'execution_mode', None)}"
                )
        except Exception as e:
            logger.error(f"Failed to init ONNX Runtime CPU: {e}")
    
    def _init_onnxruntime_npu(self):
        """使用 ONNX Runtime Ascend NPU 后端"""
        try:
            import onnxruntime as ort
            available_providers = ort.get_available_providers()
            logger.info(f"Available ONNX Runtime providers: {available_providers}")
            
            if 'CANNExecutionProvider' in available_providers:
                if self.model_path:
                    so = ort.SessionOptions()

                    intra = os.environ.get("ORT_INTRA_OP_NUM_THREADS")
                    inter = os.environ.get("ORT_INTER_OP_NUM_THREADS")
                    if intra and intra.isdigit():
                        so.intra_op_num_threads = int(intra)
                    if inter and inter.isdigit():
                        so.inter_op_num_threads = int(inter)

                    exec_mode = os.environ.get("ORT_EXECUTION_MODE", "").strip().upper()
                    if exec_mode == "SEQUENTIAL":
                        so.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
                    elif exec_mode == "PARALLEL":
                        so.execution_mode = ort.ExecutionMode.ORT_PARALLEL

                    self.session = ort.InferenceSession(
                        self.model_path,
                        sess_options=so,
                        providers=['CANNExecutionProvider', 'CPUExecutionProvider']
                    )
                    logger.info("ASR Model loaded with ONNX Runtime (NPU/CANN)")
            else:
                logger.warning("CANNExecutionProvider not available, falling back to CPU")
                self._init_onnxruntime_cpu()
        except Exception as e:
            logger.error(f"Failed to init ONNX Runtime NPU: {e}")
            self._init_onnxruntime_cpu()
    
    def _init_acl(self):
        """使用 AscendCL 直接加载 .om 模型"""
        global _ACL_INITIALIZED
        try:
            import acl
            self.acl = acl # 保存引用
            
            # 1. ACL 初始化 (仅执行一次)
            if not _ACL_INITIALIZED:
                ret = acl.init()
                if ret != 0:
                    # 507008 = ACL_ERROR_REPEAT_INITIALIZE
                    if ret == 507008:
                        logger.warning("ACL already initialized (Repeat Init).")
                    else:
                        logger.error(f"acl.init failed, ret={ret}")
                        return
                _ACL_INITIALIZED = True
            
            # 2. 设置 Device
            ret = acl.rt.set_device(0)
            if ret != 0:
                logger.error(f"acl.rt.set_device failed, ret={ret}")
                return
            
            # 3. Context 管理
            # 注意：set_device 成功后，当前线程已经有了 Context。
            # 之前的报错 (107001 create_context, 107002 get_context) 表明显式操作 Context 可能存在参数或状态问题。
            # 既然 set_device 成功，我们尝试直接使用隐式 Context，不再显式获取或创建。
            logger.info("ACL Device 0 set successfully. Using implicit context.")
                
            # 4. 加载模型
            if self.model_path and self.model_path.endswith('.om'):
                self.model_id, ret = acl.mdl.load_from_file(self.model_path)
                if ret != 0:
                    logger.error(f"acl.mdl.load_from_file failed, ret={ret}")
                    return
                
                self.model_desc = acl.mdl.create_desc()
                ret = acl.mdl.get_desc(self.model_desc, self.model_id)
                if ret != 0:
                    logger.error(f"acl.mdl.get_desc failed, ret={ret}")
                    return
                    
                logger.info(f"ASR Model loaded with ACL: {self.model_path}")
                
                # 预分配输出 Buffer (根据模型描述)
                self._prepare_acl_output_buffer()
            else:
                logger.error("Model path must end with .om for ACL mode")
            
        except ImportError:
            logger.error("ACL module not found. Please install CANN Toolkit.")
        except Exception as e:
            logger.error(f"Failed to init ACL: {e}")
            import traceback
            traceback.print_exc()

    def _prepare_acl_output_buffer(self):
        """预分配 ACL 输出 Buffer"""
        import acl
        output_size = acl.mdl.get_num_outputs(self.model_desc)
        self.output_dataset = acl.mdl.create_dataset()
        
        for i in range(output_size):
            size = acl.mdl.get_output_size_by_index(self.model_desc, i)
            dev_ptr, ret = acl.rt.malloc(size, ACL_MEM_MALLOC_NORMAL_ONLY)
            if ret != 0:
                logger.error(f"acl.rt.malloc output {i} failed, size={size}, ret={ret}")
                return
            self.output_buffers.append({"ptr": dev_ptr, "size": size})
            
            data_buffer = acl.create_data_buffer(dev_ptr, size)
            acl.mdl.add_dataset_buffer(self.output_dataset, data_buffer)
            
        logger.info(f"ACL Output buffers allocated: {output_size} outputs")

    def add_audio_buffer(self, audio_data: np.ndarray):
        """添加音频数据到缓冲区"""
        if isinstance(audio_data, bytes):
            audio_data = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32) / 32768.0
        self.audio_buffer = np.concatenate([self.audio_buffer, audio_data])
    
    def clear_audio_buffer(self):
        """清空音频缓冲区"""
        self.audio_buffer = np.array([], dtype=np.float32)
    
    def ASR_generate_text(self, audio_data: np.ndarray = None) -> str:
        """
        执行语音识别
        """
        if audio_data is None:
            audio_data = self.audio_buffer
        
        if len(audio_data) == 0:
            return ""
        
        try:
            if self.device == "acl":
                return self._process_acl(audio_data)
            elif self.session:
                return self._process_onnx(audio_data)
            else:
                logger.error("No ASR backend initialized")
                return ""
        except Exception as e:
            logger.error(f"ASR inference failed: {e}")
            import traceback
            traceback.print_exc()
            return ""

    def _process_onnx(self, audio_data):
        """ONNX Runtime 推理流程"""
        # 1. 提取特征 (560维 LFR)
        features, lengths = self._extract_features_lfr_onnx(audio_data)
        
        # 2. 准备输入
        input_names = [node.name for node in self.session.get_inputs()]
        inputs = {}
        for name in input_names:
            if "speech" in name and "length" not in name:
                inputs[name] = features
            elif "length" in name:
                inputs[name] = lengths
            elif "language" in name:
                inputs[name] = np.array([3], dtype=np.int32) # 3=zh
            elif "textnorm" in name:
                inputs[name] = np.array([1], dtype=np.int32) # 1=with_text_norm
        
        # 3. 推理
        output_names = [node.name for node in self.session.get_outputs()]
        result = self.session.run(output_names, inputs)
        
        # 4. 解码
        return self._decode_output(result)

    def _process_acl(self, audio_data):
        """ACL 推理流程"""
        import acl
        
        # 1. 提取特征并进行 LFR 堆叠 (560维)
        # 注意：ACL 模型输入是固定的 [1, 500, 560]
        features_560, valid_len = self._extract_features_lfr(audio_data, target_len=500)
        
        # 2. 准备输入数据
        # 输入顺序必须与 atc 命令一致: speech, speech_lengths, language, textnorm
        # speech: [1, 500, 560] float32
        # speech_lengths: [1] int32
        # language: [1] int32 (默认为 3 -> zh)
        # textnorm: [1] int32 (默认为 1 -> with_text_norm)
        
        input_data = []
        input_data.append(features_560) # speech
        input_data.append(np.array([valid_len], dtype=np.int32)) # speech_lengths
        input_data.append(np.array([3], dtype=np.int32)) # language (3=zh, 0=auto?)
        input_data.append(np.array([1], dtype=np.int32)) # textnorm
        
        # 3. 构建 Input Dataset
        input_dataset = acl.mdl.create_dataset()
        input_dev_ptrs = []
        
        try:
            for i, data in enumerate(input_data):
                # 确保连续内存
                if not data.flags['C_CONTIGUOUS']:
                    data = np.ascontiguousarray(data)
                
                ptr = acl.util.numpy_to_ptr(data)
                size = data.nbytes
                
                # 申请 Device 内存
                dev_ptr, ret = acl.rt.malloc(size, ACL_MEM_MALLOC_NORMAL_ONLY)
                if ret != 0:
                    raise RuntimeError(f"Malloc input {i} failed")
                input_dev_ptrs.append(dev_ptr)
                
                # 拷贝 Host -> Device
                ret = acl.rt.memcpy(dev_ptr, size, ptr, size, ACL_MEMCPY_HOST_TO_DEVICE)
                if ret != 0:
                    raise RuntimeError(f"Memcpy input {i} failed")
                
                # 添加到 Dataset
                data_buffer = acl.create_data_buffer(dev_ptr, size)
                acl.mdl.add_dataset_buffer(input_dataset, data_buffer)
            
            # 4. 执行推理
            # start_time = time.time()
            ret = acl.mdl.execute(self.model_id, input_dataset, self.output_dataset)
            if ret != 0:
                raise RuntimeError(f"acl.mdl.execute failed, ret={ret}")
            # logger.info(f"ACL Inference time: {(time.time() - start_time)*1000:.2f} ms")
            
            # 5. 获取输出
            # 假设只有一个输出 logits
            out_meta = self.output_buffers[0]
            out_host_ptr, ret = acl.rt.malloc_host(out_meta["size"])
            if ret != 0:
                raise RuntimeError("Malloc host failed")
            
            ret = acl.rt.memcpy(out_host_ptr, out_meta["size"], out_meta["ptr"], out_meta["size"], ACL_MEMCPY_DEVICE_TO_HOST)
            if ret != 0:
                raise RuntimeError("Memcpy output failed")
            
            # 转为 numpy
            # 假设输出是 float32
            out_data = acl.util.ptr_to_numpy(out_host_ptr, (out_meta["size"] // 4,), 11) # 11=NPY_FLOAT32
            
            # 释放 host 内存
            acl.rt.free_host(out_host_ptr)
            
            # Reshape: [1, 500, vocab_size] ? 需要知道 vocab_size
            # 或者直接传给 decode，decode 会处理
            # SenseVoiceSmall vocab size 约为 25000+
            # 我们可以根据 size 动态 reshape
            # [1, 500, 560] -> [1, 500, V] ? 
            # 通常输出是 [batch, time, vocab]
            
            # 简单处理：传给 decode
            # 需要 reshape 成 [1, time, vocab]
            # time=500
            vocab_size = out_data.size // 500
            out_reshaped = out_data.reshape(1, 500, vocab_size)
            
            return self._decode_output([out_reshaped])
            
        finally:
            # 6. 释放 Input 资源 (Output 复用)
            for ptr in input_dev_ptrs:
                acl.rt.free(ptr)
            if input_dataset:
                # 注意：不能 destroy dataset buffer 里的 data buffer，因为那是 create_data_buffer 创建的
                # 但是我们需要 destroy dataset 本身
                # 这里简化处理，可能存在内存泄漏，标准做法是遍历 destroy data buffer
                num = acl.mdl.get_dataset_num_buffers(input_dataset)
                for i in range(num):
                    db = acl.mdl.get_dataset_buffer(input_dataset, i)
                    acl.destroy_data_buffer(db)
                acl.mdl.destroy_dataset(input_dataset)

    def _extract_features_fbank(self, audio: np.ndarray):
        """提取基础 Fbank (80维)"""
        import torchaudio
        import torch
        
        if audio.dtype != np.float32:
            audio = audio.astype(np.float32)
        
        waveform = torch.from_numpy(audio).unsqueeze(0)
        
        # SenseVoice: 80 mel bins, 25ms window, 10ms shift
        fbank = torchaudio.compliance.kaldi.fbank(
            waveform,
            num_mel_bins=80,
            frame_length=25,
            frame_shift=10,
            dither=0.0,
            energy_floor=0.0,
            sample_frequency=16000
        )
        # [batch, time, 80]
        features = fbank.unsqueeze(0).numpy()
        lengths = np.array([features.shape[1]], dtype=np.int32)
        return features, lengths

    def _extract_features_lfr_onnx(self, audio: np.ndarray):
        """
        提取特征并进行 LFR (Low Frame Rate) 堆叠，适配 ONNX 动态输入
        Input: Audio samples
        Output: [1, T_out, 560], lengths
        """
        # 1. 先提 Fbank [1, T, 80]
        fbank, _ = self._extract_features_fbank(audio)
        fbank = fbank[0] # [T, 80]
        
        # 2. LFR 堆叠
        # m=7, n=6
        m = 7
        n = 6
        T, D = fbank.shape
        
        # 计算输出长度
        if T < m:
            # 音频太短，补零
            pad_len = m - T
            fbank = np.pad(fbank, ((0, pad_len), (0, 0)), mode='constant')
            T = m
            
        T_out = (T - m) // n + 1
        
        lfr_features = np.zeros((T_out, D * m), dtype=np.float32)
        for i in range(T_out):
            start = i * n
            end = start + m
            # [7, 80] -> [560]
            lfr_features[i] = fbank[start:end].reshape(-1)
            
        # Add batch dim: [1, T_out, 560]
        features = lfr_features[np.newaxis, :, :]
        lengths = np.array([T_out], dtype=np.int32)
        
        return features, lengths

    def _extract_features_lfr(self, audio: np.ndarray, target_len=500):
        """
        提取特征并进行 LFR (Low Frame Rate) 堆叠，适配 NPU 固定输入
        Input: Audio samples
        Output: [1, target_len, 560], valid_len
        """
        # 1. 先提 Fbank [1, T, 80]
        fbank, _ = self._extract_features_fbank(audio)
        fbank = fbank[0] # [T, 80]
        
        # 2. LFR 堆叠
        # m=7, n=6
        m = 7
        n = 6
        T, D = fbank.shape
        
        # 计算输出长度
        if T < m:
            # 音频太短，补零
            pad_len = m - T
            fbank = np.pad(fbank, ((0, pad_len), (0, 0)), mode='constant')
            T = m
            
        T_out = (T - m) // n + 1
        
        lfr_features = np.zeros((T_out, D * m), dtype=np.float32)
        for i in range(T_out):
            start = i * n
            end = start + m
            # [7, 80] -> [560]
            lfr_features[i] = fbank[start:end].reshape(-1)
            
        # 3. Padding / Truncating to target_len (500)
        curr_len = lfr_features.shape[0]
        
        if curr_len > target_len:
            # 截断
            final_features = lfr_features[:target_len]
            valid_len = target_len
        else:
            # Padding
            pad_len = target_len - curr_len
            final_features = np.pad(lfr_features, ((0, pad_len), (0, 0)), mode='constant')
            valid_len = curr_len
            
        # Add batch dim: [1, 500, 560]
        return final_features[np.newaxis, :, :], valid_len

    def _decode_output(self, results) -> str:
        """解码模型输出为文本"""
        try:
            logits = results[0]
            if len(logits.shape) == 3:
                preds = np.argmax(logits, axis=-1)[0]
            else:
                preds = np.argmax(logits, axis=-1)
                if len(preds.shape) > 1: preds = preds[0]

            tokens = []
            prev_token = -1
            blank_id = 0 
            
            for token in preds:
                if token != blank_id and token != prev_token:
                    tokens.append(token)
                prev_token = token
            
            text = ""
            for t in tokens:
                word = self.vocab.get(t, "")
                if not word.startswith("<") and not word.endswith(">"):
                    text += word
            
            return text
            
        except Exception as e:
            logger.error(f"Decoding failed: {e}")
            return ""


# ============ 工厂函数：根据配置选择后端 ============
def create_asr_model(device: str = "cpu", model_path: str = None, vocab_path: str = None):
    """
    创建 ASR 模型实例
    :param device: "cpu", "npu", "acl", "cpu-onnx"
    :param model_path: 模型文件路径
    :param vocab_path: 词表文件路径
    """
    if device in ("npu", "acl", "cpu-onnx"):
        return ASRModelNPU(model_path=model_path, vocab_path=vocab_path, device=device)
    else:
        # 回退到原有的 FunASR 实现 (cpu-torch)
        from models.asr_model import ASRModel
        return ASRModel(device=device)

