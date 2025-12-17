#include "WebRTCClient.h"
#include "../Utils/user_log.h"
#include <iostream>
#include <sstream>
#include <cstring>
#include <curl/curl.h>
#include <json/json.h>

// 注意：这是一个框架实现，需要libdatachannel库才能完整工作
// 编译时需要链接: -ldatachannel -lpthread -lcurl

WebRTCClient::WebRTCClient(const std::string& address, int port, 
                           const std::string& token, const std::string& deviceId)
    : server_address_(address)
    , server_port_(port)
    , token_(token)
    , device_id_(deviceId)
    , is_connected_(false)
    , should_stop_(false) {
    
    signaling_url_ = "http://" + address + ":" + std::to_string(port) + "/offer";
    USER_LOG_INFO("WebRTC Client initialized. Signaling URL: %s", signaling_url_.c_str());
    
#ifdef USE_LIBDATACHANNEL
    // 初始化libdatachannel日志
    // rtc::InitLogger(rtc::LogLevel::Warning);
#else
    USER_LOG_WARN("WebRTC Client: libdatachannel not enabled. This is a stub implementation.");
    USER_LOG_WARN("To use WebRTC, please:");
    USER_LOG_WARN("  1. Install libdatachannel");
    USER_LOG_WARN("  2. Add -DUSE_LIBDATACHANNEL to compile flags");
    USER_LOG_WARN("  3. Link with -ldatachannel");
#endif
}

WebRTCClient::~WebRTCClient() {
    Close();
}

