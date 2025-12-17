// SPDX-License-Identifier: MulanPSL-2.0
#include "./AudioProcess.h"
#include "../Utils/user_log.h"
#include "../Utils/affinity.h"
#include <cstdlib>
#include <iostream>
#include <fstream>
// PortAudio音频库能调用电脑 / 设备的麦克风，把你说的话转换成 “原始音频数据”（PCM）
//libopus音频编解码库能把PCM数据压缩成更小的Opus格式数据，方便网络传输；也能把收到的Opus数据解码还原成PCM数据，供播放设备播放

#include <unistd.h>
#include <fcntl.h>
#include <cstdio>

// 定义一个 RAII 风格的静音器，生命周期结束时自动恢复日志
// 注意：它通过重定向进程级的 `stderr`（文件描述符 2）来抑制输出，
// 因此会影响同一进程内所有线程。只在短时间、初始化或打开流等
// 可能产生噪声的关键段落使用，避免在实时回调中使用。
class StderrSilencer {
public:
    StderrSilencer() {
        // 1. 刷新缓冲区，防止丢失之前的日志
        fflush(stderr);
        // 2. 备份当前的 stderr 文件描述符 (2)
        saved_stderr_fd_ = dup(STDERR_FILENO);
        // 3. 打开 /dev/null
        int dev_null = open("/dev/null", O_WRONLY);
        // 4. 将 stderr 重定向到 /dev/null
        dup2(dev_null, STDERR_FILENO);
        close(dev_null);
    }

    ~StderrSilencer() {
        // 1. 刷新缓冲区
        fflush(stderr);
        // 2. 恢复 stderr
        dup2(saved_stderr_fd_, STDERR_FILENO);
        close(saved_stderr_fd_);
    }

private:
    int saved_stderr_fd_;
};

AudioProcess::AudioProcess(int sample_rate, int channels, int frame_duration_ms) 
    : sample_rate(sample_rate), 
      channels(channels), 
      frame_duration_ms(frame_duration_ms),
      encoder(nullptr), 
      decoder(nullptr), 
      isRecording(false), 
      recordStream(nullptr),
      isPlaying(false),
      playbackStream(nullptr) {
        if (!initializeOpus()) {
            USER_LOG_ERROR("Failed to initialize Opus encoder/decoder.");
        }
}

AudioProcess::~AudioProcess() {
    cleanupOpus();
    clearRecordedAudioQueue();
    clearPlaybackAudioQueue();
    if (isRecording) {
        stopRecording();
    }
    if (isPlaying) {
        stopPlaying();
    }
}

bool AudioProcess::initializeOpus() {
    int error;

    encoder = opus_encoder_create(sample_rate, channels, OPUS_APPLICATION_VOIP, &error);
    if (error != OPUS_OK) {
        USER_LOG_ERROR("Opus encoder initialization failed: %s", opus_strerror(error));
        return false;
    }

    decoder = opus_decoder_create(sample_rate, channels, &error);
    if (error != OPUS_OK) {
        USER_LOG_ERROR("Opus decoder initialization failed: %s", opus_strerror(error));
        opus_encoder_destroy(encoder);
        return false;
    }
    return true;
}

void AudioProcess::cleanupOpus() {
    if (encoder) {
        opus_encoder_destroy(encoder);
    }
    if (decoder) {
        opus_decoder_destroy(decoder);
    }
}

