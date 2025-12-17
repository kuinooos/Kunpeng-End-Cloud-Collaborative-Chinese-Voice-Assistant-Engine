// SPDX-License-Identifier: MulanPSL-2.0
#include "Listening.h"
#include "../../Utils/user_log.h"
#include "../../Events/AppEvents.h"
#include "../../Utils/affinity.h"
#include <cstdlib>

// 静态成员变量定义
std::atomic<bool> ListeningState::state_running_{false};
std::thread ListeningState::state_running_thread_;

// 端侧动作：
// 状态机切换到 ListeningState。
// 发送 State 消息：立即发送 {"type": "state", "state": "listening"}。

// 云侧动作：
// 收到 listening 状态。
// 重置 VAD/ASR：准备迎接新的语音流。
// 预热 TTS：建立流式连接。
void ListeningState::Enter(Application* app) {
    app->oled_controller_.StartAnimation(OledController::LISTENING);
    std::string json_message = R"({"type": "state", "state": "listening"})";
    app->ws_client_.SendText(json_message);
    app->set_first_audio_msg_received(true);
    app->audio_processor_.startRecording();
    std::this_thread::sleep_for(std::chrono::milliseconds(500));
    app->audio_processor_.clearRecordedAudioQueue();
    state_running_.store(true);
    state_running_thread_ = std::thread([app]() { Run(app); });
    USER_LOG_INFO("Into listening state.");
}

void ListeningState::Run(Application* app) {
    const char* audio_set = std::getenv("AICHAT_AUDIO_CORES");
    if (audio_set && *audio_set) {
        set_current_thread_affinity(audio_set);
    } else {
        set_current_thread_affinity("1");
    }
    while (state_running_.load() == true) {
        std::vector<int16_t> audio_frame;
        if(app->audio_processor_.recordedQueueIsEmpty() == false) {
            if(app->audio_processor_.getRecordedAudio(audio_frame)) {
                uint8_t opus_data[1536];
                size_t opus_data_size;
                if (app->audio_processor_.encode(audio_frame, opus_data, opus_data_size)) {
                    BinProtocol* packed_frame = app->audio_processor_.PackBinFrame(opus_data, opus_data_size, app->get_ws_protocolVersion());
                    if (packed_frame) {
                        app->ws_client_.SendBinary(reinterpret_cast<uint8_t*>(packed_frame), sizeof(BinProtocol) + opus_data_size);
                    } else {
                        USER_LOG_WARN("Audio Packing failed");
                    }
                } else {
                    USER_LOG_WARN("Audio Encoding failed");
                }
            }
        }
    }
}

void ListeningState::Exit(Application* app) {
    app->audio_processor_.stopRecording();
    state_running_.store(false);
    state_running_thread_.join();
    USER_LOG_INFO("Listening exit.");
}
