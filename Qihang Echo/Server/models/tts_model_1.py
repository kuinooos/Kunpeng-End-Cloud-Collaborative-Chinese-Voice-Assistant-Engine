from __future__ import annotations

import json
import os
import subprocess
from typing import Optional

import numpy as np

from config.settings import global_settings
from tools.logger import logger

class TTSModel:
    def __init__(self):
        self.callbacks = {}

        # Piper voice metadata cache
        self._piper_src_sample_rate: Optional[int] = None

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

        engine = getattr(global_settings, "TTS_ENGINE", "piper")
        engine = (engine or "piper").strip().lower()
        
        try:
            if self.callbacks.get("on_open"):
                self.callbacks["on_open"]()

            if engine == "piper":
                audio_data = self._tts_piper(text)
                if audio_data and self.callbacks.get("on_data"):
                    self.callbacks["on_data"](audio_data)
                if self.callbacks.get("on_complete"):
                    self.callbacks["on_complete"]()
                return

            if engine == "dashscope":
                audio_data = self._tts_dashscope(text)
                if audio_data and self.callbacks.get("on_data"):
                    self.callbacks["on_data"](audio_data)
                if self.callbacks.get("on_complete"):
                    self.callbacks["on_complete"]()
                return

            raise ValueError(f"Unknown TTS_ENGINE: {engine}")

        except Exception as e:
            logger.error(f"TTS Exception: {e}")
            if self.callbacks.get("on_error"):
                self.callbacks["on_error"](str(e))

    def _detect_piper_sample_rate(self, model_path: str) -> Optional[int]:
        if not model_path:
            return None
        candidates = []
        if model_path.endswith(".onnx") and os.path.exists(model_path + ".json"):
            candidates.append(model_path + ".json")
        base, _ = os.path.splitext(model_path)
        if os.path.exists(base + ".json"):
            candidates.append(base + ".json")
        # also check sibling json
        sibling_json = model_path + ".onnx.json"
        if os.path.exists(sibling_json):
            candidates.append(sibling_json)

        for p in candidates:
            try:
                with open(p, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                # common keys in piper voice json
                for key_path in (
                    ("audio", "sample_rate"),
                    ("inference", "sample_rate"),
                    ("sample_rate",),
                ):
                    cur = meta
                    ok = True
                    for k in key_path:
                        if isinstance(cur, dict) and k in cur:
                            cur = cur[k]
                        else:
                            ok = False
                            break
                    if ok:
                        sr = int(cur)
                        if sr > 0:
                            return sr
            except Exception:
                continue
        return None

    def _resample_int16_mono(self, pcm_bytes: bytes, src_rate: int, dst_rate: int) -> bytes:
        if not pcm_bytes or src_rate == dst_rate:
            return pcm_bytes
        x = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32)
        if x.size == 0:
            return b""
        new_len = int(round(x.size * float(dst_rate) / float(src_rate)))
        if new_len <= 0:
            return b""
        # linear interpolation
        xp = np.linspace(0.0, 1.0, num=x.size, endpoint=False)
        fp = x
        x_new = np.linspace(0.0, 1.0, num=new_len, endpoint=False)
        y = np.interp(x_new, xp, fp)
        y = np.clip(np.round(y), -32768, 32767).astype(np.int16)
        return y.tobytes()

    def _tts_piper(self, text: str) -> bytes:
        piper_bin = str(getattr(global_settings, "LOCAL_TTS_PIPER_BIN", "piper"))
        model_path = str(getattr(global_settings, "LOCAL_TTS_MODEL_PATH", ""))
        speaker = getattr(global_settings, "LOCAL_TTS_SPEAKER", None)
        target_sr = int(getattr(global_settings, "LOCAL_TTS_OUTPUT_SAMPLE_RATE", 16000))

        if not model_path:
            raise RuntimeError("TTS_ENGINE=piper 但未配置 LOCAL_TTS_MODEL_PATH")

        if self._piper_src_sample_rate is None:
            self._piper_src_sample_rate = self._detect_piper_sample_rate(model_path)

        cmd = [piper_bin, "--model", model_path, "--output_raw"]
        if speaker is not None:
            cmd += ["--speaker", str(speaker)]

        try:
            proc = subprocess.run(
                cmd,
                input=(text + "\n").encode("utf-8"),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
        except FileNotFoundError as e:
            raise FileNotFoundError(
                f"找不到 piper 可执行文件: {piper_bin}。请安装 piper 或设置 LOCAL_TTS_PIPER_BIN 为绝对路径。"
            ) from e

        if proc.returncode != 0:
            err = proc.stderr.decode("utf-8", errors="ignore")
            raise RuntimeError(f"piper 运行失败 (code={proc.returncode}): {err}")

        pcm = proc.stdout or b""

        src_sr = self._piper_src_sample_rate
        if src_sr and src_sr != target_sr:
            pcm = self._resample_int16_mono(pcm, src_sr, target_sr)

        return pcm

    def _tts_dashscope(self, text: str) -> bytes:
        try:
            from dashscope.audio.tts import SpeechSynthesizer  # type: ignore
        except Exception as e:
            raise ModuleNotFoundError("TTS_ENGINE=dashscope 但未安装 dashscope") from e

        response = SpeechSynthesizer.call(
            model='sambert-zhijia-v1',
            text=text,
            sample_rate=16000,
            format='pcm',
        )

        audio_data = None
        try:
            audio_data = response.get_audio_data()
        except Exception as e:
            logger.warning(f"get_audio_data failed: {e}, trying alternative method")
            if hasattr(response, 'audio_data'):
                audio_data = response.audio_data
            elif hasattr(response, 'output') and hasattr(response.output, 'audio'):
                audio_data = response.output.audio

        if audio_data:
            return audio_data

        err_msg = None
        if hasattr(response, 'message'):
            err_msg = getattr(response, 'message')
        elif hasattr(response, 'error'):
            err_msg = getattr(response, 'error')
        elif hasattr(response, 'code'):
            err_msg = f"code={getattr(response, 'code')}"
        else:
            err_msg = str(response)
        raise RuntimeError(f"DashScope TTS Failed: {err_msg}")

