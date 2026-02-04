/* oled_speaking_v2.c
 * 平台：Orange Pi Kunpeng Pro
 * 内容：自然说话动画 (模拟音量随机变化 + 平滑过渡 + 声波条)
 * 编译: gcc oled_speaking_v2.c -o oled_speaking_v2 -lm
 * 运行: sudo ./oled_speaking_v2
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <sys/ioctl.h>
#include <linux/spi/spidev.h>
#include <sys/time.h>
#include <math.h>
#include <stdint.h>
#include <time.h>

/* ============ 硬件配置 ============ */
#define SPI_DEVICE      "/dev/spidev0.0"
#define SPI_SPEED       1000000         // 1MHz

/* 您的固定配置 */
#define GPIO_DC         38    
#define GPIO_RES        -1    

int spi_fd = -1;
unsigned char g_gram[8][128]; 

/* ============ GPIO 工具函数 ============ */
void gpio_export(int gpio) {
    if (gpio < 0) return;
    char path[64];
    sprintf(path, "/sys/class/gpio/gpio%d/direction", gpio);
    if (access(path, F_OK) == 0) return; 
    int fd = open("/sys/class/gpio/export", O_WRONLY);
    if (fd >= 0) {
        char buf[16];
        sprintf(buf, "%d", gpio);
        write(fd, buf, strlen(buf));
        close(fd);
    }
}

void gpio_set_dir(int gpio, int out) {
    if (gpio < 0) return;
    char path[64];
    sprintf(path, "/sys/class/gpio/gpio%d/direction", gpio);
    int fd = open(path, O_WRONLY);
    if (fd >= 0) {
        write(fd, out ? "out" : "in", out ? 3 : 2);
        close(fd);
    }
}

void gpio_set_value(int gpio, int val) {
    if (gpio < 0) return;
    char path[64];
    sprintf(path, "/sys/class/gpio/gpio%d/value", gpio);
    int fd = open(path, O_WRONLY);
    if (fd >= 0) {
        write(fd, val ? "1" : "0", 1);
        close(fd);
    }
}

/* ============ SPI 工具函数 ============ */
int spi_init() {
    int fd = open(SPI_DEVICE, O_RDWR);
    if (fd < 0) { perror("无法打开 SPI"); return -1; }
    uint8_t mode = SPI_MODE_0; uint8_t bits = 8; uint32_t speed = SPI_SPEED;
    ioctl(fd, SPI_IOC_WR_MODE, &mode);
    ioctl(fd, SPI_IOC_WR_BITS_PER_WORD, &bits);
    ioctl(fd, SPI_IOC_WR_MAX_SPEED_HZ, &speed);
    return fd;
}

void spi_send(uint8_t *buf, int len) { write(spi_fd, buf, len); }

/* ============ 驱动底层逻辑 ============ */
void oled_write_cmd(uint8_t cmd) { gpio_set_value(GPIO_DC, 0); spi_send(&cmd, 1); }
void oled_write_datas(uint8_t *buf, int len) { gpio_set_value(GPIO_DC, 1); spi_send(buf, len); }
void OLED_DIsp_Set_Pos(int x, int y) {
    oled_write_cmd(0xb0 + y);
    oled_write_cmd((x & 0x0f));
    oled_write_cmd(((x & 0xf0) >> 4) | 0x10);
}

void oled_hardware_init(void) {
    oled_write_cmd(0xae); oled_write_cmd(0x00); oled_write_cmd(0x10); 
    oled_write_cmd(0x40); oled_write_cmd(0xB0); oled_write_cmd(0x81); oled_write_cmd(0x66); 
    oled_write_cmd(0xa1); oled_write_cmd(0xa6); oled_write_cmd(0xa8); oled_write_cmd(0x3f); 
    oled_write_cmd(0xc8); oled_write_cmd(0xd3); oled_write_cmd(0x00); 
    oled_write_cmd(0xd5); oled_write_cmd(0x80); oled_write_cmd(0xd9); oled_write_cmd(0x1f); 
    oled_write_cmd(0xda); oled_write_cmd(0x12); oled_write_cmd(0xdb); oled_write_cmd(0x30); 
    oled_write_cmd(0x8d); oled_write_cmd(0x14); oled_write_cmd(0xaf); 
}

void Refresh_GRAM(void) {
    for (int y = 0; y < 8; y++) {
        OLED_DIsp_Set_Pos(0, y);
        oled_write_datas(g_gram[y], 128);
    }
}

void Clear_GRAM(void) { memset(g_gram, 0, sizeof(g_gram)); }

/* ============ 绘图库 ============ */
void Draw_Point(int x, int y, int mode) {
    if (x < 0 || x >= 128 || y < 0 || y >= 64) return;
    if (mode) g_gram[y/8][x] |= (1 << (y%8));
    else      g_gram[y/8][x] &= ~(1 << (y%8));
}

void Draw_Line(int x1, int y1, int x2, int y2, int mode) {
    int dx = abs(x2 - x1), sx = x1 < x2 ? 1 : -1;
    int dy = abs(y2 - y1), sy = y1 < y2 ? 1 : -1;
    int err = (dx > dy ? dx : -dy) / 2;
    while(1) {
        Draw_Point(x1, y1, mode);
        if (x1 == x2 && y1 == y2) break;
        int e2 = err;
        if (e2 > -dx) { err -= dy; x1 += sx; }
        if (e2 < dy) { err += dx; y1 += sy; }
    }
}

