cmake_minimum_required(VERSION 3.10)

# Option to choose target architecture
option(TARGET_ARM "Build for ARM architecture" OFF)

# 选择静态库：优先允许用户通过 -DSNOWBOY_LIBRARY 覆盖；否则按架构选择
if(NOT DEFINED SNOWBOY_LIBRARY)
    # 检查是否存在 aarch64 专用库
    if(CMAKE_SYSTEM_PROCESSOR MATCHES "aarch64|arm64" AND EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/lib/aarch64/libsnowboy-detect.a")
        set(SNOWBOY_LIBRARY "${CMAKE_CURRENT_SOURCE_DIR}/lib/aarch64/libsnowboy-detect.a")
        message(STATUS "Snowboy: detected aarch64, using ${SNOWBOY_LIBRARY}")
    elseif(TARGET_ARM OR CMAKE_SYSTEM_PROCESSOR MATCHES "aarch64|arm64|arm")
        # 如果是 ARM 架构但没有 aarch64 库，或者明确指定了 TARGET_ARM，则尝试使用 rpi (通常是 armv7) 库
        # 注意：在纯 64 位系统上链接 32 位库可能会失败
        set(SNOWBOY_LIBRARY "${CMAKE_CURRENT_SOURCE_DIR}/lib/rpi/libsnowboy-detect.a")
        message(STATUS "Snowboy: TARGET_ARM set or aarch64 lib missing, using fallback: ${SNOWBOY_LIBRARY}")
        if(NOT DEFINED CMAKE_TOOLCHAIN_FILE)
            set(CMAKE_TOOLCHAIN_FILE "${CMAKE_CURRENT_SOURCE_DIR}/toolchain.cmake" CACHE FILEPATH "Default toolchain file for ARM builds")
            message(STATUS "No toolchain file specified; using default: ${CMAKE_TOOLCHAIN_FILE}")
        endif()
        message(STATUS "Building for ARM using toolchain file: ${CMAKE_TOOLCHAIN_FILE}")
    else()
        set(SNOWBOY_LIBRARY "${CMAKE_CURRENT_SOURCE_DIR}/lib/ubuntu64/libsnowboy-detect.a")
        message(STATUS "Snowboy: defaulting to x86 ubuntu64 lib: ${SNOWBOY_LIBRARY}")
    endif()
else()
    message(STATUS "Snowboy: using user-provided library: ${SNOWBOY_LIBRARY}")
endif()

# Set the project name and define the library
project(SnowboyLib)

add_compile_definitions(_GLIBCXX_USE_CXX11_ABI=0)

# Include directories
include_directories(${CMAKE_CURRENT_SOURCE_DIR})

# 搜索所有 .cc 和 .h 文件
file(GLOB_RECURSE SNOWBOY_SOURCES
    #"${CMAKE_CURRENT_SOURCE_DIR}/*.cc"
    "${CMAKE_CURRENT_SOURCE_DIR}/demo2.cc"
    "${CMAKE_CURRENT_SOURCE_DIR}/*.h"
)

# 添加静态库
add_library(snowboy STATIC ${SNOWBOY_SOURCES})

# Link libraries
# target_link_libraries(snowboy PRIVATE ${SNOWBOY_LIBRARY})
# 使用绝对路径，避免链接器将相对路径误判为库名
get_filename_component(SNOWBOY_LIBRARY_ABS ${SNOWBOY_LIBRARY} ABSOLUTE)
target_link_libraries(snowboy PRIVATE ${SNOWBOY_LIBRARY_ABS})

# Additional flags and options
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

find_package(PkgConfig REQUIRED)

# 确保链接必要的数学库
if(TARGET_ARM)
    find_package(OpenBLAS REQUIRED)

    if(OpenBLAS_FOUND)
        set(BLAS_LIBRARIES ${OpenBLAS_LIBRARIES})
        set(LAPACK_LIBRARIES ${OpenBLAS_LIBRARIES})  # OpenBLAS 包含 LAPACK 实现
        set(BLAS_INCLUDE_DIRS ${OpenBLAS_INCLUDE_DIR})
    endif()
else()
    find_package(BLAS REQUIRED)
    find_package(LAPACK REQUIRED)
endif()

# 将找到的库添加到目标
target_include_directories(snowboy PUBLIC ${BLAS_INCLUDE_DIRS})
target_link_libraries(snowboy PRIVATE ${BLAS_LIBRARIES} ${LAPACK_LIBRARIES})

# Create the C wrapper for snowboy-detect
add_library(snowboy-detect-c-wrapper STATIC
    snowboy-detect-c-wrapper.cc  # C wrapper implementation
)

# Link the snowboy C++ library into the C wrapper
target_link_libraries(snowboy-detect-c-wrapper PRIVATE snowboy)

# 添加一个可选的 demo 可执行文件
if(BUILD_DEMO)
    add_executable(demo2 demo2.cc)
    target_link_libraries(demo2 snowboy)
endif()
