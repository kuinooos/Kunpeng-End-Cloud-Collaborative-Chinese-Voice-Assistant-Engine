#ifndef GPIO_H
#define GPIO_H

#include "Arduino.h"

#define GPIO0 (3)
#define GPIO1 (228)
#define GPIO2 (128)
#define GPIO3 (84)
#define GPIO4 ((4-1)*32+23)

class GPIO {
    private:
        int m_iPin;
        string m_sPath;
        
    public:
        GPIO(void);
        GPIO(int pin);
        
        void setPin(int pin);
        int getPin(void);   
        
        void setPath(int pin);
        string getPath(void);
        
        int setDirection(int dir);
        int getDirection(void);
        
        int setValue(int val);
        int getValue(void);
        
        int exportGPIO(void);
        int unexportGPIO(void);
};

#endif
