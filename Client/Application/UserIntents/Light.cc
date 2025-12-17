// Light.cc
#include "Light.h"
#include <iostream>
#include "../../third_party/Utils/user_log.h"
#include "../../Hardware/led.h"
#include <string>
#include <algorithm>
#ifdef __arm__
#include <json/json.h>
#else
#include <jsoncpp/json/json.h>
#endif

/*
当用户发出 “开启照明” 的指令时：
语音识别模块解析出意图为 light_control，参数为 state = on / off；
系统通过 IntentHandler 查找 robot_move 对应的处理函数（即 RobotMove::Move）；
调用该函数并传入参数，执行机器人移动逻辑；
其中，“robot_move 需要哪些参数” 的规则，正是由 GenerateRegisterMessage 提供的元信息定义的。
*/

namespace LightControl {
    void Control(const Json::Value& arguments){
        std::string state = "off"; // on / off

        if (arguments.isMember("direction") && arguments["direction"].isString()) {
            state = arguments["direction"].asString();
        }
    }
}