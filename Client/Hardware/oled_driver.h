#ifndef OLED_DRIVER_H
#define OLED_DRIVER_H

#include <stdint.h>
#include <string>

class OledDriver {
public:
    static OledDriver& GetInstance();

    bool Init();
    void Close();
    
    void Clear();
    void Refresh();
    
    void DrawPoint(int x, int y, int mode);
    void DrawLine(int x1, int y1, int x2, int y2, int mode);
    void DrawCircle(int x0, int y0, int r, int mode);
    void DrawFillCircle(int x0, int y0, int r, int mode);
    void DrawRect(int x, int y, int w, int h, int mode);
    void DrawFillRect(int x, int y, int w, int h, int mode);
    void DrawRoundRect(int x, int y, int w, int h, int r, int mode);
    void DrawArc(int x0, int y0, int r, int start_angle, int end_angle);
    
    void DrawChar8x8(int x, int y, char c);
    void DrawString8x8(int x, int y, const char* str);
    void DrawChar16x16(int x, int y, char c);
    void DrawString16x16(int x, int y, const char* str);

private:
    OledDriver();
    ~OledDriver();
    
    int spi_fd_ = -1;
    unsigned char g_gram_[8][128];
    
    void GpioExport(int gpio);
    void GpioSetDir(int gpio, int out);
    void GpioSetValue(int gpio, int val);
    int SpiInit();
    void SpiSend(uint8_t *buf, int len);
    void WriteCmd(uint8_t cmd);
    void WriteData(uint8_t *buf, int len);
    void SetPos(int x, int y);
    void HardwareInit();
};

#endif // OLED_DRIVER_H
