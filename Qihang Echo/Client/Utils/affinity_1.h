#pragma once

#if defined(__linux__)
#include <pthread.h>
#include <sched.h>
#include <vector>
#include <string>
#include <sstream>
#include <algorithm>

inline cpu_set_t parse_cpu_set(const std::string& spec) {
    cpu_set_t set; CPU_ZERO(&set);
    std::stringstream ss(spec);
    std::string token;
    while (std::getline(ss, token, ',')) {
        auto dash = token.find('-');
        if (dash != std::string::npos) {
            int a = std::stoi(token.substr(0, dash));
            int b = std::stoi(token.substr(dash + 1));
            for (int i = a; i <= b; ++i) CPU_SET(i, &set);
        } else if (!token.empty()) {
            CPU_SET(std::stoi(token), &set);
        }
    }   
    return set;
}

inline void set_current_thread_affinity(const std::string& cpus_spec) {
    cpu_set_t set = parse_cpu_set(cpus_spec);
    pthread_setaffinity_np(pthread_self(), sizeof(set), &set);
}
#else
inline void set_current_thread_affinity(const char*) {}
#endif
