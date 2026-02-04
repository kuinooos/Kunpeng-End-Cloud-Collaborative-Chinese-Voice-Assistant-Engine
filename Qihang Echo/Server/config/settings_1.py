try:
    import dashscope  # type: ignore
except Exception:  # 在未安装环境下允许导入通过，便于静态检查
    class _DashScopeStub:
        api_key = None
    dashscope = _DashScopeStub()

class Settings:
    protocol_version = 2
    # 机器人名称（影响对话人设与自我介绍）
    ROBOT_NAME = "鲲鹏"
    # 项目名称（用于对外自我介绍）
    PROJECT_NAME = "鲲鹏端云协同中文语音助手引擎"
    # ========== LLM 配置（默认本地） ==========
    # LLM 后端：
    # - "local_ascend_qwen_om": 使用 Ascend ACL 直接跑 .om（参考 llm_ascend_poc/scripts/chat_qwen.py）
    # - "dashscope": 阿里云 DashScope（云端，不建议离线场景）
    LLM_ENGINE = "local_ascend_qwen_om"
    # LLM_ENGINE = "DashScope"

    # DashScope API Key（仅云端模式需要）。不要把密钥写进代码仓库。
    DASHSCOPE_API_KEY = "sk-99cc5293093c4c6a8819c32683bcb834"
    dashscope.api_key = "sk-99cc5293093c4c6a8819c32683bcb834"

    # 仅 dashscope 模式时使用的模型名
    INTENT_MODEL = "qwen-turbo"       # 专门用于意图识别
    CHAT_MODEL = "qwen-turbo"         # 用于常规对话

    # 本地 Ascend-OM Qwen 配置
    LOCAL_LLM_DEVICE_ID = 0
    LOCAL_LLM_OM_PATH = "/root/kunpengChat/Server/models/Qwen/qwen2.5_0.5b_chat.om"            # 例如: /home/openEuler/models/qwen2.5-0.5b-chat.om
    LOCAL_LLM_TOKENIZER_PATH = "/root/kunpengChat/Server/models/Qwen/qwen_tokenizer"     # 例如: /home/openEuler/models/qwen_tokenizer
    LOCAL_LLM_MAX_SEQ_LEN = 1024
    LOCAL_LLM_VOCAB_SIZE = 151936
    LOCAL_LLM_KV_NUM_LAYERS = 96
    LOCAL_LLM_KV_HEAD_DIM = 64

    # 本地采样参数（可按需调整）
    LOCAL_LLM_TEMPERATURE = 0.8
    LOCAL_LLM_TOP_P = 0.95
    LOCAL_LLM_TOP_K = 50
    LOCAL_LLM_REPETITION_PENALTY = 1.2
    LOCAL_LLM_MIN_NEW_TOKENS = 12
    LOCAL_LLM_NO_REPEAT_NGRAM = 3
    LOCAL_LLM_MAX_NEW_TOKENS = 256

    # ========== 本地 TTS（默认） ==========
    # 使用 Piper CLI 离线合成，输出 16kHz int16 PCM（必要时重采样）
    TTS_ENGINE = "piper"  # "piper" (默认离线) 或 "dashscope" (云端)
    LOCAL_TTS_PIPER_BIN = "/root/kunpengChat/Server/third_party/piper/piper"  # 可填写绝对路径
    LOCAL_TTS_MODEL_PATH = "/root/kunpengChat/Server/models/tts/zh_CN-huayan-medium.onnx"       # e.g. /home/openEuler/models/tts/zh_CN-voice.onnx
    LOCAL_TTS_SPEAKER = None
    LOCAL_TTS_OUTPUT_SAMPLE_RATE = 16000

    # device
    # ASR 模型使用的设备: 
    # "cpu-torch" : 使用 PyTorch 原生推理 (CPU)
    # "cpu-onnx"  : 使用 ONNX Runtime 推理 (CPU)
    # "acl"       : 使用 AscendCL 直接推理 (.om 模型)
    # 说明：
    # - 默认/推荐："cpu-onnx"（ONNX Runtime CPU）——部署简单、可移植、调试友好，适用于 x86/aarch64 通用平台；
    #   ONNX Runtime 在不同平台上有针对性的优化（如 MLAS/NEON），能在没有 NPU 的情况下获得较好性能。
    # - 昇腾/NPU（"acl" 或 使用 onnxruntime-ascend 的 "npu"）需要额外依赖（CANN、特定驱动、onnxruntime-ascend 或 acl python 包），且模型需转换为 .om 格式，非开箱即用。
    # - 如果要尝试 NPU：请先在部署节点上验证 `ort.get_available_providers()` 或能成功 `import acl`。
    # 示例验证命令：
    #   python -c "import onnxruntime as ort; print(ort.get_available_providers())"
    #   python -c "import acl; print('acl OK')"
    ASR_DEVICE = "cpu-onnx"            # ASR 模型使用的设备
    
    VAD_DEVICE = "cpu"            # VAD 模型使用的设备 (webrtcvad 仅支持 CPU)
    
    # 模型路径配置
    # ONNX 模型路径 (用于 cpu-onnx)
    ASR_ONNX_MODEL_PATH = "/root/kunpengChat/Server/models/sensevoice_onnx_quant/model_quant.onnx"
    # OM 模型路径 (用于 acl)
    ASR_OM_MODEL_PATH = "/home/openEuler/KunpengChat/Server/models/sensevoice_small_310b1.om"
    
    # 兼容旧代码的属性 (ASR_NPU_MODEL_PATH)
    @property
    def ASR_NPU_MODEL_PATH(self):
        if self.ASR_DEVICE == "acl":
            return self.ASR_OM_MODEL_PATH
        else:
            return self.ASR_ONNX_MODEL_PATH
    # SenseVoice 词表路径 (通常在下载的模型目录中)
    ASR_VOCAB_PATH = "/root/kunpengChat/Server/models/FunAudioLLM/iic/SenseVoiceSmall/tokens.json"

    # 超时设置
    API_TIMEOUT = 10  # 秒
    
    # ========== 音频处理配置 ==========
    # VAD 专用噪声门阈值 (RMS): 仅用于 VAD 判断，不影响 ASR 识别
    # 调高此值可以解决“一直处于讲话状态”的问题，而不影响识别准确率
    # 建议值: 300-800
    VAD_NOISE_THRESHOLD = 200
    
    # VAD 激进程度: 0-3 (建议 1 或 2)
    VAD_AGGRESSIVENESS = 1

    def Set_API_Key(self, aliyun_api_key):
        # 兼容旧启动参数：允许从 CLI 传入 key，但不要硬编码到仓库
        self.DASHSCOPE_API_KEY = aliyun_api_key
        try:
            dashscope.api_key = aliyun_api_key
        except Exception:
            pass

    #根据您的硬件资源（特别是鲲鹏 CPU 的核心数和 NUMA 节点布局）和程序中各个任务的性能需求，
    # 为每一类线程分配一组专用的、物理上最优的 CPU 核心。
    # ========== 性能/亲和配置 ==========
    # 是否启用 CPU 亲和绑定（进程/线程）
    ENABLE_AFFINITY = False
    # 进程级 CPU 亲和（字符串或列表；例如 "0-15" 或 [0,1,2,3]）
    PROCESS_CPU_SET = None
    # 各类线程建议绑定的 CPU 集（可按实际核数修改）。None 表示不设置。
    THREAD_CPU_SETS = {
        # WebSocket/事件循环（处理收发、VAD+ASR 预处理）
         "io_ws": None,           # 例如 "0-7"
        # 发送音频（AudioSendThread）
        "audio_send": None,     # 例如 "8-11"
        # TTS 生成线程（TTSGenerateThread）
        "tts": None,            # 例如 "12-15"
        # LLM/对话/ASR 任务线程（由线程池执行）
        "task_worker": None     # 例如 "16-23"
    }
    # 线性代数线程（OpenBLAS/KML/OMP）默认线程数（按实例与 CPU 资源分配）
    THREADS_LINEAR_ALG = 8
    # PyTorch 计算与互操作线程
    TORCH_NUM_THREADS = 8
    TORCH_NUM_INTEROP_THREADS = 2

    # ========== TLS/WSS 配置 ==========
    # 是否启用 WSS（TLS）
    TLS_ENABLE = False
    # 服务器证书与私钥路径（PEM）
    TLS_CERT_FILE = None
    TLS_KEY_FILE = None
    # 可选：客户端 CA（双向认证）
    TLS_CA_FILE = None
    # 可选：自定义密码套件（留空使用系统默认）
    TLS_CIPHERS = None  # 例如："TLS_AES_128_GCM_SHA256:TLS_CHACHA20_POLY1305_SHA256"
    # 可选：ECDH 优先曲线
    TLS_ECDH_CURVES = "X25519:P-256"

global_settings = Settings()
    
