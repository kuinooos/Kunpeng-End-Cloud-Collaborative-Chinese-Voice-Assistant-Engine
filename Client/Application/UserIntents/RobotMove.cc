// RobotMove.cc
#include "RobotMove.h"
#include <iostream>
#include "../../third_party/Utils/user_log.h"
#include "../../Hardware/motor.h"
#include <string>
#include <algorithm>


/*
当用户发出 “让机器人向前以 2 的速度移动 5（step*5） 秒” 的指令时：
语音识别模块解析出意图为 robot_move，参数为 direction="forward", speed=50, duration=2；
系统通过 IntentHandler 查找 robot_move 对应的处理函数（即 RobotMove::Move）；
调用该函数并传入参数，执行机器人移动逻辑；
其中，“robot_move 需要哪些参数” 的规则，正是由 GenerateRegisterMessage 提供的元信息定义的。
*/

// 简单工具：从 Json::Value 解析为 int / double（兼容字符串数字）
namespace {
    static inline void trim_inplace(std::string &s) {
        auto not_space = [](int ch){ return ch != ' ' && ch != '\t' && ch != '\n' && ch != '\r'; };
        s.erase(s.begin(), std::find_if(s.begin(), s.end(), not_space));
        s.erase(std::find_if(s.rbegin(), s.rend(), not_space).base(), s.end());
    }

    static bool parse_int_from_json(const Json::Value &v, int &out) {
        if (v.isInt()) { out = v.asInt(); return true; }
        if (v.isUInt()) { out = static_cast<int>(v.asUInt()); return true; }
        if (v.isDouble()) { out = static_cast<int>(v.asDouble()); return true; }
        if (v.isString()) {
            std::string s = v.asString();
            trim_inplace(s);
            if (s.empty()) return false;
            try {
                size_t idx = 0;
                double d = std::stod(s, &idx);
                if (idx == s.size()) { out = static_cast<int>(d); return true; }
            } catch (...) { return false; }
        }
        return false;
    }

    static bool parse_double_from_json(const Json::Value &v, double &out) {
        if (v.isDouble()) { out = v.asDouble(); return true; }
        if (v.isInt() || v.isUInt()) { out = v.asDouble(); return true; }
        if (v.isString()) {
            std::string s = v.asString();
            trim_inplace(s);
            if (s.empty()) return false;
            try {
                size_t idx = 0;
                double d = std::stod(s, &idx);
                if (idx == s.size()) { out = d; return true; }
            } catch (...) { return false; }
        }
        return false;
    }
}

namespace RobotMove {
    void Move(const Json::Value& arguments) {
        // 解析参数
        std::string direction = "forward";
        int speed = 2;          // 1-10
        int steps = 512;        // 512 一圈
        double duration = 0.0;  // 可选：秒

        if (arguments.isMember("direction") && arguments["direction"].isString()) {
            direction = arguments["direction"].asString();
        }
        if (arguments.isMember("speed")) {
            int tmp = speed;
            if (parse_int_from_json(arguments["speed"], tmp)) {
                speed = tmp;
            }
        }
        if (arguments.isMember("steps")) {
            int tmp = steps;
            if (parse_int_from_json(arguments["steps"], tmp)) {
                steps = tmp;
            }
        }
        // 兼容单数写法: step
        if (arguments.isMember("step")) {
            int tmp = steps;
            if (parse_int_from_json(arguments["step"], tmp)) {
                steps = tmp;
            }
        }
        if (arguments.isMember("duration")) {
            double tmp = duration;
            if (parse_double_from_json(arguments["duration"], tmp)) {
                duration = tmp;
            }
        }

        // 如果给了 duration 但没给 steps，则做一个简单估算：按一圈/秒为基准
        if (duration > 0.0 && (!arguments.isMember("steps") || steps <= 0)) {
            // 简单按 duration 秒 ≈ duration 圈 → steps = duration * 512
            steps = static_cast<int>(duration * 512);
            if (steps <= 0) steps = 512;
        }

        // 规范化参数
        if (speed < 1) speed = 1;
        if (speed > 10) speed = 10;
        if (steps <= 0) steps = 512;

        USER_LOG_INFO("RobotMove::Move dir=%s speed=%d steps=%d duration=%.2f",
                      direction.c_str(), speed, steps, duration);
        // 仅在 ARM 设备上实际控制电机；在 PC/x86 环境仅打印日志，避免访问 /sys/class/gpio 失败
    #if defined(__arm__) || defined(__aarch64__)
        // 创建/复用单例电机对象
        if (MOTOR::g_motor == nullptr) {
            MOTOR::g_motor = new MOTOR();
        }

        MOTOR::g_motor->setSpeed(speed);

        if (direction == "forward") {
            MOTOR::g_motor->motorForward(steps);
        } else if (direction == "backward" || direction == "reverse") {
            MOTOR::g_motor->motorReverse(steps);
        } else {
            USER_LOG_WARN("Unknown direction: %s, default to forward", direction.c_str());
            MOTOR::g_motor->motorForward(steps);
        }

        MOTOR::g_motor->motorStop();
    #else
        USER_LOG_WARN("RobotMove: Motor control is disabled on non-ARM builds (no GPIO). This is expected on PC dev.");
        (void)direction; (void)speed; (void)steps; (void)duration;
        #endif
    }
}