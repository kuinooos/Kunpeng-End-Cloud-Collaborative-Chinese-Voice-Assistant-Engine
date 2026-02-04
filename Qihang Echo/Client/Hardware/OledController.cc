#include "OledController.h"
#include <iostream>
#include <cmath>
#include <chrono>
#include <cstdlib>
// Force sync 20251216

// OledController implementation

OledController::OledController() : running_(false), current_anim_(NONE) {}

OledController::~OledController() {
    StopAnimation();
}

void OledController::Init() {
    OledDriver::GetInstance().Init();
}

void OledController::StartAnimation(AnimationType type) {
    std::lock_guard<std::mutex> lock(mutex_);
    current_anim_ = type;
    if (!running_) {
        running_ = true;
        thread_ = std::thread(&OledController::ThreadLoop, this);
    }
}

void OledController::StopAnimation() {
    {
        std::lock_guard<std::mutex> lock(mutex_);
        running_ = false;
    }
    if (thread_.joinable()) {
        thread_.join();
    }
    OledDriver::GetInstance().Clear();
    OledDriver::GetInstance().Refresh();
}

void OledController::ThreadLoop() {
    int frame = 0;
    while (running_) {
        OledDriver::GetInstance().Clear();
        
        AnimationType type = current_anim_.load();
        switch (type) {
            case IDLE:
                DrawIdle(frame);
                break;
            case LISTENING:
                DrawListening(frame);
                break;
            case THINKING:
                DrawThinking(frame);
                break;
            case SPEAKING:
                DrawSpeaking(frame);
                break;
            case SMILE:
                DrawSmile(frame);
                break;
            default:
                break;
        }
        
        OledDriver::GetInstance().Refresh();
        frame++;
        std::this_thread::sleep_for(std::chrono::milliseconds(30));
    }
}

// ================== Animations ==================

void OledController::DrawIdle(int frame) {
    OledDriver& oled = OledDriver::GetInstance();
    
    // 1. 显示大号文字 (右侧)
    oled.DrawString16x16(64, 12, "Hi,");
    
    // 换回小字体显示名字
    const char *name = "I'm Kunpeng";
    int nx = 40, ny = 40;
    oled.DrawString8x8(nx, ny, name);

    // 2. 呼吸机器人 (左侧)
    float breath_val = sin(frame * 0.1); 
    int body_offset_y = (int)(breath_val * 1.5); 
    int rx = 4, ry = 35 + body_offset_y; 

    // 身体
    oled.DrawRoundRect(rx, ry, 32, 22, 5, 1);
    oled.DrawRoundRect(rx+4, ry+4, 24, 14, 3, 0); // 屏幕镂空

    // 眼睛 (眨眼动画)
    int eye_y = ry + 11;
    if (frame % 50 > 45) { // 闭眼
        oled.DrawLine(rx+8, eye_y, rx+12, eye_y, 1);
        oled.DrawLine(rx+18, eye_y, rx+22, eye_y, 1);
    } else { // 睁眼 (圆点)
        oled.DrawFillCircle(rx+10, eye_y, 2, 1);
        oled.DrawFillCircle(rx+20, eye_y, 2, 1);
    }
    
    // 天线
    oled.DrawLine(rx+16, ry, rx+16, ry-5, 1);
    oled.DrawFillCircle(rx+16, ry-6, 1, 1);

    // Zzz... (呼噜)
    int z_start_x = rx + 24;
    int z_start_y = ry - 8;
    int step = (frame / 10) % 3;
    if(step >= 0) { oled.DrawChar8x8(z_start_x, z_start_y, '.'); }
    if(step >= 1) { oled.DrawChar8x8(z_start_x+6, z_start_y-6, 'z'); }
    if(step >= 2) { oled.DrawChar8x8(z_start_x+12, z_start_y-12, 'Z'); }
}

