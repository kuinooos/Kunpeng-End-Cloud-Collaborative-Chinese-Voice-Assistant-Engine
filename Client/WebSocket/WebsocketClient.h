// SPDX-License-Identifier: MulanPSL-2.0
// 鲲鹏端云协同中文语音助手引擎 - WebSocket 客户端头文件
// 说明：提供基于 websocketpp 的文本/二进制发送与连接管理接口
// 约定：保持最小职责（连接、收发、回调绑定），协议处理交由 WSHandler
#ifndef WEBSOCKETCLIENT_H
#define WEBSOCKETCLIENT_H

#include <websocketpp/client.hpp>
#include <websocketpp/config/asio_no_tls_client.hpp>
#include <string>
#include <functional>
#include <map>
#include <iostream>
#include <thread>
#include <memory>

/**
 * 二进制音频帧协议
 * header: version(2) + type(2) + payload_size(4) + payload(N)
 */
struct BinProtocol {
    uint16_t version;
    uint16_t type;
    uint32_t payload_size;
    uint8_t payload[];
} __attribute__((packed));

struct BinProtocolInfo {
    uint16_t version;
    uint16_t type;
};

/**
 * WebSocketClient
 * 职责：管理 WS 连接与消息收发；不处理业务协议解析
 */
class WebSocketClient {
public:
    using message_callback_t = std::function<void(const std::string&, bool)>;
    using close_callback_t = std::function<void()>;

    WebSocketClient(const std::string& address, int port, const std::string& token, const std::string& deviceId, int protocolVersion);
    ~WebSocketClient();

    /// 启动网络事件循环线程
    void Run();

    /// 建立连接（需先调用 Run）
    void Connect();

    /// 主动断开连接
    void Close();

    /// 停止网络事件循环
    void Terminate();

    /// 发送文本消息
    void SendText(const std::string& message);

    /// 发送二进制数据
    void SendBinary(const uint8_t* data, size_t size);
    
    /// 绑定消息回调（payload, is_binary）
    void SetMessageCallback(message_callback_t callback);

    /// 绑定关闭回调
    void SetCloseCallback(close_callback_t callback);    

    /// 当前是否已建立连接
    bool IsConnected() const { return is_connected_; }

private:
    using client_t = websocketpp::client<websocketpp::config::asio_client>;
    client_t ws_client_;
    websocketpp::lib::shared_ptr<websocketpp::lib::thread> thread_;
    websocketpp::connection_hdl connection_hdl_;
    std::map<std::string, std::string> headers_;
    message_callback_t on_message_;
    close_callback_t on_close_;
    std::string uri_;
    bool is_connected_ = false;

    void on_open(websocketpp::connection_hdl hdl);
    void on_message(websocketpp::connection_hdl hdl, client_t::message_ptr msg);
    void on_close(websocketpp::connection_hdl hdl); 
};

#endif // WEBSOCKETCLIENT_H
