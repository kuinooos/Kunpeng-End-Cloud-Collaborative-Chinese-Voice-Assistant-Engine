#ifndef STATE_CONFIG_H
#define STATE_CONFIG_H

#include "../StateMachine/StateMachine.h"
#include "Application.h"

enum class AppState {
    fault,
    startup,//联网、鉴权、注册技能
    stopping,
    idle,//没事干，监听麦克风看有没有人叫唤提醒词（hi，鲲鹏）
    listening,//正在录音，把声音发给服务器
    thinking,//录音发完了，等服务器返回结果
    speaking,//正在播放服务器返回的语音
};

class StateConfig {
public:
    /*
        * @brief Configure the state machine with states and transitions.
        * 
        * @param state_machine The state machine to configure.
        * @param app Pointer to the Application instance.
        * 
        * This function sets up the state machine by registering states and their corresponding
        * entry and exit actions, as well as defining the transitions between states based on events.
    */
    static void Configure(StateMachine& state_machine, Application* app);
};

#endif // STATE_CONFIG_H