void OledController::DrawListening(int frame) {
    OledDriver& oled = OledDriver::GetInstance();
    int cx = 64, cy = 32;
    int r = 20;

    // 1. 脸轮廓
    oled.DrawCircle(cx, cy, r, 1);

    // 2. 眼睛 (向右看，盯着声音来源)
    int eye_l_x = cx - 10, eye_r_x = cx + 10;
    int eye_y = cy - 5;
    oled.DrawCircle(eye_l_x, eye_y, 5, 1);
    oled.DrawCircle(eye_r_x, eye_y, 5, 1);
    // 眼珠强烈向右
    oled.DrawFillCircle(eye_l_x + 2, eye_y, 2, 1);
    oled.DrawFillCircle(eye_r_x + 2, eye_y, 2, 1);

    // 3. 嘴巴 (微张，表示专注)
    oled.DrawCircle(cx, cy + 12, 3, 1); 
    oled.DrawFillCircle(cx, cy + 12, 1, 0); // 镂空中间

    // 4. 夸张的右耳 (关键点！)
    int ear_x = cx + 24;
    int ear_y = cy;
    // 画一个C形的大耳朵
    oled.DrawArc(ear_x - 5, ear_y, 10, -90, 90); 
    oled.DrawArc(ear_x - 5, ear_y, 9, -90, 90);  // 加粗

    // 5. 手掌拢耳动作 (Cupping Hand)
    int hand_x = ear_x + 5;
    int finger_w = 4;
    int finger_h = 12;
    // 食指
    oled.DrawFillCircle(hand_x, ear_y - 10, 3, 1);
    oled.DrawRect(hand_x - 2, ear_y - 10, finger_w, finger_h, 1);
    // 中指
    oled.DrawFillCircle(hand_x + 3, ear_y - 2, 3, 1);
    oled.DrawRect(hand_x + 1, ear_y - 2, finger_w, finger_h, 1);
    // 无名指
    oled.DrawFillCircle(hand_x + 2, ear_y + 8, 3, 1);
    oled.DrawRect(hand_x, ear_y + 8, finger_w, finger_h - 2, 1);

    // 6. 动态声波 (从屏幕右边缘飞入耳朵)
    int wave_center_x = ear_x + 10;
    int wave_center_y = ear_y;
    int speed_div = 3; // 动画速度
    
    for(int i=0; i<3; i++) {
        int raw_val = ((frame / speed_div) + i * 10);
        int current_r = 35 - (raw_val % 35); // 35 -> 0 收缩效果
        
        if (current_r > 5 && current_r < 35) {
            oled.DrawArc(wave_center_x, wave_center_y, current_r, -45, 45);
            oled.DrawArc(wave_center_x + 1, wave_center_y, current_r, -45, 45); // 加粗
        }
    }
}

void OledController::DrawThinking(int frame) {
    OledDriver& oled = OledDriver::GetInstance();
    int cx = 64, cy = 32;
    int r = 20;

    // 1. 脸轮廓
    oled.DrawCircle(cx, cy, r, 1);

    // 2. 眼睛 (向上看)
    int eye_lx = cx - 10, eye_rx = cx + 10, eye_y = cy - 5;
    int look_offset = 0;
    int anim_step = (frame / 5) % 4; 
    
    if (anim_step == 0) look_offset = 0;      
    else if (anim_step == 1) look_offset = -3; 
    else if (anim_step == 2) look_offset = 0;  
    else if (anim_step == 3) look_offset = 3;  

    oled.DrawCircle(eye_lx, eye_y, 4, 1);
    oled.DrawCircle(eye_rx, eye_y, 4, 1);
    oled.DrawFillCircle(eye_lx + look_offset, eye_y, 1, 1);
    oled.DrawFillCircle(eye_rx + look_offset, eye_y, 1, 1);

    // 4. 嘴巴 (抿嘴思考，直线)
    oled.DrawLine(cx - 5, cy + 12, cx + 8, cy + 12, 1);

    // 5. 手 (托着下巴)
    oled.DrawFillCircle(cx - 8, cy + 20, 3, 1);
    oled.DrawLine(cx - 8, cy + 20, cx - 8, cy + 28, 1); 
    oled.DrawFillCircle(cx - 5, cy + 15, 3, 1);
    oled.DrawFillCircle(cx + 2, cy + 16, 3, 1);
    oled.DrawFillCircle(cx, cy + 25, 6, 1);

    // 6. 思考气泡 "..." (依次出现)
    int bubble_step = (frame / 10) % 4; 
    if (bubble_step >= 1) oled.DrawFillCircle(cx + 25, cy - 20, 2, 1); 
    if (bubble_step >= 2) oled.DrawFillCircle(cx + 32, cy - 20, 2, 1); 
    if (bubble_step >= 3) oled.DrawFillCircle(cx + 39, cy - 20, 2, 1); 
}

