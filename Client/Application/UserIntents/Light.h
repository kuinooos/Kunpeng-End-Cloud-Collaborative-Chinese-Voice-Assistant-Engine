#ifndef LIGHT_H
#define LIGHT_H

#ifdef __arm__ 
#include <json/json.h>
#else
#include <jsoncpp/json/json.h>
#endif

namespace LightControl {
    void Control(const Json::Value& arguments);
}

#endif // LIGHT_H