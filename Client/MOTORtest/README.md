# MOTORtest (openEuler standalone)

一个可在 openEuler (ARM/Linux) 上直接用 g++ 编译运行的步进电机测试小程序，复用项目中的 GPIO/motor 实现。

## 依赖
- 需要在目标设备具备 /sys/class/gpio 访问权限（可能需要 root 或 udev 规则）
- 需要 Linux 头文件（unistd.h 等），已由 `Hardware/Arduino.h` 引入
- 无需 CMake，仅 g++ 与项目已有源码

## 编译

在 `AIChat_demo/Client/` 根目录下执行（注意相对路径）：

```sh
# 打开 O2 优化，包含路径指向 Client 根目录（以便找到 Hardware/*.h）
g++ -O2 -std=c++17 \
  MOTORtest/main.cpp \
  Hardware/gpio.cpp Hardware/motor.cpp \
  -I . -o MOTORtest/MOTORtest
```

如果你是在交叉编译环境，请用对应的交叉 g++（如 aarch64-linux-gnu-g++）并加上 --sysroot。

## 运行

```sh
cd MOTORtest
sudo ./MOTORtest -d cycle -s 5 -n 512 -c 2
```

参数说明：
- `-d` 方向：`forward` | `backward` | `cycle`（默认 cycle）
- `-s` 速度：1..10（默认 5，内部会映射到电机步骤延时）
- `-n` 步数：步进个数，512=一圈（默认 512）
- `-c` 循环次数：仅在 `-d cycle` 模式有效（默认 1）

## 安全提示
- 请勿用 `kill -9` 结束程序；`motor.cpp` 已注册信号处理，但 `SIGKILL` 无法捕获。异常退出可能导致 GPIO 输出保持，电机发热。
- 接线与 GPIO 号请根据你的平台适配（见 `Hardware/gpio.h`），必要时修改为你的开发板编号。