void OledController::DrawSpeaking(int frame) {
    OledDriver& oled = OledDriver::GetInstance();
    int cx = 64, cy = 32;
    int r = 22;

    // 1. 脸轮廓
    oled.DrawCircle(cx, cy, r, 1);

    // 2. 眼睛 (弯弯的笑眼)
    int eye_lx = cx - 10, eye_rx = cx + 10, eye_y = cy - 5;
    oled.DrawArc(eye_lx, eye_y + 3, 5, 200, 340); // 上拱形
    oled.DrawArc(eye_rx, eye_y + 3, 5, 200, 340);

    // 3. 嘴巴 (动态张合)
    // 模拟音量/语速变化
    float target_mouth_h = 2 + (rand() % 12); 
    static float current_mouth_h = 2;
    int mouth_w = 16;
    int mouth_y = cy + 10;

    current_mouth_h += (target_mouth_h - current_mouth_h) * 0.3;
    int h_int = (int)current_mouth_h;
    if (h_int < 1) h_int = 1; 

    oled.DrawRoundRect(cx - mouth_w/2, mouth_y - h_int/2, mouth_w, h_int, h_int/3 + 1, 1);
    if (h_int > 5) {
        oled.DrawLine(cx - 3, mouth_y, cx + 3, mouth_y, 0);
    }

    // 4. 两侧动态声波条
    int bar_dist = 35;
    for(int i=0; i<3; i++) {
        int height_l = (int)(current_mouth_h * (0.5 + 0.5 * sin(frame * 0.5 + i))); 
        oled.DrawFillRect(cx - bar_dist - i*4, cy - height_l/2, 2, height_l, 1);
        
        int height_r = (int)(current_mouth_h * (0.5 + 0.5 * cos(frame * 0.5 + i)));
        oled.DrawFillRect(cx + bar_dist + i*4, cy - height_r/2, 2, height_r, 1);
    }
}

void OledController::DrawSmile(int frame) {
    OledDriver& oled = OledDriver::GetInstance();
    
    static float x = 64, y = 32;       
    static float vx = 2.0, vy = 1.5;   
    int r = 16;                 
    int wink = 0;

    // 物理碰撞检测
    x += vx;
    y += vy;

    if (x < r || x > 128 - r) {
        vx = -vx;
        x += vx; 
    }
    if (y < r || y > 64 - r) {
        vy = -vy;
        y += vy;
    }

    if (frame % 40 > 35) wink = 1;
    else wink = 0;

    // Draw Smile Face
    int ix = (int)x;
    int iy = (int)y;
    
    // 1. 脸轮廓
    oled.DrawCircle(ix, iy, r, 1);
    
    // 2. 眼睛参数
    int eye_offset_x = r / 3;
    int eye_offset_y = r / 3;
    int eye_r = r / 5;

    // 左眼 (始终睁开)
    oled.DrawFillCircle(ix - eye_offset_x, iy - eye_offset_y, eye_r, 1);
    oled.DrawPoint(ix - eye_offset_x - 1, iy - eye_offset_y - 1, 0);

    // 右眼 (根据 wink 状态决定)
    if (wink) {
        oled.DrawLine(ix + eye_offset_x - eye_r, iy - eye_offset_y, 
                  ix + eye_offset_x + eye_r, iy - eye_offset_y, 1);
    } else {
        oled.DrawFillCircle(ix + eye_offset_x, iy - eye_offset_y, eye_r, 1);
        oled.DrawPoint(ix + eye_offset_x - 1, iy - eye_offset_y - 1, 0);
    }

    // 3. 嘴巴 (画弧线)
    oled.DrawArc(ix, iy - 2, r - 5, 45, 135);
}

