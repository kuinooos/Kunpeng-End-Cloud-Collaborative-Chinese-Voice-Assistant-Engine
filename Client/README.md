
## 鲲鹏端云协同中文语音助手引擎 · Client 端


### 库安装

1. jsoncpp

```sh
sudo apt-get install libjsoncpp-dev
```

2. opus

```sh
sudo apt install libopus-dev
```

3. portaudio(依赖ALSA)

```sh
sudo apt-get install libasound-dev
sudo apt-get -y install libportaudio2
```

4. websocketpp(依赖boost)

```sh
sudo apt-get install libboost-dev

git clone https://github.com/zaphoyd/websocketpp.git
cd websocketpp #进入目录
cmake CMakeList.txt #执行cmake
sudo make
sudo make install
```

安装好websocketpp之后，查看是否系统有头文件了

```sh
ls /usr/local/include/websocketpp
```

### 如何编译&运行：

**注意：** Client运行之前，确保先把Server服务器跑起来，才能正常工作

```sh
mkdir build && cd build
cmake ..
make
```
然后运行即可, 这里的地址参数为Server端的IP地址, 按照你自己的设置改即可：
```sh
./build/AIChatClient 127.0.0.1 8000 123456
```

sudo ./scripts/run_client_affinity.sh \
  -e ./build/AIChatClient \
  -c "0-3" \
  -i "0" \
  -a "1" \
  -t "2-3" \
  -- \
  127.0.0.1 8000 123456

#### 清除

```sh
# in dir: build
make clean-all
```

### Websockets协议定义：

以下是Client端会向Server端发送的信息:

1. 鉴权信息：

   ```
   Authorization: "Bearer " + access_token
   Device-Id: MAC address
   Protocol-Version: 定义的协议版本
   ```

2. 发送参数

   ```json
   {
       "type": "hello",
       "audio_params": {
           "format": "opus",
           "sample_rate": "16000",
           "channels": "1",
           "frame_duration": "40"
       }
   }
   ```

3. 发送状态改变

   ```json
   {
       "type": "state", 
       "state": "idle" 
   }
   ```
    "state"还包括listening等，详见代码

4. 打包发送的音频数据

   ```cpp
   struct BinProtocol {
       uint16_t version;       //协议版本
       uint16_t type;          //0为音频数据
       uint32_t payload_size;  //音频数据长度
       uint8_t payload[];      //opus音频数据
   } __attribute__((packed));
   ```

5. 函数注册

```json
{
    "type": "reg_func",
    "functions": [
        {
            "name": "robot_move",
            "description": "让机器人运动",
            "arguments": {
                "direction": "字符数据,分别有forward,backward,left和right"
            }
        },
        {
            "name": "xxx",
            "description": "描述xxxxx",
            "arguments": {
                "arg1": "描述xxx",
                "arg2": "描述xxx"
            }
        }
    ]
}
```

6. 可能接收到的意图

```json
{
    "function_call": {
        "name": "robot_move",
        "arguments": {
            "direction": "forward",
            "speed": "1"
        }
    }
}
```

## 整体模块与职责

- WebSocket 通信层
  - `WebSocket/WebsocketClient.h/.cc`：基于 websocketpp。建立连接、附带鉴权头、收发文本/二进制、回调派发。
- 应用层入口与编排
  - main.cc：解析命令行参数，构造 `Application`。
  - `Application/Application.h/.cc`：持有各子模块；启动状态机线程；在关闭时善后。
- 状态机与状态
  - `StateMachine/StateMachine.h/.cc`：通用有限状态机（注册状态、事件、迁移）。
  - `Application/StateConfig.h/.cc`：注册业务状态与事件迁移关系。
  - `Application/UserStates/*.cc`：每个状态的 Enter/Exit/Run 逻辑：Startup/Idle/Listening/Thinking/Speaking/Fault/Stop。
- 音频采集/播放与编解码
  - `Audio/AudioProcess.h/.cc`：PortAudio 录放音、Opus 编解码、帧打包/解包（`BinProtocol`）与播放队列。