bool AudioProcess::startRecording() {

    if (isRecording) {
        USER_LOG_WARN("Already recording. Cannot start again.");
        return false;
    }

    PaError err;

    // Suppress noisy ALSA/Pulse/JACK messages during PortAudio initialization
    // Use RAII-style StderrSilencer to minimize transient stderr spam.
    {
        StderrSilencer silencer;
        err = Pa_Initialize();
        if (err != paNoError) {
            USER_LOG_ERROR("PortAudio error: %s", Pa_GetErrorText(err));
            return false;
        }
    }

    PaStreamParameters inputParameters;
    inputParameters.device = Pa_GetDefaultInputDevice();
    if (inputParameters.device == paNoDevice) {
        USER_LOG_ERROR("No default input device found.");
        Pa_Terminate();
        return false;
    }
    inputParameters.channelCount = channels;
    inputParameters.sampleFormat = paInt16;
    inputParameters.suggestedLatency = Pa_GetDeviceInfo(inputParameters.device)->defaultLowInputLatency;
    inputParameters.hostApiSpecificStreamInfo = nullptr;

    // Silence warnings while opening/starting the stream that may come
    // from underlying ALSA/Pulse/JACK backends (we still surface errors).
    {
        StderrSilencer silencer;
        err = Pa_OpenStream(&recordStream,
                            &inputParameters,
                            nullptr,
                            sample_rate,
                            sample_rate / 1000 * frame_duration_ms,
                            paClipOff,
                            recordCallback,
                            this);
        if (err != paNoError) {
            USER_LOG_ERROR("Error opening recordStream: %s", Pa_GetErrorText(err));
            Pa_Terminate();
            return false;
        }

        err = Pa_StartStream(recordStream);
        if (err != paNoError) {
            USER_LOG_ERROR("Error starting recordStream: %s", Pa_GetErrorText(err));
            Pa_CloseStream(recordStream);
            Pa_Terminate();
            return false;
        }
    }

    isRecording = true;
    USER_LOG_INFO("Recording started.");
    return true;
}

bool AudioProcess::stopRecording() {

    if (!isRecording) {
        USER_LOG_WARN("Not recording. Nothing to stop.");
        return false;
    }

    PaError err;

    err = Pa_StopStream(recordStream);
    if (err != paNoError) {
        USER_LOG_ERROR("Error stopping recordStream: %s", Pa_GetErrorText(err));
        return false;
    }

    err = Pa_CloseStream(recordStream);
    if (err != paNoError) {
        USER_LOG_ERROR("Error closing recordStream: %s", Pa_GetErrorText(err));
        return false;
    }

    Pa_Terminate();

    isRecording = false;
    USER_LOG_INFO("Recording stopped.");
    return true;
}

bool AudioProcess::getRecordedAudio(std::vector<int16_t>& recordedData) {
    std::unique_lock<std::mutex> lock(recordedAudioMutex);
    recordedAudioCV.wait(lock, [this] { return !recordedAudioQueue.empty() || !isRecording; });

    if (recordedAudioQueue.empty()) {
        return false; // 队列为空且不再录音
    }

    recordedData.swap(recordedAudioQueue.front());
    recordedAudioQueue.pop();
    return true;
}

void AudioProcess::clearRecordedAudioQueue() {
    std::lock_guard<std::mutex> lock(recordedAudioMutex);
    std::queue<std::vector<int16_t>> empty;
    std::swap(recordedAudioQueue, empty);
}

//录音线程
int AudioProcess::recordCallback(const void *inputBuffer, void *outputBuffer,
                                 unsigned long framesPerBuffer,
                                 const PaStreamCallbackTimeInfo* timeInfo,
                                 PaStreamCallbackFlags statusFlags,
                                 void *userData) {
    (void) outputBuffer;
    (void) timeInfo;
    (void) statusFlags;

    // Pin PortAudio record thread once (if env provided)
    {
        thread_local bool pinned = false;
        if (!pinned) {
            if (const char* s = std::getenv("AICHAT_AUDIO_CORES")) {
                if (*s) set_current_thread_affinity(s);
            }
            pinned = true;
        }
    }

    AudioProcess* audioProcess = static_cast<AudioProcess*>(userData);
    const int16_t* input = static_cast<const int16_t*>(inputBuffer);

    std::vector<int16_t> frame(framesPerBuffer * audioProcess->channels);
    std::copy(input, input + framesPerBuffer * audioProcess->channels, frame.begin());

    {   
        std::lock_guard<std::mutex> lock(audioProcess->recordedAudioMutex);

        if (audioProcess->recordedAudioQueue.size() >= 750) {
            audioProcess->recordedAudioQueue.pop();
        }

        audioProcess->recordedAudioQueue.push(frame);
    }
    audioProcess->recordedAudioCV.notify_one();

    return paContinue;
}

