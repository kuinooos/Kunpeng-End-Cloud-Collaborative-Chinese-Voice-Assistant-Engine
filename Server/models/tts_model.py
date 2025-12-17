import dashscope
from dashscope.audio.tts import SpeechSynthesizer
from tools.logger import logger

class TTSModel:
    def __init__(self):
        self.callbacks = {}

    def tts_stream_set(self, on_open=None, on_complete=None, on_error=None, on_close=None, on_data=None):
        """
        设置回调函数
        """
        self.callbacks = {
            "on_open": on_open,
            "on_complete": on_complete,
            "on_error": on_error,
            "on_close": on_close,
            "on_data": on_data
        }

    def tts_stream_close(self):
        """
        关闭流，触发 on_close 回调
        """
        if self.callbacks.get("on_close"):
            self.callbacks["on_close"]()

    def tts_stream_speech_synthesis(self, text):
        """
        执行语音合成
        """
        if not text:
            return
        
        try:
            if self.callbacks.get("on_open"):
                self.callbacks["on_open"]()

            # 使用 sambert-zhijia-v1 (亲切女声) - 更稳定流畅的女声
            # 其他可选女声: sambert-zhiyan-v1 (温柔女声), sambert-zhimei-v1 (知性女声)
            # format='pcm' 返回 16k 16bit 单声道 PCM
            response = SpeechSynthesizer.call(
                model='sambert-zhijia-v1',
                text=text,
                sample_rate=16000,
                format='pcm'
            )
            
            # 兼容不同 SDK 返回：优先尝试 get_audio_data()，并兼容常见的 `code`/`status` 字段
            audio_data = None
            try:
                audio_data = response.get_audio_data()
            except Exception as e:
                # 如果get_audio_data失败，尝试直接从response获取
                logger.warning(f"get_audio_data failed: {e}, trying alternative method")
                if hasattr(response, 'audio_data'):
                    audio_data = response.audio_data
                elif hasattr(response, 'output') and hasattr(response.output, 'audio'):
                    audio_data = response.output.audio

            # 判定是否成功
            success = False
            # 有些 SDK 返回 0 表示成功，有些返回 HTTP-Style 200
            if hasattr(response, 'code'):
                try:
                    success = int(getattr(response, 'code')) in (0, 200)
                except Exception:
                    success = False
            elif hasattr(response, 'status'):
                try:
                    success = int(getattr(response, 'status')) == 200
                except Exception:
                    success = False
            elif hasattr(response, 'status_code'):
                try:
                    success = int(getattr(response, 'status_code')) == 200
                except Exception:
                    success = False
            elif audio_data:
                success = True

            if success:
                if audio_data and self.callbacks.get("on_data"):
                    self.callbacks["on_data"](audio_data)

                # 单次合成完成，触发 on_complete
                if self.callbacks.get("on_complete"):
                    self.callbacks["on_complete"]()
            else:
                # 提取错误信息
                err_msg = None
                if hasattr(response, 'message'):
                    err_msg = getattr(response, 'message')
                elif hasattr(response, 'error'):
                    err_msg = getattr(response, 'error')
                elif hasattr(response, 'code'):
                    err_msg = f"code={getattr(response, 'code')}"
                else:
                    err_msg = str(response)

                logger.error(f"TTS Failed: {err_msg}")
                if self.callbacks.get("on_error"):
                    self.callbacks["on_error"](err_msg)

        except Exception as e:
            logger.error(f"TTS Exception: {e}")
            if self.callbacks.get("on_error"):
                self.callbacks["on_error"](str(e))
