#include "oled_driver.h"
#include <stdio.h>
#include <stdlib.h>
// Force sync 20251216
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <sys/ioctl.h>
#include <linux/spi/spidev.h>
#include <math.h>
#include <iostream>

#define SPI_DEVICE      "/dev/spidev0.0"
#define SPI_SPEED       1000000
#define GPIO_DC         38    

// Helper function to get font bitmap
// Replaced global array with function to avoid designated initializer issues in older C++ standards
const unsigned char* GetFontBitmap(char c) {
    static const unsigned char font_space[] = {0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00};
    static const unsigned char font_excl[] = {0x18, 0x3C, 0x3C, 0x18, 0x18, 0x00, 0x18, 0x00};
    static const unsigned char font_comma[] = {0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x18, 0x18};
    static const unsigned char font_dot[] = {0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x18, 0x18};
    static const unsigned char font_H[] = {0x66, 0x66, 0x66, 0x7E, 0x66, 0x66, 0x66, 0x00};
    static const unsigned char font_i[] = {0x18, 0x18, 0x00, 0x18, 0x18, 0x18, 0x18, 0x00};
    static const unsigned char font_I[] = {0x3C, 0x18, 0x18, 0x18, 0x18, 0x18, 0x3C, 0x00};
    static const unsigned char font_m[] = {0x00, 0x00, 0x66, 0xFF, 0xDB, 0xDB, 0xDB, 0x00};
    static const unsigned char font_K[] = {0x66, 0x6C, 0x78, 0x70, 0x78, 0x6C, 0x66, 0x00};
    static const unsigned char font_u[] = {0x00, 0x00, 0x66, 0x66, 0x66, 0x66, 0x3E, 0x00};
    static const unsigned char font_n[] = {0x00, 0x00, 0x6E, 0x7F, 0x6B, 0x6B, 0x6B, 0x00};
    static const unsigned char font_p[] = {0x00, 0x00, 0x6E, 0x7F, 0x6B, 0x6B, 0x6B, 0x60};
    static const unsigned char font_e[] = {0x00, 0x00, 0x3C, 0x7E, 0x7E, 0x60, 0x3C, 0x00};
    static const unsigned char font_g[] = {0x00, 0x00, 0x3E, 0x66, 0x3E, 0x06, 0x3E, 0x00};
    static const unsigned char font_quote[] = {0x18, 0x18, 0x08, 0x00, 0x00, 0x00, 0x00, 0x00};
    static const unsigned char font_z[] = {0x00, 0x00, 0x64, 0x74, 0x5C, 0x4C, 0x44, 0x00};
    static const unsigned char font_Z[] = {0x61, 0x51, 0x49, 0x45, 0x43, 0x00, 0x00, 0x00};

    switch(c) {
        case ' ': return font_space;
        case '!': return font_excl;
        case ',': return font_comma;
        case '.': return font_dot;
        case 'H': return font_H;
        case 'i': return font_i;
        case 'I': return font_I;
        case 'm': return font_m;
        case 'K': return font_K;
        case 'u': return font_u;
        case 'n': return font_n;
        case 'p': return font_p;
        case 'e': return font_e;
        case 'g': return font_g;
        case '\'': return font_quote;
        case 'z': return font_z;
        case 'Z': return font_Z;
        default: return font_space;
    }
}

OledDriver& OledDriver::GetInstance() {
    static OledDriver instance;
    return instance;
}

OledDriver::OledDriver() {
    memset(g_gram_, 0, sizeof(g_gram_));
}

OledDriver::~OledDriver() {
    Close();
}

bool OledDriver::Init() {
    GpioExport(GPIO_DC);
    GpioSetDir(GPIO_DC, 1);
    spi_fd_ = SpiInit();
    if (spi_fd_ < 0) return false;
    HardwareInit();
    return true;
}

void OledDriver::Close() {
    if (spi_fd_ >= 0) {
        close(spi_fd_);
        spi_fd_ = -1;
    }
}