bool AudioProcess::startPlaying() {
    if (isPlaying) {
        USER_LOG_WARN("Already playing. Cannot start again.");
        return false;
    }

    PaError err;

    // Suppress noisy ALSA/Pulse/JACK messages during PortAudio initialization
    {
        StderrSilencer silencer;
        err = Pa_Initialize();
        if (err != paNoError) {
            USER_LOG_ERROR("PortAudio error: %s", Pa_GetErrorText(err));
            return false;
        }
    }

    PaStreamParameters outputParameters;
    outputParameters.device = Pa_GetDefaultOutputDevice();
    if (outputParameters.device == paNoDevice) {
        USER_LOG_ERROR("No default output device found.");
        Pa_Terminate();
        return false;
    }
    outputParameters.channelCount = channels;
    outputParameters.sampleFormat = paInt16;
    outputParameters.suggestedLatency = Pa_GetDeviceInfo(outputParameters.device)->defaultLowOutputLatency;
    outputParameters.hostApiSpecificStreamInfo = nullptr;

    // Silence warnings while opening/starting the stream that may come
    // from underlying ALSA/Pulse/JACK backends.
    {
        StderrSilencer silencer;
        err = Pa_OpenStream(&playbackStream,
                            nullptr,
                            &outputParameters,
                            sample_rate,
                            sample_rate / 1000 * frame_duration_ms,
                            paClipOff,
                            playCallback,
                            this);
        if (err != paNoError) {
            USER_LOG_ERROR("Error opening playbackStream: %s", Pa_GetErrorText(err));
            Pa_Terminate();
            return false;
        }

        err = Pa_StartStream(playbackStream);
        if (err != paNoError) {
            USER_LOG_ERROR("Error starting playbackStream: %s", Pa_GetErrorText(err));
            Pa_CloseStream(playbackStream);
            Pa_Terminate();
            return false;
        }
    }

    isPlaying = true;
    USER_LOG_INFO("Playback started.");
    return true;
}

bool AudioProcess::stopPlaying() {
    if (!isPlaying) {
        USER_LOG_WARN("Not playing. Nothing to stop.");
        return false;
    }

    PaError err;

    err = Pa_StopStream(playbackStream);
    if (err != paNoError) {
        USER_LOG_ERROR("Error stopping playbackStream: %s", Pa_GetErrorText(err));
        return false;
    }

    err = Pa_CloseStream(playbackStream);
    if (err != paNoError) {
        USER_LOG_ERROR("Error closing playbackStream: %s", Pa_GetErrorText(err));
        return false;
    }

    Pa_Terminate();

    isPlaying = false;
    USER_LOG_INFO("Playback stopped.");
    return true;
}

