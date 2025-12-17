#ifndef WS_HANDLER_H
#define WS_HANDLER_H

#include <string>
#include "Application.h"
#if defined(__arm__) || defined(__aarch64__)
#include <json/json.h>
#else
#include <jsoncpp/json/json.h>
#endif

/*
Application/WS_Handler.h/.cc：服务端发来的 JSON/二进制消息处理；
驱动状态事件；把音频二进制解码入播放队列
*/

class WSHandler {
public:
    // 处理 WebSocket 接收到的消息
    void ws_msg_handle(const std::string& message, bool is_binary, Application* app);
private:
    void handle_vad_message(const Json::Value& root, Application* app);
    void handle_asr_message(const Json::Value& root, Application* app);
    void handle_chat_message(const Json::Value& root, Application* app);
    void handle_tts_message(const Json::Value& root, Application* app);
    void handle_intent_message(const Json::Value& root);
};

#endif // WS_HANDLER_H