void OledDriver::GpioExport(int gpio) {
    if (gpio < 0) return;
    char path[64]; sprintf(path, "/sys/class/gpio/gpio%d/direction", gpio);
    if (access(path, F_OK) == 0) return; 
    int fd = open("/sys/class/gpio/export", O_WRONLY);
    if (fd >= 0) { char buf[16]; sprintf(buf, "%d", gpio); write(fd, buf, strlen(buf)); close(fd); }
}

void OledDriver::GpioSetDir(int gpio, int out) {
    if (gpio < 0) return;
    char path[64]; sprintf(path, "/sys/class/gpio/gpio%d/direction", gpio);
    int fd = open(path, O_WRONLY);
    if (fd >= 0) { write(fd, out ? "out" : "in", out ? 3 : 2); close(fd); }
}

void OledDriver::GpioSetValue(int gpio, int val) {
    if (gpio < 0) return;
    char path[64]; sprintf(path, "/sys/class/gpio/gpio%d/value", gpio);
    int fd = open(path, O_WRONLY);
    if (fd >= 0) { write(fd, val ? "1" : "0", 1); close(fd); }
}

int OledDriver::SpiInit() {
    int fd = open(SPI_DEVICE, O_RDWR);
    if (fd < 0) { perror("SPI Error"); return -1; }
    uint8_t mode = SPI_MODE_0; uint8_t bits = 8; uint32_t speed = SPI_SPEED;
    ioctl(fd, SPI_IOC_WR_MODE, &mode);
    ioctl(fd, SPI_IOC_WR_BITS_PER_WORD, &bits);
    ioctl(fd, SPI_IOC_WR_MAX_SPEED_HZ, &speed);
    return fd;
}

void OledDriver::SpiSend(uint8_t *buf, int len) {
    if (spi_fd_ >= 0) write(spi_fd_, buf, len);
}

void OledDriver::WriteCmd(uint8_t cmd) {
    GpioSetValue(GPIO_DC, 0);
    SpiSend(&cmd, 1);
}

void OledDriver::WriteData(uint8_t *buf, int len) {
    GpioSetValue(GPIO_DC, 1);
    SpiSend(buf, len);
}

void OledDriver::SetPos(int x, int y) {
    WriteCmd(0xb0 + y);
    WriteCmd((x & 0x0f));
    WriteCmd(((x & 0xf0) >> 4) | 0x10);
}

void OledDriver::HardwareInit() {
    WriteCmd(0xae); WriteCmd(0x00); WriteCmd(0x10); 
    WriteCmd(0x40); WriteCmd(0xB0); WriteCmd(0x81); WriteCmd(0x66); 
    WriteCmd(0xa1); WriteCmd(0xa6); WriteCmd(0xa8); WriteCmd(0x3f); 
    WriteCmd(0xc8); WriteCmd(0xd3); WriteCmd(0x00); 
    WriteCmd(0xd5); WriteCmd(0x80); WriteCmd(0xd9); WriteCmd(0x1f); 
    WriteCmd(0xda); WriteCmd(0x12); WriteCmd(0xdb); WriteCmd(0x30); 
    WriteCmd(0x8d); WriteCmd(0x14); WriteCmd(0xaf); 
}

void OledDriver::Clear() {
    memset(g_gram_, 0, sizeof(g_gram_));
}

void OledDriver::Refresh() {
    for (int y = 0; y < 8; y++) {
        SetPos(0, y);
        WriteData(g_gram_[y], 128);
    }
}

void OledDriver::DrawPoint(int x, int y, int mode) {
    if (x < 0 || x >= 128 || y < 0 || y >= 64) return;
    if (mode) g_gram_[y/8][x] |= (1 << (y%8));
    else      g_gram_[y/8][x] &= ~(1 << (y%8));
}

