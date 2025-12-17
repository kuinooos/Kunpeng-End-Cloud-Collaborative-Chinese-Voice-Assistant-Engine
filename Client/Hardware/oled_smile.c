/* oled_smile.c
 * 平台：Orange Pi Kunpeng Pro
 * 内容：弹跳的眨眼笑脸动画
 * 编译: gcc oled_smile.c -o oled_smile -lm
 * 运行: sudo ./oled_smile
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

/* ============ 硬件配置 ============ */
#define SPI_DEVICE      "/dev/spidev0.0"
#define SPI_SPEED       1000000         // 1MHz

/* 您的固定配置 */
#define GPIO_DC         38    
#define GPIO_RES        -1    

int spi_fd = -1;
unsigned char g_gram[8][128]; // 显存缓冲

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
    if (fd < 0) {
        perror("无法打开 SPI 设备");
        return -1;
    }
    
    uint8_t mode = SPI_MODE_0;
    uint8_t bits = 8;
    uint32_t speed = SPI_SPEED;
    
    ioctl(fd, SPI_IOC_WR_MODE, &mode);
    ioctl(fd, SPI_IOC_WR_BITS_PER_WORD, &bits);
    ioctl(fd, SPI_IOC_WR_MAX_SPEED_HZ, &speed);
    
    return fd;
}

void spi_send(uint8_t *buf, int len) {
    write(spi_fd, buf, len);
}

/* ============ 驱动底层逻辑 ============ */
void oled_write_cmd(uint8_t cmd) {
    gpio_set_value(GPIO_DC, 0); // CMD
    spi_send(&cmd, 1);
}

void oled_write_datas(uint8_t *buf, int len) {
    gpio_set_value(GPIO_DC, 1); // DATA
    spi_send(buf, len);
}

void OLED_DIsp_Set_Pos(int x, int y) {
    oled_write_cmd(0xb0 + y);
    oled_write_cmd((x & 0x0f));
    oled_write_cmd(((x & 0xf0) >> 4) | 0x10);
}

void oled_hardware_init(void) {
    // 您的驱动初始化序列
    oled_write_cmd(0xae); 
    oled_write_cmd(0x00); oled_write_cmd(0x10); 
    oled_write_cmd(0x40); 
    oled_write_cmd(0xB0); 
    oled_write_cmd(0x81); oled_write_cmd(0x66); 
    oled_write_cmd(0xa1); 
    oled_write_cmd(0xa6); 
    oled_write_cmd(0xa8); oled_write_cmd(0x3f); 
    oled_write_cmd(0xc8); 
    oled_write_cmd(0xd3); oled_write_cmd(0x00); 
    oled_write_cmd(0xd5); oled_write_cmd(0x80); 
    oled_write_cmd(0xd9); oled_write_cmd(0x1f); 
    oled_write_cmd(0xda); oled_write_cmd(0x12); 
    oled_write_cmd(0xdb); oled_write_cmd(0x30); 
    oled_write_cmd(0x8d); oled_write_cmd(0x14); 
    oled_write_cmd(0xaf); 
}

void Refresh_GRAM(void) {
    int y;
    for (y = 0; y < 8; y++) {
        OLED_DIsp_Set_Pos(0, y);
        oled_write_datas(g_gram[y], 128);
    }
}

void Clear_GRAM(void) {
    memset(g_gram, 0, sizeof(g_gram));
}

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
    int e2;
    while(1) {
        Draw_Point(x1, y1, mode);
        if (x1 == x2 && y1 == y2) break;
        e2 = err;
        if (e2 > -dx) { err -= dy; x1 += sx; }
        if (e2 < dy) { err += dx; y1 += sy; }
    }
}

void Draw_Circle(int x0, int y0, int r, int mode) {
    int x, y;
    for(y=-r; y<=r; y++) 
        for(x=-r; x<=r; x++) 
            if(x*x + y*y <= r*r && x*x + y*y >= (r-1)*(r-1)) // 只画空心圆
                Draw_Point(x0+x, y0+y, mode);
}

void Draw_FillCircle(int x0, int y0, int r, int mode) {
    int x, y;
    for(y=-r; y<=r; y++) 
        for(x=-r; x<=r; x++) 
            if(x*x + y*y <= r*r) Draw_Point(x0+x, y0+y, mode);
}

// 画圆弧 (用于嘴巴)
void Draw_Arc(int x0, int y0, int r, int start_angle, int end_angle) {
    int x, y;
    // 简单粗暴法：遍历下半圆
    for(int i=start_angle; i<=end_angle; i++) {
        x = x0 + r * cos(i * 3.14 / 180);
        y = y0 + r * sin(i * 3.14 / 180);
        Draw_Point(x, y, 1);
        Draw_Point(x, y+1, 1); // 加粗
    }
}

/* ============ 笑脸逻辑 ============ */
void Draw_Smile_Face(int x, int y, int r, int wink) {
    // 1. 脸轮廓
    Draw_Circle(x, y, r, 1);
    
    // 2. 眼睛参数
    int eye_offset_x = r / 3;
    int eye_offset_y = r / 3;
    int eye_r = r / 5;

    // 左眼 (始终睁开)
    Draw_FillCircle(x - eye_offset_x, y - eye_offset_y, eye_r, 1);
    // 眼神光 (让眼睛有神)
    Draw_Point(x - eye_offset_x - 1, y - eye_offset_y - 1, 0);

    // 右眼 (根据 wink 状态决定)
    if (wink) {
        // 眨眼：画一条弯弯的线
        Draw_Line(x + eye_offset_x - eye_r, y - eye_offset_y, 
                  x + eye_offset_x + eye_r, y - eye_offset_y, 1);
    } else {
        // 睁眼
        Draw_FillCircle(x + eye_offset_x, y - eye_offset_y, eye_r, 1);
        Draw_Point(x + eye_offset_x - 1, y - eye_offset_y - 1, 0);
    }

    // 3. 嘴巴 (画弧线)
    // 角度从 45度 到 135度 (对应下半圆的笑容)
    Draw_Arc(x, y - 2, r - 5, 45, 135);
}

/* ============ 主程序 ============ */
int main() {
    printf("启动笑脸动画 (DC=GPIO%d)...\n", GPIO_DC);

    // 1. 初始化
    gpio_export(GPIO_DC);
    gpio_set_dir(GPIO_DC, 1);
    spi_fd = spi_init();
    if (spi_fd < 0) return -1;
    oled_hardware_init();
    
    // 2. 动画变量
    float x = 64, y = 32;       // 起始位置
    float vx = 2.0, vy = 1.5;   // 速度
    int r = 16;                 // 半径
    int frame = 0;
    int wink = 0;

    printf("笑脸开始弹跳...\n");

    while(1) {
        Clear_GRAM();

        // 物理碰撞检测
        x += vx;
        y += vy;

        // 碰到左右边界
        if (x < r || x > 128 - r) {
            vx = -vx;
            x += vx; // 把它推回来
        }
        // 碰到上下边界
        if (y < r || y > 64 - r) {
            vy = -vy;
            y += vy;
        }

        // 眨眼逻辑：每 40 帧眨眼一次，持续 5 帧
        if (frame % 40 > 35) wink = 1;
        else wink = 0;

        // 画脸
        Draw_Smile_Face((int)x, (int)y, r, wink);

        Refresh_GRAM();
        frame++;
        usleep(30000); // 30ms 一帧，约 33FPS
    }

    close(spi_fd);
    return 0;
}