- 消息处理与意图
  - `Application/WS_Handler.h/.cc`：服务端发来的 JSON/二进制消息处理；驱动状态事件；把音频二进制解码入播放队列。
  - `Application/IntentsRegistry.h/.cc`：向服务端注册本地支持的“函数调用”元信息（function calling）。
  - `Intent/IntentHandler.h/.cc`：静态注册和派发 function_call 回调。
  - `Application/UserIntents/RobotMove.*`：一个示例意图回调（打印 direction）。

## 启动与连接（包含鉴权）

1) main 解析参数并构造 Application
- 文件：main.cc
- 命令行：server 地址、端口、token（令牌），并在 main.cc 内设定默认 `deviceId = "00:11:22:33:44:55"`、`protocolVersion = 2`。
- Application 构造时，内部创建 `WebSocketClient` 并设置消息/关闭回调。

2) 状态机启动 → 进入 Startup
- 文件：Application.cc、StateConfig.cc
- 状态机初始状态是 `startup`，进入 `StartupState::Enter()`。

3) Startup 中建立 WebSocket 连接并重试
- 文件：Startup.cc
- 调用：
  - `app->ws_client_.Run()` 启动网络线程
  - `app->ws_client_.Connect()` 发起握手
  - 最多重试 3 次（每次 sleep 5s）

4) 客户端连接时附带的请求头
- 文件：WebsocketClient.cc
- 在构造函数里设置：
  - Authorization: Bearer <token>
  - Device-Id: 00:11:22:33:44:55（默认）
  - Protocol-Version: 2（字符串）
- 在 `Connect()` 调用 `con->append_header()` 注入到握手请求。

这与服务端 `AuthHandler` 完全对齐：服务端会在握手后读取这些请求头进行校验。

5) 连接成功后发送 hello 和函数注册
- 文件：Startup.cc
- 发送 hello JSON，包含音频参数（opus、采样率/通道/帧时长）
- 调用 `IntentsRegistry::RegisterAllFunctions()` 把本地意图回调注册到 `IntentHandler`
- 生成 `functions_register` JSON 发给服务端，告知本地支持的 function 列表与参数

6) Startup 完成 → 发送 `startup_done` 事件，状态机跳转到 idle

## 状态与事件如何流转

状态注册与转移图（StateConfig.cc）：
- startup --(startup_done)--> idle
- idle --(wake_detected)--> speaking
- listening --(vad_no_speech)--> idle
- listening --(asr_received)--> thinking
- thinking --(speaking_msg_received)--> speaking
- speaking --(speaking_end)--> listening
- speaking --(dialogue_end)--> idle
- 任意 --(fault_happen)--> fault
- 任意 --(to_stop)--> stopping
- fault --(fault_solved)--> idle

事件触发来源：
- 本地：唤醒词检测、TTS 播放完毕、对话结束等
- 服务端消息：VAD/ASR/TTS/CHAT JSON，或首帧音频到达时触发 speaking_msg_received

WS 消息处理（WS_Handler.cc）：
- 文本 JSON：
  - type=vad 且 state=no_speech → 事件 vad_no_speech
  - type=asr → 事件 asr_received（并打印文本）
  - type=tts 且 state=end → 标记 tts_completed=true
  - type=chat 且 dialogue=end → 标记 dialogue_completed=true
  - 有 function_call 对象 → 调 `IntentHandler::HandleIntent()`，并将消息入 `IntentQueue_`
- 二进制（服务端 TTS 音频帧）：
  - 第一次收到二进制时触发 speaking_msg_received（用于从 thinking 切到 speaking）
  - 调 `AudioProcess::UnpackBinFrame()` 解包出 Opus → `decode` 成 PCM → 入播放队列

## 各状态做什么

- Startup
  - 建连、鉴权、hello、注册意图 → startup_done → idle
- Idle
  - 发送 `{"type":"state","state":"idle"}` 给服务端
  - 开启录音、用 Snowboy 做离线唤醒检测
  - 检测到唤醒词 → wake_detected → speaking
  - Exit 时播放一段“唤醒音”，并把 `tts_completed` 置 true（驱动 Speaking 的结束判定）
- Speaking
  - 发送 `{"type":"state","state":"speaking"}`
  - 开启播放，消费播放队列中的 PCM（来自服务端的 TTS 二进制）
  - 每 500ms 检查：若 `tts_completed==true` 且播放队列空：
    - 若 `dialogue_completed==false` → speaking_end → listening
    - 若 `dialogue_completed==true` → dialogue_end → idle
  - Exit：清播放队列，停止播放