//播放线程
int AudioProcess::playCallback(const void *inputBuffer, void *outputBuffer,
                               unsigned long framesPerBuffer,
                               const PaStreamCallbackTimeInfo* timeInfo,
                               PaStreamCallbackFlags statusFlags,
                               void *userData) {
    (void) inputBuffer;
    (void) timeInfo;
    (void) statusFlags;

    // Pin PortAudio playback thread once (if env provided)
    {
        thread_local bool pinned = false;
        if (!pinned) {
            if (const char* s = std::getenv("AICHAT_AUDIO_CORES")) {
                if (*s) set_current_thread_affinity(s);
            }
            pinned = true;
        }
    }

    AudioProcess* audioProcess = static_cast<AudioProcess*>(userData);
    int16_t* output = static_cast<int16_t*>(outputBuffer);

    std::lock_guard<std::mutex> lock(audioProcess->playbackMutex);

    if (audioProcess->playbackQueue.empty()) {
        std::fill(output, output + framesPerBuffer * audioProcess->channels, 0);
        return paContinue;
    }

    std::vector<int16_t>& currentFrame = audioProcess->playbackQueue.front();
    size_t samplesToCopy = std::min(static_cast<size_t>(framesPerBuffer * audioProcess->channels), currentFrame.size());

    std::copy(currentFrame.begin(), currentFrame.begin() + samplesToCopy, output);

    if (samplesToCopy < framesPerBuffer * audioProcess->channels) {
        std::fill(output + samplesToCopy, output + framesPerBuffer * audioProcess->channels, 0);
    }

    if (samplesToCopy == currentFrame.size()) {
        audioProcess->playbackQueue.pop();
    } else {
        audioProcess->playbackQueue.front().erase(audioProcess->playbackQueue.front().begin(), audioProcess->playbackQueue.front().begin() + samplesToCopy);
    }

    return paContinue;
}

void AudioProcess::clearPlaybackAudioQueue() {
    std::lock_guard<std::mutex> lock(playbackMutex);
    std::queue<std::vector<int16_t>> empty;
    std::swap(playbackQueue, empty);
}

void AudioProcess::addFrameToPlaybackQueue(const std::vector<int16_t>& pcm_frame) {
    std::lock_guard<std::mutex> lock(playbackMutex);
    
    int frame_size = sample_rate / 1000 * frame_duration_ms;

    if (pcm_frame.size() < static_cast<size_t>(frame_size)) {
        auto tempFrame = pcm_frame;
        tempFrame.resize(frame_size, 0);
        playbackQueue.push(tempFrame);
    } else {
        playbackQueue.push(pcm_frame);
    }
}

std::queue<std::vector<int16_t>> AudioProcess::loadAudioFromFile(const std::string& filename, int frame_duration_ms) {
    std::ifstream infile(filename, std::ios::binary);
    if (!infile) {
        USER_LOG_ERROR("Failed to open file: %s", filename.c_str());
        return {};
    }

    infile.seekg(0, std::ios::end);
    std::streampos fileSize = infile.tellg();
    infile.seekg(0, std::ios::beg);

    size_t numSamples = static_cast<size_t>(fileSize) / sizeof(int16_t);

    std::vector<int16_t> audio_data(numSamples);
    infile.read(reinterpret_cast<char*>(audio_data.data()), fileSize);

    if (!infile) {
        USER_LOG_ERROR("Error reading file: %s", filename.c_str());
        return {};
    }

    int frame_size = sample_rate / 1000 * frame_duration_ms;

    std::queue<std::vector<int16_t>> audio_frames;
    for (size_t i = 0; i < numSamples; i += frame_size) {
        size_t remaining_samples = numSamples - i;
        size_t current_frame_size = (remaining_samples > frame_size) ? frame_size : remaining_samples;

        std::vector<int16_t> frame(current_frame_size);
        std::copy(audio_data.begin() + i, audio_data.begin() + i + current_frame_size, frame.begin());
        audio_frames.push(frame);
    }

    return audio_frames;
}


void AudioProcess::saveToPCMFile(const std::string& filename, const std::queue<std::vector<int16_t>>& audioQueue) {
    std::ofstream file(filename, std::ios::binary);
    if (!file) {
        USER_LOG_ERROR("Failed to open file: %s", filename.c_str());
        return;
    }

    {
        std::queue<std::vector<int16_t>> tempQueue = audioQueue;
        while (!tempQueue.empty()) {
            const std::vector<int16_t>& frame = tempQueue.front();
            file.write(reinterpret_cast<const char*>(frame.data()), frame.size() * sizeof(int16_t));
            tempQueue.pop();
        }
    }

    file.close();
    USER_LOG_INFO("Saved recording to %s", filename.c_str());
}