void OledDriver::DrawLine(int x1, int y1, int x2, int y2, int mode) {
    int dx = abs(x2 - x1), sx = x1 < x2 ? 1 : -1;
    int dy = abs(y2 - y1), sy = y1 < y2 ? 1 : -1;
    int err = (dx > dy ? dx : -dy) / 2;
    while(1) {
        DrawPoint(x1, y1, mode);
        if (x1 == x2 && y1 == y2) break;
        int e2 = err;
        if (e2 > -dx) { err -= dy; x1 += sx; }
        if (e2 < dy) { err += dx; y1 += sy; }
    }
}

void OledDriver::DrawCircle(int x0, int y0, int r, int mode) {
    int x, y;
    for(y=-r; y<=r; y++) for(x=-r; x<=r; x++) 
        if(x*x + y*y <= r*r && x*x + y*y >= (r-1)*(r-1)) DrawPoint(x0+x, y0+y, mode);
}

void OledDriver::DrawFillCircle(int x0, int y0, int r, int mode) {
    int x, y;
    for(y=-r; y<=r; y++) for(x=-r; x<=r; x++) 
        if(x*x + y*y <= r*r) DrawPoint(x0+x, y0+y, mode);
}

void OledDriver::DrawRect(int x, int y, int w, int h, int mode) {
    DrawLine(x, y, x+w, y, mode);
    DrawLine(x, y+h, x+w, y+h, mode);
    DrawLine(x, y, x, y+h, mode);
    DrawLine(x+w, y, x+w, y+h, mode);
}

void OledDriver::DrawFillRect(int x, int y, int w, int h, int mode) {
    for(int i=x; i<x+w; i++) {
        for(int j=y; j<y+h; j++) {
            DrawPoint(i, j, mode);
        }
    }
}

void OledDriver::DrawArc(int x0, int y0, int r, int start_angle, int end_angle) {
    int x, y;
    for(int i=start_angle; i<=end_angle; i++) {
        x = x0 + r * cos(i * 3.14159 / 180);
        y = y0 + r * sin(i * 3.14159 / 180);
        DrawPoint(x, y, 1);
        DrawPoint(x, y+1, 1); // Thicken
    }
}

void OledDriver::DrawRoundRect(int x, int y, int w, int h, int r, int mode) {
    for(int i=x+r; i<x+w-r; i++) for(int j=y; j<y+h; j++) DrawPoint(i, j, mode);
    for(int i=x; i<x+w; i++) for(int j=y+r; j<y+h-r; j++) DrawPoint(i, j, mode);
    DrawFillCircle(x+r, y+r, r, mode);
    DrawFillCircle(x+w-r-1, y+r, r, mode);
    DrawFillCircle(x+r, y+h-r-1, r, mode);
    DrawFillCircle(x+w-r-1, y+h-r-1, r, mode);
}

void OledDriver::DrawChar8x8(int x, int y, char c) {
    if (c < 32 || c > 127) c = ' ';
    const unsigned char* bitmap = GetFontBitmap(c);
    for (int row = 0; row < 8; row++) {
        unsigned char line = bitmap[row];
        for (int col = 0; col < 8; col++) {
            if ((line << col) & 0x80) {
                DrawPoint(x + col, y + row, 1);
            }
        }
    }
}

void OledDriver::DrawString8x8(int x, int y, const char* str) {
    while(*str) {
        DrawChar8x8(x, y, *str);
        x += 8;
        str++;
    }
}

void OledDriver::DrawChar16x16(int x, int y, char c) {
    if (c < 32 || c > 127) c = ' ';
    const unsigned char* bitmap = GetFontBitmap(c);
    for (int row = 0; row < 8; row++) {
        unsigned char line = bitmap[row];
        for (int col = 0; col < 8; col++) {
            if ((line << col) & 0x80) {
                DrawPoint(x + col*2,     y + row*2,     1);
                DrawPoint(x + col*2 + 1, y + row*2,     1);
                DrawPoint(x + col*2,     y + row*2 + 1, 1);
                DrawPoint(x + col*2 + 1, y + row*2 + 1, 1);
            }
        }
    }
}

void OledDriver::DrawString16x16(int x, int y, const char* str) {
    while(*str) {
        DrawChar16x16(x, y, *str);
        x += 16;
        str++;
    }
}