void Draw_Circle(int x0, int y0, int r, int mode) {
    int x, y;
    for(y=-r; y<=r; y++) for(x=-r; x<=r; x++) 
        if(x*x + y*y <= r*r && x*x + y*y >= (r-1)*(r-1)) Draw_Point(x0+x, y0+y, mode);
}

void Draw_FillCircle(int x0, int y0, int r, int mode) {
    int x, y;
    for(y=-r; y<=r; y++) for(x=-r; x<=r; x++) 
        if(x*x + y*y <= r*r) Draw_Point(x0+x, y0+y, mode);
}

void Draw_FillRect(int x, int y, int w, int h, int mode) {
    for(int i=x; i<x+w; i++) for(int j=y; j<y+h; j++) Draw_Point(i, j, mode);
}

// 画圆角矩形 (用于更圆润的嘴巴)
void Draw_RoundRect(int x, int y, int w, int h, int r, int mode) {
    // 简单的模拟：中间矩形 + 两头半圆
    Draw_FillRect(x+r, y, w-2*r, h, mode); // 中间
    Draw_FillRect(x, y+r, w, h-2*r, mode); // 两侧填充
    // 四个角 (偷懒用实心圆填充四个角)
    Draw_FillCircle(x+r, y+r, r, mode);
    Draw_FillCircle(x+w-r-1, y+r, r, mode);
    Draw_FillCircle(x+r, y+h-r-1, r, mode);
    Draw_FillCircle(x+w-r-1, y+h-r-1, r, mode);
}

/* ============ 自然说话动画逻辑 ============ */

// 全局变量，用于平滑过渡
float current_mouth_h = 2.0;
float target_mouth_h = 2.0;
int change_counter = 0;

void Draw_Natural_Speaking(int frame) {
    int cx = 64, cy = 32;
    int r = 26;

    // 1. 脸轮廓
    Draw_Circle(cx, cy, r, 1);

    // 2. 眼睛 (保持睁开，偶尔眨眼，眼神稳定)
    int eye_lx = cx - 10, eye_rx = cx + 10;
    int eye_y = cy - 6;
    if (frame % 50 > 45) { // 眨眼频率降低
        Draw_Line(eye_lx - 3, eye_y, eye_lx + 3, eye_y, 1);
        Draw_Line(eye_rx - 3, eye_y, eye_rx + 3, eye_y, 1);
    } else {
        Draw_FillCircle(eye_lx, eye_y, 3, 1);
        Draw_FillCircle(eye_rx, eye_y, 3, 1);
        Draw_Point(eye_lx - 1, eye_y - 1, 0); // 眼神光
        Draw_Point(eye_rx - 1, eye_y - 1, 0);
    }

    // 3. 嘴巴 (核心优化：模拟语音振幅)
    int mouth_y = cy + 8;
    int mouth_w = 14; // 嘴巴宽度

    // 算法：每隔几帧随机改变目标高度，模拟音节变化
    if (change_counter <= 0) {
        // 随机生成下一个嘴型高度 (0~10)
        // 30% 概率闭嘴 (停顿)，70% 概率张开不同程度
        if (rand() % 10 < 3) target_mouth_h = 1.0; 
        else target_mouth_h = 3.0 + (rand() % 8); 
        
        // 下次改变的时间间隔也随机 (模拟语速快慢)
        change_counter = 2 + (rand() % 4); 
    }
    change_counter--;

    // 平滑过渡 (Ease-in/out)
    // 每次向目标值移动 30% 的距离，避免突变
    current_mouth_h += (target_mouth_h - current_mouth_h) * 0.3;

    int h_int = (int)current_mouth_h;
    if (h_int < 1) h_int = 1; // 最小高度线

    // 绘制嘴巴 (使用圆角矩形，看起来像真实的嘴唇张合)
    // 居中绘制：y 坐标要上下延伸
    Draw_RoundRect(cx - mouth_w/2, mouth_y - h_int/2, mouth_w, h_int, h_int/3 + 1, 1);
    // 如果嘴巴张得够大，中间画个小黑线表示牙齿/舌头层次
    if (h_int > 5) {
        Draw_Line(cx - 3, mouth_y, cx + 3, mouth_y, 0);
    }

    // 4. 两侧动态声波条 (增加科技感，分散对嘴巴的注意力)
    // 在脸的两侧画几根跳动的柱子
    int bar_dist = 35;
    for(int i=0; i<3; i++) {
        // 左边声波
        int height_l = (int)(current_mouth_h * (0.5 + 0.5 * sin(frame * 0.5 + i))); 
        Draw_FillRect(cx - bar_dist - i*4, cy - height_l/2, 2, height_l, 1);
        
        // 右边声波
        int height_r = (int)(current_mouth_h * (0.5 + 0.5 * cos(frame * 0.5 + i)));
        Draw_FillRect(cx + bar_dist + i*4, cy - height_r/2, 2, height_r, 1);
    }
}

/* ============ 主程序 ============ */
int main() {
    printf("启动自然说话动画 (DC=GPIO%d)...\n", GPIO_DC);
    srand(time(NULL)); // 初始化随机数

    // 1. 初始化
    gpio_export(GPIO_DC);
    gpio_set_dir(GPIO_DC, 1);
    spi_fd = spi_init();
    if (spi_fd < 0) return -1;
    oled_hardware_init();
    
    printf("播放中... (平滑过渡 + 随机节奏)\n");

    int frame = 0;
    while(1) {
        Clear_GRAM();

        Draw_Natural_Speaking(frame);

        Refresh_GRAM();
        frame++;
        usleep(30000); // 30ms 帧率
    }

    close(spi_fd);
    return 0;
}