void AudioProcess::saveToPCMFile(const std::string& filename) {
    std::unique_lock<std::mutex> lock(recordedAudioMutex);
    saveToPCMFile(filename, recordedAudioQueue);
}

bool AudioProcess::encode(const std::vector<int16_t>& pcm_frame, uint8_t* opus_data, size_t& opus_data_size) {
    if (!encoder) {
        USER_LOG_ERROR("Encoder not initialized");
        return false;
    }

    int frame_size = pcm_frame.size();

    if (frame_size <= 0) {
        USER_LOG_ERROR("Invalid PCM frame size: %d", frame_size);
        return false;
    }

    // 对当前帧进行编码
    int encoded_bytes_size = opus_encode(encoder, pcm_frame.data(), frame_size, opus_data, 2048); // max 2048 bytes

    if (encoded_bytes_size < 0) {
        USER_LOG_ERROR("Encoding failed: %s", opus_strerror(encoded_bytes_size));
        return false;
    }

    opus_data_size = static_cast<size_t>(encoded_bytes_size);
    return true;
}

bool AudioProcess::decode(const uint8_t* opus_data, size_t opus_data_size, std::vector<int16_t>& pcm_frame) {
    if (!decoder) {
        USER_LOG_ERROR("Decoder not initialized");
        return false;
    }

    int frame_size = 960;  // 40ms 帧, 16000Hz 采样率, 理论上应该是 640 个样本，但是 Opus 限制为 960
    pcm_frame.resize(frame_size * channels);

    // 对当前帧进行解码
    int decoded_samples = opus_decode(decoder, opus_data, static_cast<int>(opus_data_size), pcm_frame.data(), frame_size, 0);

    if (decoded_samples < 0) {
        USER_LOG_ERROR("Decoding failed: %s", opus_strerror(decoded_samples));
        return false;
    }

    pcm_frame.resize(decoded_samples * channels);
    return true;
}

BinProtocol* AudioProcess::PackBinFrame(const uint8_t* payload, size_t payload_size, int ws_protocol_version) {
    auto pack = (BinProtocol*)malloc(sizeof(BinProtocol) + payload_size);
    if (!pack) {
        USER_LOG_ERROR("Memory allocation failed");
        return nullptr;
    }

    pack->version = htons(ws_protocol_version);
    pack->type = htons(0);  // Indicate audio data type
    pack->payload_size = htonl(payload_size);
    assert(sizeof(BinProtocol) == 8);

    memcpy(pack->payload, payload, payload_size);

    return pack;
}

bool AudioProcess::UnpackBinFrame(const uint8_t* packed_data, size_t packed_data_size, BinProtocolInfo& protocol_info, std::vector<uint8_t>& opus_data) {
    if (packed_data_size < sizeof(uint16_t) * 2 + sizeof(uint32_t)) { // 至少需要2字节版本+2字节类型+4字节负载大小
        USER_LOG_ERROR("Packed data size is too small");
        return false;
    }

    const uint16_t* version_ptr = reinterpret_cast<const uint16_t*>(packed_data);
    const uint16_t* type_ptr = reinterpret_cast<const uint16_t*>(packed_data + sizeof(uint16_t));
    const uint32_t* payload_size_ptr = reinterpret_cast<const uint32_t*>(packed_data + sizeof(uint16_t) * 2);

    uint16_t version = ntohs(*version_ptr);
    uint16_t type = ntohs(*type_ptr);
    uint32_t payload_size = ntohl(*payload_size_ptr);

    if (packed_data_size < sizeof(uint16_t) * 2 + sizeof(uint32_t) + payload_size) {
        USER_LOG_ERROR("Packed data size does not match payload size");
        return false;
    }

    protocol_info.version = version;
    protocol_info.type = type;

    opus_data.clear();
    opus_data.insert(opus_data.end(), packed_data + sizeof(uint16_t) * 2 + sizeof(uint32_t), 
                     packed_data + sizeof(uint16_t) * 2 + sizeof(uint32_t) + payload_size);

    return true;
}