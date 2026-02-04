#ifndef OLED_CONTROLLER_H
#define OLED_CONTROLLER_H

#include <thread>
#include <atomic>
#include <mutex>
#include "oled_driver.h"

class OledController {
public:
    enum AnimationType {
        NONE,
        IDLE,
        LISTENING,
        THINKING,
        SPEAKING,
        SMILE
    };

    OledController();
    ~OledController();

    void Init();
    void StartAnimation(AnimationType type);
    void StopAnimation();

private:
    void ThreadLoop();
    void DrawIdle(int frame);
    void DrawListening(int frame);
    void DrawThinking(int frame);
    void DrawSpeaking(int frame);
    void DrawSmile(int frame);

    std::thread thread_;
    std::atomic<bool> running_;
    std::atomic<AnimationType> current_anim_;
    std::mutex mutex_;
};

#endif // OLED_CONTROLLER_H
