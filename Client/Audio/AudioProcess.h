// SPDX-License-Identifier: MulanPSL-2.0
// 鲲鹏端云协同中文语音助手引擎 - 音频处理接口
// 说明：封装 PortAudio 录放音与 Opus 编解码；线程安全队列管理
#ifndef AUDIOPROCESS_H
#define AUDIOPROCESS_H

#include <vector>
#include <queue>
#include <mutex>
#include <condition_variable>
#include <opus/opus.h>
#include <cstdint>
#include <thread>
#include <portaudio.h>
#include "../WebSocket/WebsocketClient.h"

/**
 * 音频处理：录音、播放、Opus 编解码及简易帧打包
 */
class AudioProcess {
public:
    /// 构造：采样率/通道/帧时长(ms)
    AudioProcess(int sample_rate = 16000, int channels = 1, int frame_duration_ms = 40);
    ~AudioProcess();

    int get_sample_rate() const { return sample_rate; }
    int get_channels() const { return channels; }
    int get_frame_duration() const { return frame_duration_ms; }

    /// 录音队列是否为空
    bool recordedQueueIsEmpty() const { return recordedAudioQueue.empty(); }
    /// 播放队列是否为空
    bool playbackQueueIsEmpty() const { return playbackQueue.empty(); }

    /// 启动录音
    bool startRecording();

    /// 停止录音
    bool stopRecording();

    /// 清空录音队列
    void clearRecordedAudioQueue();

    /// 启动播放
    bool startPlaying();

    /// 停止播放
    bool stopPlaying();

    /// 清空播放队列
    void clearPlaybackAudioQueue();

    /**
     * 从录音队列取一帧（阻塞直至有数据或录音停止）
     */
    bool getRecordedAudio(std::vector<int16_t>& recordedData);

    /// 向播放队列追加一帧（不足会静音填充至帧长）
    void addFrameToPlaybackQueue(const std::vector<int16_t>& pcm_frame);

    /** 从 PCM 文件读取并切帧（16-bit little-endian） */
    std::queue<std::vector<int16_t>> loadAudioFromFile(const std::string& filename, int frame_duration_ms);

    /** 将任意帧队列保存为 PCM 文件 */
    void saveToPCMFile(const std::string& filename, const std::queue<std::vector<int16_t>>& audioQueue);

    /** 将录音队列保存为 PCM 文件 */
    void saveToPCMFile(const std::string& filename);


    /** PCM -> Opus 编码（单帧） */
    bool encode(const std::vector<int16_t>& pcm_frame, uint8_t* opus_data, size_t& opus_data_size);

    /** Opus -> PCM 解码（单帧） */
    bool decode(const uint8_t* opus_data, size_t opus_data_size, std::vector<int16_t>& pcm_frame);

    /** 打包为二进制协议帧（ws 传输） */
    BinProtocol* PackBinFrame(const uint8_t* payload, size_t payload_size, int ws_protocol_version);

    /** 解析二进制协议帧，提取 Opus 负载与协议信息 */
    bool UnpackBinFrame(const uint8_t* packed_data, size_t packed_data_size, BinProtocolInfo& protocol_info, std::vector<uint8_t>& opus_data);

private:
    // PortAudio 录音回调
    static int recordCallback(const void *inputBuffer, void *outputBuffer,
                              unsigned long framesPerBuffer,
                              const PaStreamCallbackTimeInfo* timeInfo,
                              PaStreamCallbackFlags statusFlags,
                              void *userData);

    // PortAudio 播放回调
    static int playCallback(const void *inputBuffer, void *outputBuffer,
                            unsigned long framesPerBuffer,
                            const PaStreamCallbackTimeInfo* timeInfo,
                            PaStreamCallbackFlags statusFlags,
                            void *userData);

    // Opus 编码器
    OpusEncoder* encoder;
    // Opus 解码器
    OpusDecoder* decoder;

    int sample_rate;
    int channels;
    int frame_duration_ms;

    std::queue<std::vector<int16_t>> recordedAudioQueue;
    std::mutex recordedAudioMutex;
    std::condition_variable recordedAudioCV;
    PaStream* recordStream;
    bool isRecording;
    std::queue<std::vector<int16_t>> playbackQueue;
    std::mutex playbackMutex;
    PaStream* playbackStream;
    bool isPlaying;

    // 初始化/释放 Opus
    bool initializeOpus();
    void cleanupOpus();
};

#endif // AUDIOPROCESS_H