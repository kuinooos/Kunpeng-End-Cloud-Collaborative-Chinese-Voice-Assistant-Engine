/* oled_final_v3.c
 * 平台：Orange Pi Kunpeng Pro
 * 内容：眨眼机器人 + 放大版英文显示 (绝对无乱码)
 * 编译: gcc oled_final_v3.c -o oled_final_v3 -lm
 * 运行: sudo ./oled_final_v3
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
#define SPI_SPEED       1000000

/* 您的配置 */
#define GPIO_DC         38    
#define GPIO_RES        -1    

int spi_fd = -1;
unsigned char g_gram[8][128]; 

/* ============ 标准 8x8 字体 (逐行式 - 肉眼可辨) ============ */
/* 每一行代表 8 个像素，MSB 在左 */
const unsigned char font8x8_basic[][8] = {
    [' '] = {0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00},
    ['!'] = {0x18, 0x3C, 0x3C, 0x18, 0x18, 0x00, 0x18, 0x00},
    [','] = {0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x18, 0x18}, // 修正逗号
    ['.'] = {0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x18, 0x18}, // 句号修正
    ['H'] = {0x66, 0x66, 0x66, 0x7E, 0x66, 0x66, 0x66, 0x00},
    ['i'] = {0x18, 0x18, 0x00, 0x18, 0x18, 0x18, 0x18, 0x00},
    ['I'] = {0x3C, 0x18, 0x18, 0x18, 0x18, 0x18, 0x3C, 0x00},
    ['m'] = {0x00, 0x00, 0x66, 0xFF, 0xDB, 0xDB, 0xDB, 0x00},
    ['K'] = {0x66, 0x6C, 0x78, 0x70, 0x78, 0x6C, 0x66, 0x00},
    ['u'] = {0x00, 0x00, 0x66, 0x66, 0x66, 0x66, 0x3E, 0x00},
    ['n'] = {0x00, 0x00, 0x6E, 0x7F, 0x6B, 0x6B, 0x6B, 0x00},
    ['p'] = {0x00, 0x00, 0x6E, 0x7F, 0x6B, 0x6B, 0x6B, 0x60},
    ['e'] = {0x00, 0x00, 0x3C, 0x7E, 0x7E, 0x60, 0x3C, 0x00},
    ['g'] = {0x00, 0x00, 0x3E, 0x66, 0x3E, 0x06, 0x3E, 0x00}, 
    ['\''] = {0x18, 0x18, 0x08, 0x00, 0x00, 0x00, 0x00, 0x00}, // 单引号
};

/* ============ 基础驱动 ============ */
void gpio_export(int gpio) {
    if (gpio < 0) return;
    char path[64]; sprintf(path, "/sys/class/gpio/gpio%d/direction", gpio);
    if (access(path, F_OK) == 0) return; 
    int fd = open("/sys/class/gpio/export", O_WRONLY);
    if (fd >= 0) { char buf[16]; sprintf(buf, "%d", gpio); write(fd, buf, strlen(buf)); close(fd); }
}
void gpio_set_dir(int gpio, int out) {
    if (gpio < 0) return;
    char path[64]; sprintf(path, "/sys/class/gpio/gpio%d/direction", gpio);
    int fd = open(path, O_WRONLY);
    if (fd >= 0) { write(fd, out ? "out" : "in", out ? 3 : 2); close(fd); }
}
void gpio_set_value(int gpio, int val) {
    if (gpio < 0) return;
    char path[64]; sprintf(path, "/sys/class/gpio/gpio%d/value", gpio);
    int fd = open(path, O_WRONLY);
    if (fd >= 0) { write(fd, val ? "1" : "0", 1); close(fd); }
}
int spi_init() {
    int fd = open(SPI_DEVICE, O_RDWR);
    if (fd < 0) { perror("SPI Error"); return -1; }
    uint8_t mode = SPI_MODE_0; uint8_t bits = 8; uint32_t speed = SPI_SPEED;
    ioctl(fd, SPI_IOC_WR_MODE, &mode);
    ioctl(fd, SPI_IOC_WR_BITS_PER_WORD, &bits);
    ioctl(fd, SPI_IOC_WR_MAX_SPEED_HZ, &speed);
    return fd;
}
void spi_send(uint8_t *buf, int len) { write(spi_fd, buf, len); }
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
void Draw_Point(int x, int y, int mode) {
    if (x < 0 || x >= 128 || y < 0 || y >= 64) return;
    if (mode) g_gram[y/8][x] |= (1 << (y%8));
    else      g_gram[y/8][x] &= ~(1 << (y%8));
}

