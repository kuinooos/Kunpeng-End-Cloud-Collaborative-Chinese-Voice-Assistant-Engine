## 鲲鹏端云协同中文语音助手引擎 · Server 端

### 环境搭建

``` sh
cd ./your-path
conda create --prefix ./AIChatServerEnv python=3.10
```

``` sh
conda activate ./AIChatServerEnv
pip install -r ./requirments.txt
```

搭建完毕，直接运行即可了, access_token是Client端匹配的密码，aliyun_api_key是阿里云的API key，用于访问通义千问

``` sh
python ./main.py --access_token="123456"   --aliyun_api_key="sk-474f209f9e134637ba2d7aac6a89f2fd"
```

### 文件目录介绍

```sh
Server/
├── config/                # 全局设置
├── handle/                # ws接收内容的处理
|   ├── audio_handle.py    # 音频数据处理
|   ├── auth_handle.py     # 鉴权
│   └── text_handle.py     # 文本数据处理
├── models/                # 
├── services/              # 
├── test/                  # 单功能测试
├── threads/               # 多线程相关
├── tools/                 # 工具
|   ├── audio_processor.py # 音频处理
|   ├── logger.py          # log
│   └── registry.py        # 意图注册
├── ws_server.py           # websocket server 业务
├── service_manager.py     # services 全局管理
└── main.py
```

### WebSockets协议说明

以下是Server端会向Client端发送的信息:

1. 鉴权信息：

   ```json
   {
      "type": "auth",
      "message": "Authentication failed" 
   }
   ```
   "message"还包括: "Client authenticated"

2. VAD检测到说话的活跃状态

   ```json
   {
      "type": "vad",
      "state": "no_speech" 
   }
   ```
   "state"还包括: "end", "too_long"

3. ASR识别到说话的文字

   ```json
   {
       "type": "asr",
       "text": "speech的内容"
   }
   ```

4. tts生成语音完毕

   ```json
   {
      "type": "tts",
      "state": "end"
   }
   ```
   "state"还包括: "continue"

5. 对话结束

   ```json
   {
      "type": "chat",
      "dialogue": "end"
   }
   ```
   "state"还包括: "continue"


6. 打包发送的音频数据

   ```python
    version: 协议版本 (2 字节)
    type: 消息类型 (2 字节)
    payload: opus格式消息负载 (字节)
   ```
 
### WSS/TLS 与 KAE 引擎

本服务支持可选的 WSS（TLS）模式。在 `config/settings.py` 中配置：

- `TLS_ENABLE = True`
- `TLS_CERT_FILE`、`TLS_KEY_FILE` 指向服务端证书与私钥（PEM）
- 可选：`TLS_CA_FILE`（双向认证）、`TLS_CIPHERS`、`TLS_ECDH_CURVES`

代码使用 Python 的 `ssl` 标准库创建 `SSLContext`，依赖系统 OpenSSL/Provider。
若在目标机器已启用 KAE Engine/Provider（华为鲲鹏平台），则握手与加解密可由 KAE 加速，
无需修改代码即可生效。开启方法请参考对应发行版的 KAE/OpenSSL 配置文档。

客户端需切换到 `wss://` 连接，并信任/校验证书。

### aarch64 优化与本次改动说明

为提升在鲲鹏/aarch64 CPU 上的实时性能，本次完成了以下工作：

- 集成高性能 VAD（WebRTC VAD）
   - 新增：`models/vad_model.py`，使用 `webrtcvad` 对 16k 单声道 PCM 进行流式语音活动检测。
   - 返回值与现有流程保持一致：
      - 0：继续处理
      - 1：检测到语音结束（end-of-speech）
      - 2：长时间无语音
      - 3：单段语音过长（主动截断）
   - 依赖更新：在 `Server/requirements.txt` 增加 `webrtcvad`。

- 运行时诊断与线程配置
   - 新增：`tools/diag.py`，启动时打印平台、NumPy/BLAS、PyTorch、ONNX Runtime 可用信息，便于确认是否使用了 ARM/NEON 优化路径。
   - `main.py` 在初始化后调用 `print_runtime_diagnostics()`；项目已有 `tools/affinity.configure_runtime_threads()` 用于设置 OMP/BLAS/PyTorch 线程数。

> 说明：本次改动已使 VAD 的底层计算走了适合 ARM 的高效实现。ASR 仍沿用原有 FunASR/PyTorch 路线，是否启用 aarch64 优化取决于设备上安装的 PyTorch/NumPy 轮子（如 XNNPACK/OpenBLAS 等）。如需把 ASR 也切到 aarch64 专用后端，建议导出 ONNX 并使用 ONNX Runtime（aarch64 下带 MLAS/NEON 优化），或确保安装 arm64 优化的 PyTorch/NumPy。

#### 在 aarch64 设备上的建议安装

- 使用 conda/conda-forge 安装 arm64 的 Python 依赖，确保：
   - NumPy 使用 OpenBLAS（默认即可）。
   - PyTorch/torchaudio 为 arm64 版本（如需 PyTorch 后端）。
- 运行时环境变量（示例，已由 `configure_runtime_threads()` 设置）：
   - `OMP_NUM_THREADS`、`OPENBLAS_NUM_THREADS`、`NUMEXPR_NUM_THREADS` 等按 CPU 核心适当设置。

#### 验证是否启用优化

启动 `Server/main.py` 后，日志会输出：

- 平台与架构（应显示 aarch64/arm64）。
- NumPy BLAS 配置（确认 OpenBLAS）。
- 若安装了 PyTorch：线程/XNNPACK 配置与编译信息。
- 若安装了 ONNX Runtime：providers 列表。

这些信息有助于确认是否启用了 aarch64 上的优化路径。

#### 后续可选增强

- 将 ASR 模型导出为 ONNX，改为使用 ONNX Runtime CPU 推理（aarch64 MLAS/NEON 优化）。
- 或继续使用 PyTorch，但确保安装 arm64/NEON 优化的官方/conda-forge 轮子，并按需开启 channels_last/XNNPACK。