void WebRTCClient::Connect() {
#ifdef USE_LIBDATACHANNEL
    try {
        USER_LOG_INFO("Starting WebRTC connection...");
        
        // 配置PeerConnection
        rtc::Configuration config;
        // 局域网环境可以不配置STUN服务器
        // 如果需要穿透NAT，取消注释下面的行
        // config.iceServers.emplace_back("stun:stun.l.google.com:19302");
        
        pc_ = std::make_shared<rtc::PeerConnection>(config);
        
        // 设置 ICE Gathering 状态回调
        pc_->onGatheringStateChange([this](rtc::PeerConnection::GatheringState state) {
            std::string state_str;
            switch(state) {
                case rtc::PeerConnection::GatheringState::New: state_str = "New"; break;
                case rtc::PeerConnection::GatheringState::InProgress: state_str = "InProgress"; break;
                case rtc::PeerConnection::GatheringState::Complete: 
                    state_str = "Complete";
                    // ICE gathering 完成，现在可以获取并发送 Local SDP
                    if (auto desc = pc_->localDescription()) {
                        USER_LOG_INFO("Local SDP generated, sending offer to signaling server...");
                        
                        // 使用 jsoncpp 构建 JSON（自动处理转义）
                        Json::Value offer;
                        offer["sdp"] = std::string(*desc);
                        offer["type"] = desc->typeString();
                        
                        Json::StreamWriterBuilder writer;
                        writer["indentation"] = "";  // 紧凑格式
                        std::string offer_json = Json::writeString(writer, offer);
                        
                        try {
                            // 发送HTTP POST到信令服务器
                            std::string response = HttpPost(signaling_url_, offer_json);
                            
                            // 使用 jsoncpp 解析 Answer
                            Json::CharReaderBuilder reader;
                            Json::Value answer_json;
                            std::string errs;
                            std::istringstream iss(response);
                            
                            if (Json::parseFromStream(reader, iss, &answer_json, &errs)) {
                                if (answer_json.isMember("sdp") && answer_json.isMember("type")) {
                                    std::string sdp = answer_json["sdp"].asString();
                                    std::string type = answer_json["type"].asString();
                                    
                                    // 创建Answer Description
                                    rtc::Description answer(sdp, type);
                                    pc_->setRemoteDescription(answer);
                                    
                                    USER_LOG_INFO("Remote SDP set successfully");
                                } else {
                                    USER_LOG_ERROR("Server response missing sdp or type field");
                                }
                            } else {
                                USER_LOG_ERROR("Failed to parse JSON response: %s", errs.c_str());
                            }
                        } catch (const std::exception& e) {
                            USER_LOG_ERROR("Failed to exchange signaling: %s", e.what());
                        }
                    }
                    break;
            }
            USER_LOG_INFO("ICE Gathering State: %s", state_str.c_str());
        });
        
        // 设置连接状态变化回调
        pc_->onStateChange([this](rtc::PeerConnection::State state) {
            std::string state_str;
            switch(state) {
                case rtc::PeerConnection::State::New: state_str = "New"; break;
                case rtc::PeerConnection::State::Connecting: state_str = "Connecting"; break;
                case rtc::PeerConnection::State::Connected: 
                    state_str = "Connected";
                    is_connected_ = true;
                    if (on_open_) {
                        on_open_();
                    }
                    break;
                case rtc::PeerConnection::State::Disconnected: state_str = "Disconnected"; break;
                case rtc::PeerConnection::State::Failed: state_str = "Failed"; break;
                case rtc::PeerConnection::State::Closed: 
                    state_str = "Closed";
                    is_connected_ = false;
                    if (on_close_) {
                        on_close_();
                    }
                    break;
            }
            USER_LOG_INFO("WebRTC State: %s", state_str.c_str());
            OnConnectionStateChange(state_str);
        });
        
        // 创建 "text" DataChannel (可靠传输，用于控制消息)
        dc_text_ = pc_->createDataChannel("text");
        
        dc_text_->onOpen([this]() {
            USER_LOG_INFO("Text DataChannel opened");
        });
        
        dc_text_->onClosed([this]() {
            USER_LOG_INFO("Text DataChannel closed");
        });
        
        dc_text_->onMessage([this](auto data) {
            if (std::holds_alternative<std::string>(data)) {
                std::string message = std::get<std::string>(data);
                HandleDataChannelMessage(message, false);
            } else if (std::holds_alternative<rtc::binary>(data)) {
                auto& bin = std::get<rtc::binary>(data);
                std::string message(reinterpret_cast<const char*>(bin.data()), bin.size());
                HandleDataChannelMessage(message, false);
            }
        });
        
        // 创建 "audio" DataChannel (不可靠模式，UDP特性)
        rtc::DataChannelInit audio_config;
        audio_config.reliability.unordered = true;     // 允许乱序
        audio_config.reliability.maxRetransmits = 0;  // 零重传，丢包直接丢弃 (UDP特性)
        
        dc_audio_ = pc_->createDataChannel("audio", audio_config);
        
        dc_audio_->onOpen([this]() {
            USER_LOG_INFO("Audio DataChannel opened (Unreliable mode, 0 retransmits)");
        });
        
        dc_audio_->onClosed([this]() {
            USER_LOG_INFO("Audio DataChannel closed");
        });
        
        dc_audio_->onMessage([this](auto data) {
            if (std::holds_alternative<rtc::binary>(data)) {
                auto& bin = std::get<rtc::binary>(data);
                std::string message(reinterpret_cast<const char*>(bin.data()), bin.size());
                HandleDataChannelMessage(message, true);
            } else if (std::holds_alternative<std::string>(data)) {
                std::string message = std::get<std::string>(data);
                HandleDataChannelMessage(message, true);
            }
        });
        
        // 触发 SDP 生成和 ICE gathering
        pc_->setLocalDescription();
        
    } catch (const std::exception& e) {
        USER_LOG_ERROR("WebRTC connection failed: %s", e.what());
        is_connected_ = false;
    }
#else
    USER_LOG_ERROR("WebRTC not supported in this build. Please rebuild with libdatachannel.");
#endif
}

void WebRTCClient::Close() {
    should_stop_ = true;
    is_connected_ = false;
    
#ifdef USE_LIBDATACHANNEL
    if (dc_audio_) {
        dc_audio_->close();
        dc_audio_.reset();
    }
    if (dc_text_) {
        dc_text_->close();
        dc_text_.reset();
    }
    if (pc_) {
        pc_->close();
        pc_.reset();
    }
#endif
    
    USER_LOG_INFO("WebRTC connection closed");
}

