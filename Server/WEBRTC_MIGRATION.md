# WebRTC迁移指南 - 从WebSocket到WebRTC低延迟传输

本文档说明如何将项目从WebSocket迁移到WebRTC以获得更低的延迟和更好的实时性能。

## 架构优势对比

### WebSocket (TCP)
- ❌ **队头阻塞**: 一个丢包会阻塞后续所有数据
- ❌ **重传延迟**: 丢包后必须重传，累积延迟
- ❌ **有序传输**: 强制顺序，音频帧必须等待前序帧
- ✅ **可靠性**: 100%保证数据到达

### WebRTC DataChannel (UDP)
- ✅ **零队头阻塞**: 丢包不影响后续数据传输
- ✅ **可配置重传**: Audio通道设置为0重传，允许丢包
- ✅ **乱序传输**: 音频帧独立传输，不等待
- ✅ **极低延迟**: 典型延迟 < 100ms

## 服务端安装

### 1. 安装依赖

```bash
# Python服务端依赖
pip install aiortc aiohttp opencv-python

# aiortc依赖的系统库 (Ubuntu/Debian)
sudo apt-get install libavdevice-dev libavfilter-dev libopus-dev libvpx-dev pkg-config

# aiortc依赖的系统库 (CentOS/RHEL/openEuler)
sudo yum install libavdevice libavfilter opus-devel libvpx-devel pkgconfig
```

### 2. 启动WebRTC服务器

```bash
cd Server

# WebRTC模式 (推荐，低延迟)
python main_webrtc.py --host 0.0.0.0 --port 8000 --webrtc

# WebSocket模式 (传统模式)
python main_webrtc.py --host 0.0.0.0 --port 8000

# 或使用原有启动方式
python main.py  # 默认WebSocket模式
```

### 3. 验证服务器

访问 `http://localhost:8000/` 应该看到服务器状态页面。

## 客户端安装

### 1. 安装libdatachannel

libdatachannel是轻量级WebRTC库，专为嵌入式和C++环境设计。

#### Ubuntu/Debian
```bash
# 安装编译依赖
sudo apt-get install cmake git libssl-dev

# 克隆并编译
git clone https://github.com/paullouisageneau/libdatachannel.git
cd libdatachannel
git submodule update --init --recursive

mkdir build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release \
         -DUSE_GNUTLS=OFF \
         -DUSE_NICE=OFF \
         -DNO_EXAMPLES=ON \
         -DNO_TESTS=ON

make -j$(nproc)
sudo make install
sudo ldconfig
```

#### CentOS/RHEL/openEuler (鲲鹏服务器)
```bash
# 安装编译依赖
sudo yum install cmake3 git openssl-devel

# 克隆并编译
git clone https://github.com/paullouisageneau/libdatachannel.git
cd libdatachannel
git submodule update --init --recursive

mkdir build && cd build
cmake3 .. -DCMAKE_BUILD_TYPE=Release \
          -DUSE_GNUTLS=OFF \
          -DUSE_NICE=OFF \
          -DNO_EXAMPLES=ON \
          -DNO_TESTS=ON

make -j$(nproc)
sudo make install
echo "/usr/local/lib" | sudo tee /etc/ld.so.conf.d/libdatachannel.conf
sudo ldconfig
```

### 2. 编译客户端

修改CMakeLists.txt或Makefile，添加WebRTC支持：

```cmake
# CMakeLists.txt示例
find_package(LibDataChannel REQUIRED)

add_executable(aichat_client
    main.cc
    Application/Application.cc
    WebRTC/WebRTCClient.cc
    # ... 其他源文件
)

target_compile_definitions(aichat_client PRIVATE USE_LIBDATACHANNEL)
target_link_libraries(aichat_client PRIVATE datachannel pthread)
```

或使用g++直接编译：

```bash
cd Client

g++ -std=c++17 -DUSE_LIBDATACHANNEL \
    -o aichat_client \
    main.cc \
    Application/Application.cc \
    WebRTC/WebRTCClient.cc \
    $(find . -name "*.cc") \
    -ldatachannel -lpthread -lopus -ljsoncpp
```