- Listening
  - 发送 `{"type":"state","state":"listening"}`
  - 开启录音，循环获取录音帧：
    - encode(Opus) → Pack(`BinProtocol`) → 通过 WebSocket 以二进制发送到服务端
  - 服务端侧据此进行 VAD、ASR、对话生成、TTS 等
  - Exit：停止录音
- Thinking
  - 发送 `{"type":"state","state":"thinking"}`
  - 等候服务端返回首帧 TTS 二进制，WS_Handler 在首次二进制到达时发 speaking_msg_received → speaking
- Fault/Stop
  - 简单的故障与停止处理；Stop 是整体退出前的清理阶段

## 音频协议与编解码

- 录音与播放：`Audio/AudioProcess.*` 使用 PortAudio；录音帧进 recorded 队列，播放帧来自 WS_Handler 解析后的 PCM 放入 playback 队列
- Opus 编解码：`encode()`/`decode()` 使用 libopus。Listening 状态中把采集帧编码成 Opus 后再打包；WS_Handler 收到服务端二进制后先解包、再解码为 PCM 播放
- 二进制打包协议：`BinProtocol`（头部含 version/type/payload_size + payload）
  - version 要与 `Application` 的 `ws_protocolVersion_` 对上（默认 2）
  - type=0 表示 TTS 音频帧（从 WS_Handler 的判断看出）

## 意图注册与执行

- 注册阶段：`IntentsRegistry::RegisterAllFunctions()` → 把 "robot_move" 绑定到 `RobotMove::Move`
- 上报给服务端：发送 `{"type":"functions_register","functions":[...meta...]}` 告知本地支持的函数及参数说明
- 执行阶段：服务端下发带有
  ```
  {
    "function_call": {
      "name": "robot_move",
      "arguments": { "direction": "forward", "speed": 3, "duration": 1.2 }
    }
  }
  ```
  的 JSON → `WS_Handler` 调 `IntentHandler::HandleIntent()` → 根据 name 查找到 `RobotMove::Move` 执行
- 示例回调：`RobotMove::Move` 里示例地打印了 direction（你可以替换成实际电机/机器人控制逻辑）

## 一次真实时序举例

- 启动服务端（鉴权要求：Authorization Bearer 123456、Device-Id、Protocol-Version）
- 启动客户端：
  - `AIChatClient.exe 127.0.0.1 8000 123456`
- Startup：
  - 握手时携带头：Authorization/Device-Id/Protocol-Version
  - 鉴权成功 → 服务端发 {"type":"auth","message":"Client authenticated"}
  - 客户端发 hello + functions_register
  - 事件 startup_done → idle
- Idle：
  - 开启录音+唤醒检测
  - 用户说“唤醒词” → wake_detected → speaking
  - Exit 时播放一小段“唤醒音”，并置 tts_completed=true
- Speaking：
  - 开始播放（此时播放的是“唤醒音”的 PCM）
  - 因 tts_completed==true 且播放队列空 → speaking_end → listening
- Listening：
  - 开启录音并不断发送 Opus 帧（二进制，协议 version=2）
  - 服务端进行 VAD：若检测到静音 → 发 {"type":"vad","state":"no_speech"} → 触发 vad_no_speech → idle
  - 服务端进行 ASR：识别文本 → 发 {"type":"asr","text":"..."} → 触发 asr_received → thinking
- Thinking：
  - 等服务器生成回复与 TTS 音频
  - 服务器开始下发 TTS 二进制数据 → 客户端首次收到二进制 → speaking_msg_received → speaking
- Speaking：
  - 播放来自服务端的 TTS PCM
  - 期间服务器可能发 {"type":"chat","dialogue":"end"}（对话结束）和 {"type":"tts","state":"end"}（语音播报结束）
  - 当 `tts_completed==true` 且播放队列空：
    - 若对话已结束 → dialogue_end → idle
    - 否则 → speaking_end → listening（继续轮次）
- 任何异常（解析失败、网络断开）→ fault_happen → fault
