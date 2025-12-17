#include "Speaking.h"
#include "../../Utils/user_log.h"
#include "../../Events/AppEvents.h"
#include "../../Utils/affinity.h"
#include "../../third_party/snowboy/include/snowboy-detect-c-wrapper.h"
#include <cstdlib>

// 静态成员变量定义
std::atomic<bool> SpeakingState::state_running_{false};
std::thread SpeakingState::state_running_thread_;

void SpeakingState::Enter(Application* app) {
    app->oled_controller_.StartAnimation(OledController::SPEAKING);
    std::string json_message = R"({"type": "state", "state": "speaking"})";
    app->ws_client_.SendText(json_message);
    
    // start播放
    app->audio_processor_.startPlaying();
    
    // 开启录音 (支持打断/Barge-in)
    app->audio_processor_.clearRecordedAudioQueue();
    app->audio_processor_.startRecording();

    // running
    state_running_.store(true);
    state_running_thread_ = std::thread([app]() { Run(app); });
    USER_LOG_INFO("Into speaking state.");
}

void SpeakingState::Run(Application* app) {
    // 监控/任务线程亲和
    const char* task_set = std::getenv("AICHAT_TASK_CORES");
    if (task_set && *task_set) {
        set_current_thread_affinity(task_set);
    } else {
        set_current_thread_affinity("2-3");
    }
    USER_LOG_INFO("Speaking state run.");

    // 初始化 Snowboy 用于打断检测
    SnowboyDetect* detector = SnowboyDetectConstructor("third_party/snowboy/resources/common.res",
                                                     "third_party/snowboy/resources/models/echo.pmdl");
    SnowboyDetectSetSensitivity(detector, "0.5");
    SnowboyDetectSetAudioGain(detector, 1);
    SnowboyDetectApplyFrontend(detector, false);
    std::vector<int16_t> data;

    while(state_running_.load() == true) {
        // 1. 检测唤醒词 (打断)
        bool audio_processed = false;
        if(app->audio_processor_.recordedQueueIsEmpty() == false) {
            app->audio_processor_.getRecordedAudio(data);
            int result = SnowboyDetectRunDetection(detector, data.data(), data.size(), false);
            if (result > 0) {
                USER_LOG_INFO("Barge-in (Wake) detected! Interrupting speech.");
                
                // 立即停止播放
                app->audio_processor_.clearPlaybackAudioQueue();
                
                // 触发结束事件，转入 Listening 状态
                app->eventQueue_.Enqueue(static_cast<int>(AppEvent::speaking_end));
                
                // 重置标志位
                app->set_tts_completed(false);
                app->set_dialogue_completed(false);
                break;
            }
            audio_processed = true;
        }

        // 2. 检查 TTS 是否播放完成 (正常结束)
        if(app->get_tts_completed() && app->audio_processor_.playbackQueueIsEmpty()) {
            // 给一点缓冲时间让最后的声音播完
            std::this_thread::sleep_for(std::chrono::milliseconds(200));
            
            USER_LOG_INFO("Speaking end.");
            if(app->get_dialogue_completed() == false) {
                app->eventQueue_.Enqueue(static_cast<int>(AppEvent::speaking_end));
            } else {
                app->eventQueue_.Enqueue(static_cast<int>(AppEvent::dialogue_end));
            }
            app->set_tts_completed(false);
            app->set_dialogue_completed(false);
            break;
        }

        // 3. 避免忙轮询
        if (!audio_processed) {
            std::this_thread::sleep_for(std::chrono::milliseconds(10));
        }
    }
    
    SnowboyDetectDestructor(detector);
}

void SpeakingState::Exit(Application* app) {
    // stop录音
    app->audio_processor_.stopRecording();

    // clear playback audio queue
    app->audio_processor_.clearPlaybackAudioQueue();
    // stop播放
    app->audio_processor_.stopPlaying();
    // stop state running
    state_running_.store(false);
    state_running_thread_.join();
    USER_LOG_INFO("Speaking exit.");
}
