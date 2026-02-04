/* oled_listening_v2.c
 * 平台：Orange Pi Kunpeng Pro
 * 内容：更明显的倾听动画 (手掌拢耳 + 侧身 + 动态声波)
 * 编译: gcc oled_listening_v2.c -o oled_listening_v2 -lm
 * 运行: sudo ./oled_listening_v2
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
            if(x*x + y*y <= r*r && x*x + y*y >= (r-1)*(r-1))
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

void Draw_Arc(int x0, int y0, int r, int start_angle, int end_angle) {
    int i;
    float rad;
    for(i = start_angle; i <= end_angle; i++) {
        rad = i * 3.14159 / 180.0;
        int x = x0 + (int)(r * cos(rad));
        int y = y0 + (int)(r * sin(rad));
        Draw_Point(x, y, 1);
        Draw_Point(x, y+1, 1); // 加粗
    }
}

/* ============ 核心：明显的倾听动画 ============ */
void Draw_Obvious_Listen(int frame) {
    int cx = 50, cy = 32; // 脸向左移，留出右边给“手”和“波”
    int r = 26;

    // 1. 脸轮廓
    Draw_Circle(cx, cy, r, 1);

    // 2. 眼睛 (向右看，盯着声音来源)
    int eye_l_x = cx - 10, eye_r_x = cx + 10;
    int eye_y = cy - 5;
    Draw_Circle(eye_l_x, eye_y, 5, 1);
    Draw_Circle(eye_r_x, eye_y, 5, 1);
    // 眼珠强烈向右
    Draw_FillCircle(eye_l_x + 2, eye_y, 2, 1);
    Draw_FillCircle(eye_r_x + 2, eye_y, 2, 1);

    // 3. 嘴巴 (微张，表示专注)
    Draw_Circle(cx, cy + 12, 3, 1); 
    Draw_FillCircle(cx, cy + 12, 1, 0); // 镂空中间

    // 4. 夸张的右耳 (关键点！)
    int ear_x = cx + 24;
    int ear_y = cy;
    // 画一个C形的大耳朵
    Draw_Arc(ear_x - 5, ear_y, 10, -90, 90); 
    Draw_Arc(ear_x - 5, ear_y, 9, -90, 90);  // 加粗

    // 5. 手掌拢耳动作 (Cupping Hand)
    // 在耳朵后面画几个长条形，代表手指，模拟把耳朵往前推的动作
    int hand_x = ear_x + 5;
    int finger_w = 4;
    int finger_h = 12;
    // 食指
    Draw_FillCircle(hand_x, ear_y - 10, 3, 1);
    Draw_Rect(hand_x - 2, ear_y - 10, finger_w, finger_h, 1);
    // 中指
    Draw_FillCircle(hand_x + 3, ear_y - 2, 3, 1);
    Draw_Rect(hand_x + 1, ear_y - 2, finger_w, finger_h, 1);
    // 无名指
    Draw_FillCircle(hand_x + 2, ear_y + 8, 3, 1);
    Draw_Rect(hand_x, ear_y + 8, finger_w, finger_h - 2, 1);

    // 6. 动态声波 (从屏幕右边缘飞入耳朵)
    int wave_center_x = ear_x + 10;
    int wave_center_y = ear_y;
    int speed_div = 3; // 动画速度
    
    // 画3层向内收缩的波纹
    for(int i=0; i<3; i++) {
        // 让波纹向耳朵移动 (半径缩小)
        // (frame/speed_div) 是时间增量
        // i*10 是波纹间距
        // % 30 循环周期
        int raw_val = ((frame / speed_div) + i * 10);
        int current_r = 35 - (raw_val % 35); // 35 -> 0 收缩效果
        
        if (current_r > 5 && current_r < 35) {
            // 画右侧的圆弧 (((( 
            Draw_Arc(wave_center_x, wave_center_y, current_r, -45, 45);
            Draw_Arc(wave_center_x + 1, wave_center_y, current_r, -45, 45); // 加粗
        }
    }
}

/* ============ 主程序 ============ */
int main() {
    printf("启动明显的倾听动画 (DC=GPIO%d)...\n", GPIO_DC);

    // 1. 初始化
    gpio_export(GPIO_DC);
    gpio_set_dir(GPIO_DC, 1);
    spi_fd = spi_init();
    if (spi_fd < 0) return -1;
    oled_hardware_init();
    
    printf("正在倾听 (手掌拢耳 + 波纹入耳)...\n");

    int frame = 0;
    while(1) {
        Clear_GRAM();

        Draw_Obvious_Listen(frame);

        Refresh_GRAM();
        frame++;
        usleep(30000); // 30ms
    }

    close(spi_fd);
    return 0;
}
