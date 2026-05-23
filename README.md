<h2 align="center">1. 鲲鹏端云协同中文语音助手引擎</h2>
<p align="center">
    <img border="1px" width="100%" src="./assets/architecture/AIChat_Architecture.png">
</p>
请确保[Server](./Server/README.md)运行起来, 再运行[Client](./Client/README.md).


## 功能总览

端到端中文语音助手，组件化可扩展：

- 流式语音管线：VAD → ASR → Chat/LLM → Intent → TTS → 播放
- 服务端（Python）：
    - VAD：基于 webrtcvad 的实时语音端点检测（`models/vad_model.py`、`services/vad_service.py`）
    - ASR：FunASR/PyTorch 路径（可选扩展 ONNX Runtime 以优化 aarch64）
    - Chat：系统提示词内置“自我介绍为‘鲲鹏’”，并做跨分片别名统一替换，避免“Echo”等泄漏（`services/chat_service.py`、`service_manager.py`）
    - Intent：意图识别到动作映射，统一注册表（`tools/registry.py`、`services/intent_service.py`）
    - TTS：TTS 包装与流式合成（`services/tts_service.py`）
    - WS/WSS：WebSocket 服务，支持 TLS（`ws_server.py`、`tools/tls.py`、`config/settings.py`）
- 客户端（C++）：
    - 采集/回放：PortAudio（参考 `Client/Audio/AudioProcess.*`）
    - 编解码：Opus（aarch64 默认启用 NEON）
    - 网络：websocketpp（`Client/WebSocket/WebsocketClient.*`）
    - 状态机与意图：`Client/Application/*`、`Intent/*`、`Application/UserIntents/*`
    - 硬件抽象：`Client/Hardware/*`（GPIO/LED/Motor 等）
    - 演示工具：`Client/MOTORtest/`（独立步进电机测试）

服务端日志在 `Server/logs/`，客户端日志在控制台输出，可按需扩展到文件。

---


## 在 openEuler 绑定 CPU 与内存亲和（鲲鹏专项）

在多核鲲鹏平台上，为降低关键线程的调度抖动、缓存穿越和跨 NUMA 迁移带来的性能波动，可在运行阶段使用 numactl 或 taskset 对进程做 CPU 与内存亲和绑定。

我们提供了两个启动脚本（优先使用 numactl，不存在则回退到 taskset）：

- `scripts/run_client_affinity.sh`：用于客户端 `AIChatClient`
- `scripts/run_server_affinity.sh`：用于 Python Server（`Server/main.py`）

示例（假设 NUMA 节点 0，CPU 0-7 给客户端）：

```bash
./scripts/run_client_affinity.sh -e ../Client/build/AIChatClient -c "0-7" -m 0 -- --your-client-args
```

示例（服务端绑定到 CPU 8-31，NUMA 1）：

```bash
./scripts/run_server_affinity.sh -c "8-31" -m 1 -- --your-server-args
```

脚本参数说明：

- `-c`: 绑定的 CPU 集（如 `"0-7"` 或 `"0,2,4,6"`）
- `-m`: 绑定的 NUMA 节点（同时用于 `--cpunodebind/--membind`）
- `-e`: 客户端可执行路径（client 脚本）或 `-e` 指定 Python 解释器（server 脚本）
- `-s`: 服务端入口脚本路径（server 脚本）

进阶：如果你希望在应用内部对不同线程进一步细分亲和（例如 IO/WS、音频编解码、任务线程分配不同核心集合），`run_client_affinity.sh` 会导出以下环境变量供应用读取：

- `AICHAT_IO_CORES`
- `AICHAT_AUDIO_CORES`
- `AICHAT_TASK_CORES`

你可以在代码中读取这些变量，并调用 `Client/Utils/affinity.h` 的 `set_current_thread_affinity("0-3")` 在各线程入口处完成更细粒度绑定。

注意：

- 生产环境建议将 Server 与 Client 分别绑定到不同 CPU 集合，NUMA 服务器上可进一步分配到不同内存节点，互不干扰。
- 如果系统无 `numactl`，脚本会自动回退为 `taskset -c`；若两者都不可用，将直接运行（无绑定）。

## 按平台选择：NUMA 服务器 vs 非 NUMA 开发板

### 情形 A：Kunpeng 920/930（NUMA，多内存节点）

特征：多路/多 NUMA 节点服务器，跨节点访问带来额外延迟。

推荐做法：

- 将 Server 与 Client（或不同服务，如 ASR/TTS/Chat）分配到不同的 NUMA 节点与 CPU 集合，计算和内存都“就近”。
- 使用 `-m <node>` 同时进行 CPU 节点与内存绑定（`--cpunodebind/--membind`），并用 `-c` 指定该节点内的 CPU 核集合。

示例：

```bash
# Client 绑定到 Node 0，使用 0-31 号核
./scripts/run_client_affinity.sh -e ../Client/build/AIChatClient -c "0-31" -m 0 -- --your-client-args

# Server 绑定到 Node 1，使用 32-63 号核
./scripts/run_server_affinity.sh -c "32-63" -m 1 -- --your-server-args
```

预期效果：

- 降低跨节点内存访问带来的尾延迟抖动，提升缓存命中与带宽利用。
- Server/Client 互不抢占同一节点资源，整体吞吐与稳定性更好。

验证（可选）：

```bash
numactl -H                 # 查看 NUMA 拓扑
taskset -cp <pid>          # 查看进程 CPU 亲和
ps -L -o pid,tid,psr -p <pid> | head   # 采样线程所在 CPU
```

### 情形 B：OrangePi Kunpeng Pro（单 NUMA 开发板）

特征：4 核 ARM64，通常为单 NUMA 节点；`-m`（内存绑定）收益不明显，但 CPU 亲和依然有效。

推荐做法：

- 重点使用 `-c` 进行进程级 CPU 亲和，配合 `-i/-a/-t` 给不同职责线程分配不同核心，减少互相干扰。
- 示例分配：IO/WS→核0，音频→核1，计算（ASR/VAD/TTS）→核2-3。

示例：

```bash
./scripts/run_client_affinity.sh -e ../Client/build/AIChatClient -c "0-3" -i "0" -a "1" -t "2-3" -- --your-client-args
./scripts/run_server_affinity.sh -c "0-3" -- --your-server-args
```

预期效果：

- 音频与网络线程获得稳定时延，减少与重计算线程的抢占冲突，端到端 P95/P99 更稳。
- 在资源紧张（4 核）场景，关键路径“保底”能力更强，交互更顺滑。

验证（可选）：

```bash
taskset -cp <pid>
ps -L -o pid,tid,psr -p <pid> | head
```

提示：若需要在应用内部进一步细分线程亲和，请在相应线程入口读取 `AICHAT_IO_CORES`、`AICHAT_AUDIO_CORES`、`AICHAT_TASK_CORES` 并调用 `Client/Utils/affinity.h` 中的 `set_current_thread_affinity()`。

在 Application.cc 的状态机事件线程入口亲和设置：
读取 AICHAT_TASK_CORES 并调用 set_current_thread_affinity(...)。
在 AudioProcess.cc 的 PortAudio 回调线程加了亲和设置：
录音回调 recordCallback(...) 和播放回调 playCallback(...) 首次进入时读取 AICHAT_AUDIO_CORES 并对“当前回调线程”设置亲和（thread_local 只设置一次）。
 WebsocketClient.cc  IO/WS 线程亲和（读取 AICHAT_IO_CORES，默认绑定到 0）。
