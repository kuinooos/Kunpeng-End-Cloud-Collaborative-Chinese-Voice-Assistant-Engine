# 保存为 test/tts_quality_test.py
import os
import wave
import dashscope
from dashscope.audio.tts import SpeechSynthesizer
from config.settings import global_settings

# 优先使用环境变量 DASHSCOPE_API_KEY，若未设置则尝试从项目配置读取。
key = os.environ.get('DASHSCOPE_API_KEY')
if key:
    dashscope.api_key = key
else:
    # Settings 里可能已写入 dashscope.api_key（开发调试用），仅在安全环境下使用。
    try:
        cfg_key = getattr(global_settings, 'dashscope', None) and getattr(global_settings.dashscope, 'api_key', None)
        if cfg_key:
            dashscope.api_key = cfg_key
    except Exception:
        pass

if not getattr(dashscope, 'api_key', None):
    raise RuntimeError("No DashScope API key found. Set DASHSCOPE_API_KEY env var or configure in config/settings.py")


def save_pcm_to_wav(pcm_bytes, path, sample_rate=16000):
    with wave.open(path, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)   # 16-bit
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_bytes)

text = "今天天气怎么样？我想知道一下今天的温度和降雨概率。"

for model in ['sambert-zhichu-v1', 'sambert-zhijia-v1']:
    resp = SpeechSynthesizer.call(model=model, text=text, sample_rate=16000, format='pcm')
    audio = None
    try:
        audio = resp.get_audio_data()
    except Exception:
        print(f"{model}: no audio returned")
    if audio:
        save_pcm_to_wav(audio, f'out_{model}.wav')
        print(f"Saved out_{model}.wav")