// 绘制 8x8 字符 (逐行式解析，保证正确)
void Draw_Char8x8(int x, int y, char c) {
    // 简单过滤非法字符
    if (c < 32 || c > 127) c = ' ';
    
    for (int row = 0; row < 8; row++) {
        unsigned char line = font8x8_basic[(int)c][row];
        for (int col = 0; col < 8; col++) {
            // 0x80 是最左边的像素 (MSB Left)
            if ((line << col) & 0x80) {
                Draw_Point(x + col, y + row, 1);
            }
        }
    }
}

// 绘制放大 2 倍的字符 (16x16)
void Draw_Char16x16(int x, int y, char c) {
    if (c < 32 || c > 127) c = ' ';
    for (int row = 0; row < 8; row++) {
        unsigned char line = font8x8_basic[(int)c][row];
        for (int col = 0; col < 8; col++) {
            if ((line << col) & 0x80) {
                // 一个点画成 2x2 的方块
                Draw_Point(x + col*2,     y + row*2,     1);
                Draw_Point(x + col*2 + 1, y + row*2,     1);
                Draw_Point(x + col*2,     y + row*2 + 1, 1);
                Draw_Point(x + col*2 + 1, y + row*2 + 1, 1);
            }
        }
    }
}

void Draw_String16(int x, int y, char *str) {
    while(*str) {
        Draw_Char16x16(x, y, *str);
        x += 16; // 移动 16 像素
        str++;
    }
}

/* ============ 绘图辅助 ============ */
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
void Draw_RoundRect(int x, int y, int w, int h, int r, int mode) {
    for(int i=x+r; i<x+w-r; i++) for(int j=y; j<y+h; j++) Draw_Point(i, j, mode);
    for(int i=x; i<x+w; i++) for(int j=y+r; j<y+h-r; j++) Draw_Point(i, j, mode);
    Draw_FillCircle(x+r, y+r, r, mode);
    Draw_FillCircle(x+w-r-1, y+r, r, mode);
    Draw_FillCircle(x+r, y+h-r-1, r, mode);
    Draw_FillCircle(x+w-r-1, y+h-r-1, r, mode);
}

/* ============ 最终场景 ============ */
void Draw_Final_Scene(int frame) {
    // 1. 显示大号文字 (右侧)
    // "Hi,"
    Draw_String16(64, 12, "Hi,");
    // "Kunpeng" (用 8x8 显示，因为 16x16 太长放不下)
    // Draw_String16(32, 40, "I'm Kunpeng"); // 太长了
    // 换回小字体显示名字
    char *name = "I'm Kunpeng";
    int nx = 40, ny = 40;
    while(*name) {
        Draw_Char8x8(nx, ny, *name);
        nx += 8; name++;
    }

    // 2. 呼吸机器人 (左侧)
    float breath_val = sin(frame * 0.1); 
    int body_offset_y = (int)(breath_val * 1.5); 
    int rx = 4, ry = 35 + body_offset_y; 

    // 身体
    Draw_RoundRect(rx, ry, 32, 22, 5, 1);
    Draw_RoundRect(rx+4, ry+4, 24, 14, 3, 0); // 屏幕镂空

    // 眼睛 (眨眼动画)
    int eye_y = ry + 11;
    if (frame % 50 > 45) { // 闭眼
        Draw_Line(rx+8, eye_y, rx+12, eye_y, 1);
        Draw_Line(rx+18, eye_y, rx+22, eye_y, 1);
    } else { // 睁眼 (圆点)
        Draw_FillCircle(rx+10, eye_y, 2, 1);
        Draw_FillCircle(rx+20, eye_y, 2, 1);
    }
    
    // 天线
    Draw_Line(rx+16, ry, rx+16, ry-5, 1);
    Draw_FillCircle(rx+16, ry-6, 1, 1);

    // Zzz... (呼噜)
    int z_start_x = rx + 24;
    int z_start_y = ry - 8;
    int step = (frame / 10) % 3;
    if(step >= 0) { Draw_Char8x8(z_start_x, z_start_y, '.'); }
    if(step >= 1) { Draw_Char8x8(z_start_x+6, z_start_y-6, 'z'); }
    if(step >= 2) { Draw_Char8x8(z_start_x+12, z_start_y-12, 'Z'); }
}

/* ============ 主程序 ============ */
int main() {
    printf("启动 OLED 最终版 (DC=GPIO%d)...\n", GPIO_DC);

    gpio_export(GPIO_DC); gpio_set_dir(GPIO_DC, 1);
    spi_fd = spi_init();
    if (spi_fd < 0) return -1;
    oled_hardware_init();
    
    printf("显示内容：机器人 + Hi, I'm Kunpeng\n");

    int frame = 0;
    while(1) {
        Clear_GRAM();
        Draw_Final_Scene(frame);
        Refresh_GRAM();
        frame++;
        usleep(40000); 
    }

    close(spi_fd);
    return 0;
}
