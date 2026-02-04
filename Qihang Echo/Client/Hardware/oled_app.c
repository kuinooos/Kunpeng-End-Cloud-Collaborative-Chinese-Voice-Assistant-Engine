/* oled_tom_jerry.c
 * 平台：Orange Pi Kunpeng Pro
 * 驱动：纯应用层 (spidev + sysfs gpio)
 * 动画：Tom & Jerry (移植自您的代码)
 * * 编译: gcc oled_tom_jerry.c -o oled_tom_jerry -lm
 * 运行: sudo ./oled_tom_jerry
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

/* 您的正确配置 */
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

// 刷新 GRAM 到屏幕 (核心函数)
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

/* ============ 绘图库 (您的代码) ============ */
void Draw_Point(int x, int y, int mode) {
    if (x < 0 || x >= 128 || y < 0 || y >= 64) return;
    if (mode) g_gram[y/8][x] |= (1 << (y%8));
    else      g_gram[y/8][x] &= ~(1 << (y%8));
}

void Draw_Circle(int x0, int y0, int r, int mode) {
    int x, y;
    for(y=-r; y<=r; y++) 
        for(x=-r; x<=r; x++) 
            if(x*x + y*y <= r*r) Draw_Point(x0+x, y0+y, mode);
}

void Draw_Rect(int x, int y, int w, int h, int mode) {
    int i, j;
    for(i=x; i<x+w; i++)
        for(j=y; j<y+h; j++)
            Draw_Point(i, j, mode);
}

/* ============ Tom & Jerry 角色数据 ============ */
void Draw_Jerry(int x, int y, int leg_frame) {
    Draw_Circle(x-2, y-5, 3, 1); Draw_Circle(x+2, y-5, 3, 1); // 耳朵
    Draw_Circle(x, y, 4, 1); // 头
    Draw_Rect(x-2, y+4, 5, 6, 1); // 身体
    for(int i=0; i<5; i++) Draw_Point(x-2-i, y+8-i, 1); // 尾巴
    if(leg_frame % 2 == 0) { Draw_Rect(x-3, y+10, 2, 3, 1); Draw_Rect(x+1, y+10, 2, 1, 1); } 
    else { Draw_Rect(x-3, y+10, 2, 1, 1); Draw_Rect(x+1, y+10, 2, 3, 1); }
}

void Draw_Tom(int x, int y, int leg_frame) {
    for(int i=0; i<4; i++) { Draw_Point(x-4-i, y-6+i, 1); Draw_Point(x-4+i, y-6+i, 1); Draw_Point(x+4-i, y-6+i, 1); Draw_Point(x+4+i, y-6+i, 1); }
    Draw_Circle(x, y, 6, 1); 
    Draw_Rect(x-8, y+1, 4, 1, 1); Draw_Rect(x+4, y+1, 4, 1, 1);
    Draw_Rect(x-4, y+6, 9, 10, 1); Draw_Rect(x+5, y+6, 6, 2, 1);
    if(leg_frame % 2 == 0) { Draw_Rect(x-4, y+16, 3, 4, 1); Draw_Rect(x+2, y+16, 3, 2, 1); } 
    else { Draw_Rect(x-4, y+16, 3, 2, 1); Draw_Rect(x+2, y+16, 3, 4, 1); }
}

/* ============ 动画场景 ============ */
void Scene_Chase() {
    int t_x = -20, j_x = 20, frame = 0;
    while(t_x < 140) {
        Clear_GRAM();
        for(int i=0; i<128; i+=4) Draw_Rect(i, 60, 2, 1, 1); // 地面
        Draw_Jerry(j_x, 45, frame); j_x += 4;
        Draw_Tom(t_x, 40, frame); t_x += 3;
        if(frame % 3 == 0) { Draw_Rect(t_x-10, 40, 5, 1, 1); Draw_Rect(t_x-15, 45, 8, 1, 1); } // 速度线
        frame++; Refresh_GRAM();
        // usleep(20000); // 这里的延时控制动画速度，不需要太慢
    }
}

