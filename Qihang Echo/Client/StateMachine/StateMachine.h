#ifndef STATE_MACHINE_H_
#define STATE_MACHINE_H_

#include <functional>
#include <unordered_map>
#include <string>

using EnterFunc_t = std::function<void()>;
using ExitFunc_t = std::function<void()>;

// StateMachine class declaration
class StateMachine {
public:
    StateMachine(int initialState);
    ~StateMachine();

    /**
     * @brief 初始化状态机。
     * 
     */
    void Initialize();

    /**
     * @brief 注册状态。
     * 
     * @param state 状态
     * @param on_enter 进入状态时的回调函数
     * @param on_exit 退出状态时的回调函数
     */
    void RegisterState(int state, EnterFunc_t on_enter, ExitFunc_t on_exit);

    /**
     * @brief 注册状态转换。
     * 
     * @param from 起始状态，-1表示任意状态
     * @param event 事件
     * @param to 目标状态
     */
    void RegisterTransition(int from, int event, int to);

    /**
     * @brief 处理事件。
     * 
     * @param event 事件
     * @return true 处理成功
     * @return false 处理失败
     */
    bool HandleEvent(int event);

    /**
     * @brief 获取当前状态。
     * 
     * @return int 当前状态
     */
    int GetCurrentState() const;

private:
    void ChangeState(int newState);
    
    /*记录当前处于哪个状态（比如 1 代表 Idle，2 代表 Listening）。*/
    int currentState_;

    /*作用：查表。
    当进入状态 X 时，查这个表执行 X 的 Enter 函数；离开时执行 X 的 Exit 函数*/
    std::unordered_map<int, std::pair<EnterFunc_t, ExitFunc_t>> stateActions_;

    /*导航图。比如 transitions_[1][100] = 2 意味着“在状态 1 时，
    如果发生事件 100，就跳到状态 2”。*/
    std::unordered_map<int, std::unordered_map<int, int>> transitions_;
};

#endif  // STATE_MACHINE_H_