#ifndef WEBRTC_CLIENT_H
#define WEBRTC_CLIENT_H

#include <string>
#include <vector>
#include <functional>
#include <thread>
#include <memory>
#include <atomic>
#include <mutex>

#ifdef USE_LIBDATACHANNEL
#include "rtc/rtc.hpp"
#endif

// 为了向后兼容，保持与WebSocket客户端相同的接口
class WebRTCClient {
public:
    using message_callback_t = std::function<void(const std::string& payload, bool is_binary)>;
    using close_callback_t = std::function<void()>;
    using open_callback_t = std::function<void()>;

    /**
     * 构造函数
     * @param address 服务器地址
     * @param port 服务器端口
     * @param token 认证Token
     * @param deviceId 设备ID
     */
    WebRTCClient(const std::string& address, int port, 
                 const std::string& token, const std::string& deviceId);
    ~WebRTCClient();

    /**
     * 连接到WebRTC服务器
     * 执行信令交换(SDP Offer/Answer)并建立DataChannel连接
     */
    void Connect();

    /**
     * 关闭连接
     */
    void Close();

    /**
     * 发送文本消息 (通过text DataChannel)
     * @param message JSON格式的文本消息
     */
    void SendText(const std::string& message);

    /**
     * 发送二进制数据 (通过audio DataChannel)
     * @param data 二进制数据指针
     * @param size 数据大小
     */
    void SendBinary(const uint8_t* data, size_t size);

    /**
     * 设置消息接收回调
     * @param callback 回调函数，参数为(消息内容, 是否为二进制)
     */
    void SetMessageCallback(message_callback_t callback);

    /**
     * 设置连接关闭回调
     */
    void SetCloseCallback(close_callback_t callback);

    /**
     * 设置连接打开回调
     */
    void SetOpenCallback(open_callback_t callback);

    /**
     * 检查是否已连接
     */
    bool IsConnected() const;

private:
    // 服务器信息
    std::string signaling_url_;
    std::string server_address_;
    int server_port_;
    std::string token_;
    std::string device_id_;
    
    // 连接状态
    std::atomic<bool> is_connected_;
    std::atomic<bool> should_stop_;
    
    // 回调函数
    message_callback_t on_message_;
    close_callback_t on_close_;
    open_callback_t on_open_;
    
    // 线程安全
    std::mutex callback_mutex_;
    
#ifdef USE_LIBDATACHANNEL
    // libdatachannel 实现
    std::shared_ptr<rtc::PeerConnection> pc_;
    std::shared_ptr<rtc::DataChannel> dc_audio_;
    std::shared_ptr<rtc::DataChannel> dc_text_;
#endif

    /**
     * 执行HTTP POST请求进行信令交换
     * @param url 信令服务器URL
     * @param body POST数据
     * @return 服务器响应
     */
    std::string HttpPost(const std::string& url, const std::string& body);

    /**
     * 处理DataChannel消息
     */
    void HandleDataChannelMessage(const std::string& message, bool is_binary);

    /**
     * 连接状态变化处理
     */
    void OnConnectionStateChange(const std::string& state);
};

#endif // WEBRTC_CLIENT_H