void WebRTCClient::SendText(const std::string& message) {
#ifdef USE_LIBDATACHANNEL
    if (dc_text_ && dc_text_->isOpen()) {
        try {
            dc_text_->send(message);
        } catch (const std::exception& e) {
            USER_LOG_ERROR("Failed to send text message: %s", e.what());
        }
    } else {
        USER_LOG_WARN("Text DataChannel not open, message not sent");
    }
#else
    USER_LOG_WARN("WebRTC not available, cannot send text");
#endif
}

void WebRTCClient::SendBinary(const uint8_t* data, size_t size) {
#ifdef USE_LIBDATACHANNEL
    if (dc_audio_ && dc_audio_->isOpen()) {
        try {
            // 发送原始二进制数据
            dc_audio_->send(reinterpret_cast<const std::byte*>(data), size);
        } catch (const std::exception& e) {
            USER_LOG_ERROR("Failed to send binary data: %s", e.what());
        }
    } else {
        USER_LOG_WARN("Audio DataChannel not open, data not sent");
    }
#else
    USER_LOG_WARN("WebRTC not available, cannot send binary");
#endif
}

void WebRTCClient::SetMessageCallback(message_callback_t callback) {
    std::lock_guard<std::mutex> lock(callback_mutex_);
    on_message_ = callback;
}

void WebRTCClient::SetCloseCallback(close_callback_t callback) {
    std::lock_guard<std::mutex> lock(callback_mutex_);
    on_close_ = callback;
}

void WebRTCClient::SetOpenCallback(open_callback_t callback) {
    std::lock_guard<std::mutex> lock(callback_mutex_);
    on_open_ = callback;
}

bool WebRTCClient::IsConnected() const {
    return is_connected_.load();
}

// libcurl 回调函数
static size_t WriteCallback(void* contents, size_t size, size_t nmemb, void* userp) {
    ((std::string*)userp)->append((char*)contents, size * nmemb);
    return size * nmemb;
}

std::string WebRTCClient::HttpPost(const std::string& url, const std::string& body) {
    CURL* curl = curl_easy_init();
    if (!curl) {
        USER_LOG_ERROR("Failed to initialize CURL");
        return "";
    }
    
    std::string response;
    struct curl_slist* headers = NULL;
    headers = curl_slist_append(headers, "Content-Type: application/json");
    
    curl_easy_setopt(curl, CURLOPT_URL, url.c_str());
    curl_easy_setopt(curl, CURLOPT_POSTFIELDS, body.c_str());
    curl_easy_setopt(curl, CURLOPT_HTTPHEADER, headers);
    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, WriteCallback);
    curl_easy_setopt(curl, CURLOPT_WRITEDATA, &response);
    curl_easy_setopt(curl, CURLOPT_TIMEOUT, 10L);
    
    USER_LOG_INFO("Sending HTTP POST to: %s", url.c_str());
    
    CURLcode res = curl_easy_perform(curl);
    if (res != CURLE_OK) {
        USER_LOG_ERROR("HTTP POST failed: %s", curl_easy_strerror(res));
    } else {
        long http_code = 0;
        curl_easy_getinfo(curl, CURLINFO_RESPONSE_CODE, &http_code);
        USER_LOG_INFO("HTTP response code: %ld", http_code);
    }
    
    curl_slist_free_all(headers);
    curl_easy_cleanup(curl);
    
    return response;
}

void WebRTCClient::HandleDataChannelMessage(const std::string& message, bool is_binary) {
    std::lock_guard<std::mutex> lock(callback_mutex_);
    if (on_message_) {
        on_message_(message, is_binary);
    }
}

void WebRTCClient::OnConnectionStateChange(const std::string& state) {
    if (state == "Connected") {
        USER_LOG_INFO("✅ WebRTC connection established successfully");
    } else if (state == "Failed" || state == "Closed") {
        USER_LOG_WARN("❌ WebRTC connection lost: %s", state.c_str());
    }
}
