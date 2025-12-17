#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>

#include "../Hardware/motor.h"  // brings in Arduino.h (Linux headers) and gpio

static void usage(const char* prog) {
    std::printf("\nUsage: %s [-d forward|backward|cycle] [-s speed] [-n steps] [-c cycles]\n", prog);
    std::printf("  -d direction : forward/backward/cycle (default: cycle)\n");
    std::printf("  -s speed     : 1..10 (default: 5)\n");
    std::printf("  -n steps     : steps per move, 512 = one revolution (default: 512)\n");
    std::printf("  -c cycles    : forward+reverse cycles when -d cycle (default: 1)\n");
    std::printf("\nExamples:\n");
    std::printf("  %s                    # forward+reverse 1 cycle, speed 5, steps 512\n", prog);
    std::printf("  %s -d forward -s 8 -n 1024\n", prog);
    std::printf("  %s -d cycle -s 6 -n 256 -c 3\n\n", prog);
}

int main(int argc, char** argv) {
#if !defined(__linux__)
    std::fprintf(stderr, "This test is intended for Linux (openEuler) on ARM.\n");
    // You can still try to compile on other systems, but GPIO access will likely fail.
#endif

    std::string direction = "cycle"; // forward | backward | cycle
    int speed = 5;                    // 1..10
    int steps = 512;                  // 512 = one revolution
    int cycles = 1;                   // only for cycle mode

    // Simple args parsing
    for (int i = 1; i < argc; ++i) {
        if ((std::strcmp(argv[i], "-h") == 0) || (std::strcmp(argv[i], "--help") == 0)) {
            usage(argv[0]);
            return 0;
        } else if (std::strcmp(argv[i], "-d") == 0 && i + 1 < argc) {
            direction = argv[++i];
        } else if (std::strcmp(argv[i], "-s") == 0 && i + 1 < argc) {
            speed = std::atoi(argv[++i]);
        } else if (std::strcmp(argv[i], "-n") == 0 && i + 1 < argc) {
            steps = std::atoi(argv[++i]);
        } else if (std::strcmp(argv[i], "-c") == 0 && i + 1 < argc) {
            cycles = std::atoi(argv[++i]);
        } else {
            std::fprintf(stderr, "Unknown or incomplete argument: %s\n", argv[i]);
            usage(argv[0]);
            return 1;
        }
    }

    if (speed < 1) speed = 1;
    if (speed > 10) speed = 10;
    if (steps <= 0) steps = 512;
    if (cycles <= 0) cycles = 1;

    // Use global pointer to cooperate with signal handler in motor.cpp
    if (MOTOR::g_motor == nullptr) {
        MOTOR::g_motor = new MOTOR();
    }
    MOTOR* motor = MOTOR::g_motor;
    motor->setSpeed(speed);

    auto do_forward = [&]() {
        std::printf("[MOTORtest] Forward: steps=%d speed=%d\n", steps, speed);
        motor->motorForward(steps);
        motor->motorStop();
    };
    auto do_reverse = [&]() {
        std::printf("[MOTORtest] Reverse: steps=%d speed=%d\n", steps, speed);
        motor->motorReverse(steps);
        motor->motorStop();
    };

    if (direction == "forward") {
        do_forward();
    } else if (direction == "backward" || direction == "reverse") {
        do_reverse();
    } else if (direction == "cycle") {
        for (int i = 0; i < cycles; ++i) {
            std::printf("[MOTORtest] Cycle %d/%d\n", i + 1, cycles);
            do_forward();
            do_reverse();
        }
    } else {
        std::fprintf(stderr, "Unknown direction: %s\n", direction.c_str());
        delete MOTOR::g_motor; MOTOR::g_motor = nullptr;
        return 2;
    }

    // Cleanup
    delete MOTOR::g_motor; MOTOR::g_motor = nullptr;
    std::printf("[MOTORtest] Done.\n");
    return 0;
}