void Scene_Crash() {
    int t_x = 0, pan_x = 100, frame = 0;
    while(t_x < pan_x - 10) {
        Clear_GRAM(); Draw_Rect(pan_x, 30, 2, 20, 1); Draw_Rect(pan_x+2, 40, 10, 2, 1);
        Draw_Tom(t_x, 40, frame); t_x += 4; frame++; Refresh_GRAM();
    }
    for(int i=0; i<5; i++) {
        Clear_GRAM(); Draw_Rect(pan_x, 30, 2, 20, 1); Draw_Rect(pan_x-2, 30, 2, 20, 1);
        Draw_Point(pan_x-5, 25, 1); Draw_Point(pan_x-8, 22, 1); Draw_Point(pan_x-5, 55, 1); Draw_Point(pan_x-8, 58, 1);
        if(i%2) Draw_Rect(0, 0, 128, 64, 1); // 撞击闪烁
        Refresh_GRAM(); usleep(100000);
    }
    for(int y=40; y<60; y+=2) {
        Clear_GRAM(); Draw_Rect(pan_x, 30, 2, 20, 1); Draw_Rect(pan_x-10, y, 10, 2, 1); // 滑落
        Refresh_GRAM();
    }
}

void Scene_Cheese() {
    int j_x = 128, frame = 0;
    while(j_x > 50) {
        Clear_GRAM();
        int cx = j_x - 5, cy = 45;
        for(int h=0; h<10; h++) Draw_Rect(cx-h, cy+h, h*2, 1, 1);
        Draw_Point(cx, cy+5, 0);
        Draw_Jerry(j_x, 45, frame); j_x -= 2; frame++; Refresh_GRAM();
    }
    for(int i=0; i<10; i++) {
        Clear_GRAM();
        int cx = j_x - 5, cy = 45;
        for(int h=0; h<10; h++) Draw_Rect(cx-h, cy+h, h*2, 1, 1);
        Draw_Jerry(j_x, 45, 0);
        if(i > 5) { // 恐怖眼睛
            Draw_Circle(20, 30, 5, 1); Draw_Point(20, 30, 0); 
            Draw_Circle(40, 30, 5, 1); Draw_Point(40, 30, 0);
            for(int x=20; x<=40; x++) Draw_Point(x, 45 + (x-30)*(x-30)/50, 1); 
        }
        Refresh_GRAM(); usleep(200000);
    }
    while(j_x < 140) {
        Clear_GRAM(); Draw_Jerry(j_x, 45, frame);
        int cx = 50 - 5, cy = 45;
        for(int h=0; h<10; h++) Draw_Rect(cx-h, cy+h, h*2, 1, 1); // 奶酪留下
        j_x += 8; frame++; Refresh_GRAM();
    }
}

/* ============ 主程序 ============ */
int main() {
    printf("启动 Tom & Jerry 动画 (DC=GPIO%d)...\n", GPIO_DC);

    // 1. 初始化 GPIO
    gpio_export(GPIO_DC);
    gpio_set_dir(GPIO_DC, 1);

    // 2. 初始化 SPI
    spi_fd = spi_init();
    if (spi_fd < 0) return -1;

    // 3. 屏幕初始化
    oled_hardware_init();
    Clear_GRAM();
    Refresh_GRAM();

    printf("开始播放...\n");

    while(1) {
        Scene_Chase();
        sleep(1);
        Scene_Crash();
        sleep(1);
        Scene_Cheese();
        sleep(1);
        
        // 字幕
        Clear_GRAM();
        Draw_Rect(40, 20, 48, 24, 1); 
        Draw_Rect(42, 22, 44, 20, 0); 
        Draw_Rect(50, 30, 28, 4, 1);  
        Refresh_GRAM();
        sleep(2);
    }

    close(spi_fd);
    return 0;
}