## 使用方式

### 服务端

```bash
# 启动WebRTC服务器（推荐）
python main_webrtc.py --webrtc --port 8000

# 查看帮助
python main_webrtc.py --help
```

### 客户端

客户端代码会自动检测WebRTC支持：

```cpp
// 在Application.cc中
#ifdef USE_LIBDATACHANNEL
    // 使用WebRTC客户端
    webrtc_client_ = new WebRTCClient(server_address, server_port, token, device_id);
    webrtc_client_->Connect();
#else
    // 回退到WebSocket
    ws_client_.Connect(ws_url);
#endif
```

## 性能测试

### 延迟对比测试

```bash
# 测试WebSocket延迟
python test_latency.py --mode websocket

# 测试WebRTC延迟
python test_latency.py --mode webrtc
```

预期结果：
- WebSocket: 200-500ms (弱网环境可能>1s)
- WebRTC: 50-150ms (稳定在100ms以内)

### 丢包容忍度测试

```bash
# 模拟5%丢包率
sudo tc qdisc add dev eth0 root netem loss 5%

# 测试音频质量
# WebSocket: 卡顿、断续
# WebRTC: 轻微模糊但连贯
```

## 故障排查

### 服务端问题

**问题**: `ModuleNotFoundError: No module named 'aiortc'`
```bash
pip install aiortc aiohttp
```

**问题**: `ImportError: libopus.so: cannot open shared object file`
```bash
# Ubuntu
sudo apt-get install libopus0

# CentOS
sudo yum install opus
```

### 客户端问题

**问题**: 编译时找不到`rtc/rtc.hpp`
```bash
# 确认libdatachannel已安装
pkg-config --modversion libdatachannel

# 添加包含路径
export CPLUS_INCLUDE_PATH=/usr/local/include:$CPLUS_INCLUDE_PATH
export LIBRARY_PATH=/usr/local/lib:$LIBRARY_PATH
```

**问题**: 运行时找不到libdatachannel.so
```bash
export LD_LIBRARY_PATH=/usr/local/lib:$LD_LIBRARY_PATH
# 或永久添加
echo "/usr/local/lib" | sudo tee /etc/ld.so.conf.d/libdatachannel.conf
sudo ldconfig
```

### 连接问题

**问题**: ICE连接失败
- 检查防火墙是否允许UDP流量
- 如果在NAT后面，可能需要STUN/TURN服务器
- 局域网环境通常不需要STUN

**问题**: DataChannel不打开
- 检查服务器日志，确认Offer/Answer交换成功
- 验证SDP格式正确
- 确认客户端和服务端协议版本匹配

## 性能调优建议

### Audio DataChannel配置
```cpp
// 客户端：极致低延迟配置
audio_config.reliability.rexmit = 0;        // 零重传
audio_config.reliability.unordered = true;  // 允许乱序
audio_config.reliability.type = rtc::Reliability::Type::Rexmit;
```

### 服务端优化
```python
# 减少发送队列检查间隔
await asyncio.sleep(0.01)  # 10ms轮询，降低延迟
```

### 系统优化
```bash
# 增加UDP缓冲区
sudo sysctl -w net.core.rmem_max=8388608
sudo sysctl -w net.core.wmem_max=8388608
```

## 兼容性说明

该实现保持了与原WebSocket客户端相同的接口，可以通过编译开关在WebSocket和WebRTC之间切换：

```cpp
#ifdef USE_LIBDATACHANNEL
    // 编译时包含WebRTC支持
#else
    // 回退到WebSocket
#endif
```

这允许渐进式迁移，无需一次性重写所有代码。

## 参考资源

- [aiortc文档](https://aiortc.readthedocs.io/)
- [libdatachannel GitHub](https://github.com/paullouisageneau/libdatachannel)
- [WebRTC DataChannel API](https://developer.mozilla.org/en-US/docs/Web/API/RTCDataChannel)

## 技术支持

遇到问题请检查：
1. 服务端和客户端日志
2. 网络连接状态
3. 依赖库版本兼容性

更多信息参考项目README.md。
