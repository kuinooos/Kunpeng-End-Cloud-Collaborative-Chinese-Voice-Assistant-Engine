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
python ./main.py --access_token="123456"   --aliyun_api_key="sk-99cc5293093c4c6a8819c32683bcb834"

# WebRTC模式 (推荐，低延迟)
python main_webrtc.py --host 0.0.0.0 --port 8000 --webrtc

# WebSocket模式 (传统模式)
python main_webrtc.py --host 0.0.0.0 --port 8000

# 或使用原有启动方式
python main.py  # 默认WebSocket模式
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

#### 如何在鲲鹏展示 `cpu-onnx` 优势

- 目标：证明在鲲鹏平台上 `cpu-onnx` 能利用多核/指令集优化，具备部署与性能优势。
- 步骤：
  1. 在目标机器上运行运行时诊断：
     ```bash
     python -c "from tools.diag import print_runtime_diagnostics; print_runtime_diagnostics()"
     ```
     确认显示：平台为 aarch64、ONNX Runtime providers（包含 CPU）、以及 CPU 支持 NEON/ASIMD。
  2. 运行基准脚本（项目已提供）：
     ```bash
     export OMP_NUM_THREADS=8
     export OPENBLAS_NUM_THREADS=8
     python test/benchmark_asr_cpu.py
     ```
     该脚本会分别尝试 `cpu-onnx` 与 `cpu-torch`（若模型可用），并输出 P50/P95 延迟与示例输出；截取这些日志作为实验结果。
  3. 通过绑定 CPU 亲和性（参考 `config/settings.py` 的 `THREAD_CPU_SETS`），重复跑一次基准，记录性能提升。建议用 `taskset` 或 `numactl` 固定进程/线程到指定核。
  4. 将诊断输出与基准数据截图放入 PPT：突出 `cpu-onnx` 在无 NPU 环境下的稳定性、低运维成本与平台优化利用（如 MLAS/NEON、OpenBLAS 线程控制）。

- 小提示：若想展示 NPU 加速（可选），请在受控硬件上完成 CANN/ACL 安装并验证 `CANNExecutionProvider` 或 `import acl` 成功，再使用 `.om` 模型跑对比基准。

#### 后续可选增强

- 将 ASR 模型导出为 ONNX，改为使用 ONNX Runtime CPU 推理（aarch64 MLAS/NEON 优化）。
- 或继续使用 PyTorch，但确保安装 arm64/NEON 优化的官方/conda-forge 轮子，并按需开启 channels_last/XNNPACK。

#### 关于 NPU 支持（当前状态与建议）

- 状态：Ascend / 昇腾 NPU（CANN/ACL）加速的代码路径在项目中有相关实现思路（`models/asr_model_npu.py`），但在常见部署环境下尚未做到开箱即用，因此在默认配置下我们使用 `cpu-onnx` 或 PyTorch CPU 后端。
- 建议：将 ASR 部署为 `cpu-onnx`（ONNX Runtime CPU 执行器）通常是更稳健、可移植的选择，原因包括：
   - 部署简单：不依赖专用驱动/工具链（如 CANN、atc、昇腾系统镜像）。
   - 可移植性强：在 x86/aarch64 通用主机上都能运行，并可借助 ONNX Runtime 的平台优化（MLAS/NEON）。
   - 易于调试：使用常规 Python 环境和 `onnxruntime` 更容易定位问题，无需进入 NPU 驱动层面。
   - 更低的运维成本：无需维护 NPU 固件/驱动、特定版本的 toolchain 或生成 `.om` 模型。

- 如果确实要启用昇腾 NPU 加速，需要满足前置条件：
   - 安装并配置好 CANN Toolkit / 昇腾驱动，以及 `onnxruntime-ascend`（或使用 AscendCL 的 `.om` 路径和 `acl` Python 包）。
   - 使用与硬件与 CANN 版本匹配的模型格式（通常为 `.om`），并在部署节点上验证 `ort.get_available_providers()` 或 `import acl` 成功。

- 快速验证命令：
   - 验证 ONNX Runtime providers：
      ```bash
      python -c "import onnxruntime as ort; print(ort.get_available_providers())"
      ```
   - 验证 Ascend ACL 接口：
      ```bash
      python -c "import acl; print('acl OK')"
      ```

我们推荐在开发与跨平台验证阶段先使用 `cpu-onnx`，待上层功能、性能基线确认后再在受控硬件上做 NPU 加速尝试与验证。