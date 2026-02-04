/* oled_thinking.c
 * 平台：Orange Pi Kunpeng Pro
 * 内容：思考者动画 (🤔 + 眼球转动 + 冒泡泡)
 * 编译: gcc oled_thinking.c -o oled_thinking -lm
 * 运行: sudo ./oled_thinking
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
            if(x*x + y*y <= r*r && x*x + y*y >= (r-1)*(r-1)) // 空心圆
                Draw_Point(x0+x, y0+y, mode);
}

void Draw_FillCircle(int x0, int y0, int r, int mode) {
    int x, y;
    for(y=-r; y<=r; y++) 
        for(x=-r; x<=r; x++) 
            if(x*x + y*y <= r*r)
                Draw_Point(x0+x, y0+y, mode);
}

void Draw_Rect(int x, int y, int w, int h, int mode) {
    int i, j;
    for(i=x; i<x+w; i++)
        for(j=y; j<y+h; j++)
            Draw_Point(i, j, mode);
}

/* ============ 思考者绘图逻辑 ============ */
void Draw_Thinking_Face(int frame) {
    int cx = 64, cy = 32; // 脸中心
    int r = 26;           // 脸半径

    // 1. 脸轮廓
    Draw_Circle(cx, cy, r, 1);

    // 2. 眉毛 (这是一个思考的灵魂)
    // 左眉毛：平的
    Draw_Line(cx - 15, cy - 12, cx - 5, cy - 12, 1);
    // 右眉毛：高高挑起 (Thinking 标志)
    Draw_Line(cx + 5, cy - 15, cx + 10, cy - 18, 1);
    Draw_Line(cx + 10, cy - 18, cx + 15, cy - 12, 1);

    // 3. 眼睛 (眼球转动逻辑)
    // 眼睛中心
    int eye_lx = cx - 10, eye_rx = cx + 10, eye_y = cy - 5;
    // 眼球偏移 (周期性左右看)
    int look_offset = 0;
    int anim_step = (frame / 5) % 4; // 动作节奏
    
    if (anim_step == 0) look_offset = 0;      // 看中间
    else if (anim_step == 1) look_offset = -3; // 看左边
    else if (anim_step == 2) look_offset = 0;  // 看中间
    else if (anim_step == 3) look_offset = 3;  // 看右边

    // 画眼白(空心) 和 眼珠(实心)
    Draw_Circle(eye_lx, eye_y, 4, 1);
    Draw_Circle(eye_rx, eye_y, 4, 1);
    Draw_FillCircle(eye_lx + look_offset, eye_y, 1, 1);
    Draw_FillCircle(eye_rx + look_offset, eye_y, 1, 1);

    // 4. 嘴巴 (抿嘴思考，直线)
    Draw_Line(cx - 5, cy + 12, cx + 8, cy + 12, 1);

    // 5. 手 (托着下巴)
    // 大拇指
    Draw_FillCircle(cx - 8, cy + 20, 3, 1);
    Draw_Line(cx - 8, cy + 20, cx - 8, cy + 28, 1); // 手臂连接
    // 食指 (横在嘴边)
    Draw_FillCircle(cx - 5, cy + 15, 3, 1);
    Draw_FillCircle(cx + 2, cy + 16, 3, 1);
    // 手掌部分
    Draw_FillCircle(cx, cy + 25, 6, 1);

    // 6. 思考气泡 "..." (依次出现)
    int bubble_step = (frame / 10) % 4; // 慢一点
    if (bubble_step >= 1) Draw_FillCircle(cx + 25, cy - 20, 2, 1); // 点1
    if (bubble_step >= 2) Draw_FillCircle(cx + 32, cy - 20, 2, 1); // 点2
    if (bubble_step >= 3) Draw_FillCircle(cx + 39, cy - 20, 2, 1); // 点3
}

/* ============ 主程序 ============ */
int main() {
    printf("启动思考者动画 (DC=GPIO%d)...\n", GPIO_DC);

    // 1. 初始化
    gpio_export(GPIO_DC);
    gpio_set_dir(GPIO_DC, 1);
    spi_fd = spi_init();
    if (spi_fd < 0) return -1;
    oled_hardware_init();
    
    printf("开始思考... (按 Ctrl+C 退出)\n");

    int frame = 0;
    while(1) {
        Clear_GRAM();

        Draw_Thinking_Face(frame);

        Refresh_GRAM();
        frame++;
        usleep(50000); // 50ms 一帧，约 20FPS
    }

    close(spi_fd);
    return 0;
}
