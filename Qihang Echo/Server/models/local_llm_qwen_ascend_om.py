"""Local Qwen2.5-* chat inference on Ascend NPU via ACL (.om).

This module is adapted from the validated PoC script in:
- llm_ascend_poc/scripts/chat_qwen.py

Design goals for Server integration:
- Keep dependencies optional (acl/transformers only required when enabled).
- Provide a simple engine that consumes `messages` (OpenAI-like) and returns text.
- Be safe for multi-thread usage via a global singleton + lock.

Notes:
- Several tensor shapes (KV cache, vocab size) are model-specific.
  They must match the exported OM.
"""

from __future__ import annotations

from dataclasses import dataclass
import atexit
import threading
import time
from typing import Iterable, Iterator, List, Dict, Optional

import numpy as np

from tools.logger import logger


@dataclass(frozen=True)
class LocalQwenOmConfig:
    device_id: int
    model_om_path: str
    tokenizer_path: str
    max_seq_len: int = 1024

    # Model-specific constants (must match your exported OM)
    vocab_size: int = 151936
    kv_num_layers: int = 96
    kv_head_dim: int = 64

    # Sampling
    temperature: float = 0.8
    top_p: float = 0.95
    top_k: int = 50
    repetition_penalty: float = 1.2
    min_new_tokens: int = 12
    no_repeat_ngram: int = 3

    max_new_tokens_default: int = 256


class _AclError(RuntimeError):
    pass


def _check_ret(ret: int, message: str) -> None:
    if ret != 0:
        raise _AclError(f"{message} failed ret={ret}")


class LocalQwenOmEngine:
    """A single loaded OM + tokenizer + device-side KV cache."""

    def __init__(self, cfg: LocalQwenOmConfig):
        self.cfg = cfg
        self._lock = threading.Lock()

        self._acl = None
        self._tokenizer = None

        # ACL resources
        self._context = None
        self._model_id = None
        self._model_desc = None

        # KV cache on device
        self._kv_cache_dev_ptr = None
        self._kv_cache_size = (
            1
            * cfg.max_seq_len
            * cfg.kv_num_layers
            * cfg.kv_head_dim
            * 2  # fp16 bytes
        )
        self._current_pos = 0

        self._initialized = False

    def ensure_initialized(self) -> None:
        if self._initialized:
            return
        with self._lock:
            if self._initialized:
                return
            self._init_acl()
            self._load_model()
            self._load_tokenizer()
            self._initialized = True
            atexit.register(self.release)

    def _import_acl(self):
        try:
            import acl  # type: ignore

            return acl
        except Exception as e:
            raise ModuleNotFoundError(
                "未找到 Ascend ACL Python 包(acl)。请确认已安装/配置 CANN，并且当前 Python 环境可 `import acl`。"
            ) from e

    def _init_acl(self) -> None:
        acl = self._import_acl()
        self._acl = acl

        ret = acl.init()
        _check_ret(ret, "acl.init")
        ret = acl.rt.set_device(self.cfg.device_id)
        _check_ret(ret, "acl.rt.set_device")
        self._context, ret = acl.rt.create_context(self.cfg.device_id)
        _check_ret(ret, "acl.rt.create_context")
        logger.info("✅ ACL initialized")

    def _load_model(self) -> None:
        acl = self._acl
        if acl is None:
            raise _AclError("ACL not initialized")

        self._model_id, ret = acl.mdl.load_from_file(self.cfg.model_om_path)
        _check_ret(ret, "acl.mdl.load_from_file")

        self._model_desc = acl.mdl.create_desc()
        ret = acl.mdl.get_desc(self._model_desc, self._model_id)
        _check_ret(ret, "acl.mdl.get_desc")

        self._kv_cache_dev_ptr, ret = acl.rt.malloc(self._kv_cache_size, 2)  # ACL_MEM_MALLOC_HUGE_FIRST
        _check_ret(ret, "acl.rt.malloc(kv_cache)")

        ret = acl.rt.memset(self._kv_cache_dev_ptr, self._kv_cache_size, 0, self._kv_cache_size)
        _check_ret(ret, "acl.rt.memset(kv_cache)")

        logger.info("✅ OM model loaded + device KV cache allocated")

    def _load_tokenizer(self) -> None:
        try:
            from transformers import AutoTokenizer  # type: ignore
        except Exception as e:
            raise ModuleNotFoundError(
                "缺少 transformers。请安装：pip install transformers"
            ) from e

        self._tokenizer = AutoTokenizer.from_pretrained(self.cfg.tokenizer_path, trust_remote_code=True)
        logger.info("✅ Tokenizer loaded")

    def _reset_kv_cache(self) -> None:
        acl = self._acl
        if acl is None or self._kv_cache_dev_ptr is None:
            raise _AclError("KV cache not ready")
        ret = acl.rt.memset(self._kv_cache_dev_ptr, self._kv_cache_size, 0, self._kv_cache_size)
        _check_ret(ret, "acl.rt.memset(reset kv cache)")
        self._current_pos = 0

    def _create_input_dataset(self, input_id: int, attention_mask: np.ndarray, position_id: int):
        acl = self._acl
        if acl is None:
            raise _AclError("ACL not initialized")

        dataset = acl.mdl.create_dataset()
        keep_alive: list[bytes] = []

        # Input 0: input_ids [1, 1] int64
        input_id_arr = np.array([[input_id]], dtype=np.int64)
        input_bytes = input_id_arr.tobytes()
        keep_alive.append(input_bytes)
        ptr = acl.util.bytes_to_ptr(input_bytes)
        buf = acl.create_data_buffer(ptr, input_id_arr.nbytes)
        acl.mdl.add_dataset_buffer(dataset, buf)

        # Input 1: attention_mask [1, max_seq_len+1] int64
        mask_arr = attention_mask.astype(np.int64)
        if not mask_arr.flags["C_CONTIGUOUS"]:
            mask_arr = np.ascontiguousarray(mask_arr)
        mask_bytes = mask_arr.tobytes()
        keep_alive.append(mask_bytes)
        ptr = acl.util.bytes_to_ptr(mask_bytes)
        buf = acl.create_data_buffer(ptr, mask_arr.nbytes)
        acl.mdl.add_dataset_buffer(dataset, buf)

        # Input 2: position_ids [1, 1] int64
        pos_arr = np.array([[position_id]], dtype=np.int64)
        pos_bytes = pos_arr.tobytes()
        keep_alive.append(pos_bytes)
        ptr = acl.util.bytes_to_ptr(pos_bytes)
        buf = acl.create_data_buffer(ptr, pos_arr.nbytes)
        acl.mdl.add_dataset_buffer(dataset, buf)

        # Input 3: kv_cache fp16 - device pointer
        if self._kv_cache_dev_ptr is None:
            raise _AclError("KV cache not allocated")
        buf = acl.create_data_buffer(self._kv_cache_dev_ptr, self._kv_cache_size)
        acl.mdl.add_dataset_buffer(dataset, buf)

        return dataset, keep_alive

    def _create_output_dataset(self):
        acl = self._acl
        if acl is None or self._model_desc is None:
            raise _AclError("ACL/model desc not ready")

        dataset = acl.mdl.create_dataset()
        output_ptrs: list[int] = []

        for i in range(2):
            size = acl.mdl.get_output_size_by_index(self._model_desc, i)
            ptr, ret = acl.rt.malloc(size, 2)
            _check_ret(ret, f"acl.rt.malloc(output {i})")
            buf = acl.create_data_buffer(ptr, size)
            acl.mdl.add_dataset_buffer(dataset, buf)
            output_ptrs.append(ptr)

        return dataset, output_ptrs

    def _dev_to_host(self, dev_ptr: int, shape: tuple[int, ...], dtype: np.dtype):
        acl = self._acl
        if acl is None:
            raise _AclError("ACL not initialized")

        size = int(np.prod(shape) * np.dtype(dtype).itemsize)
        host_ptr, ret = acl.rt.malloc_host(size)
        _check_ret(ret, "acl.rt.malloc_host")
        ret = acl.rt.memcpy(host_ptr, size, dev_ptr, size, 2)  # DEVICE_TO_HOST
        _check_ret(ret, "acl.rt.memcpy(D2H)")

        data_bytes = acl.util.ptr_to_bytes(host_ptr, size)
        data_np = np.frombuffer(data_bytes, dtype=dtype).reshape(shape).copy()
        acl.rt.free_host(host_ptr)
        return data_np

    def _forward_one(self, token_id: int) -> np.ndarray:
        """One-step inference. Returns logits (vocab_size,) float32."""
        acl = self._acl
        if acl is None or self._model_id is None:
            raise _AclError("Model not ready")

        # attention_mask [1, max_seq_len+1]
        attention_mask = np.ones((1, self.cfg.max_seq_len + 1), dtype=np.int64)
        if self._current_pos < self.cfg.max_seq_len:
            attention_mask[0, self._current_pos : self.cfg.max_seq_len] = 0

        input_dataset, keep_alive = self._create_input_dataset(token_id, attention_mask, self._current_pos)
        output_dataset, output_ptrs = self._create_output_dataset()

        ret = acl.mdl.execute(self._model_id, input_dataset, output_dataset)
        _check_ret(ret, "acl.mdl.execute")

        logits = self._dev_to_host(output_ptrs[0], (1, 1, self.cfg.vocab_size), np.float32)

        # update kv cache from output[1]
        if self._kv_cache_dev_ptr is None:
            raise _AclError("KV cache not allocated")

        offset = self._current_pos * self.cfg.kv_num_layers * self.cfg.kv_head_dim * 2
        new_kv_size = 1 * 1 * self.cfg.kv_num_layers * self.cfg.kv_head_dim * 2

        if self._current_pos < self.cfg.max_seq_len:
            ret = acl.rt.memcpy(
                self._kv_cache_dev_ptr + offset,
                new_kv_size,
                output_ptrs[1],
                new_kv_size,
                4,  # DEVICE_TO_DEVICE
            )
            _check_ret(ret, "acl.rt.memcpy(update kv cache)")

        self._current_pos += 1

        for ptr in output_ptrs:
            acl.rt.free(ptr)
        acl.mdl.destroy_dataset(output_dataset)
        acl.mdl.destroy_dataset(input_dataset)
        del keep_alive

        return logits[0, 0, :]

    def _apply_no_repeat_ngram(self, logits: np.ndarray, generated: List[int], n: int) -> np.ndarray:
        if n <= 1:
            return logits
        if len(generated) < n - 1:
            return logits
        prefix = tuple(generated[-(n - 1) :])
        banned: set[int] = set()
        for i in range(len(generated) - n + 1):
            key = tuple(generated[i : i + n - 1])
            nxt = int(generated[i + n - 1])
            if key == prefix:
                banned.add(nxt)
        if banned:
            logits[list(banned)] = -1e10
        return logits

    def _sample_token(self, logits: np.ndarray, generated: List[int], eos_id: int) -> int:
        # early block EOS
        if len(generated) < self.cfg.min_new_tokens:
            logits[eos_id] = -1e10

        logits = self._apply_no_repeat_ngram(logits, generated, self.cfg.no_repeat_ngram)

        if generated and self.cfg.repetition_penalty and self.cfg.repetition_penalty > 1.0:
            for t in set(generated[-80:]):
                t = int(t)
                if logits[t] > 0:
                    logits[t] /= self.cfg.repetition_penalty
                else:
                    logits[t] *= self.cfg.repetition_penalty

        if self.cfg.temperature <= 0:
            return int(np.argmax(logits))

        logits = logits / float(self.cfg.temperature)

        k = int(min(self.cfg.top_k, logits.shape[0]))
        topk_idx = np.argpartition(logits, -k)[-k:]
        topk_logits = logits[topk_idx]

        exp_logits = np.exp(topk_logits - np.max(topk_logits))
        probs = exp_logits / np.sum(exp_logits)

        order = np.argsort(probs)[::-1]
        sorted_idx = topk_idx[order]
        sorted_probs = probs[order]
        cumsum = np.cumsum(sorted_probs)
        cutoff = int(np.searchsorted(cumsum, self.cfg.top_p))
        cutoff = max(1, cutoff)

        cand_idx = sorted_idx[:cutoff]
        cand_probs = sorted_probs[:cutoff]
        cand_probs = cand_probs / np.sum(cand_probs)

        return int(np.random.choice(cand_idx, p=cand_probs))

    def _messages_to_prompt_text(self, messages: List[Dict[str, str]]) -> str:
        if self._tokenizer is None:
            raise RuntimeError("Tokenizer not loaded")

        # Prefer tokenizer chat template when available
        try:
            return self._tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True,
            )
        except Exception:
            # Fallback: naive concat
            parts: list[str] = []
            for m in messages:
                role = m.get("role", "user")
                content = m.get("content", "")
                parts.append(f"[{role}] {content}")
            parts.append("[assistant]")
            return "\n".join(parts)

    def generate_text(self, messages: List[Dict[str, str]], max_new_tokens: Optional[int] = None) -> str:
        return "".join(self.generate_stream(messages, max_new_tokens=max_new_tokens))

    def generate_stream(self, messages: List[Dict[str, str]], max_new_tokens: Optional[int] = None) -> Iterator[str]:
        self.ensure_initialized()
        if self._tokenizer is None:
            raise RuntimeError("Tokenizer not loaded")

        max_new_tokens = max_new_tokens or self.cfg.max_new_tokens_default

        with self._lock:
            self._reset_kv_cache()

            prompt_text = self._messages_to_prompt_text(messages)
            input_ids: List[int] = list(self._tokenizer.encode(prompt_text))

            # prefill
            logits: Optional[np.ndarray] = None
            prefill_start = time.time()
            for token_id in input_ids:
                if self._current_pos >= self.cfg.max_seq_len:
                    logger.warning("[LocalLLM] reached max_seq_len during prefill")
                    break
                logits = self._forward_one(int(token_id))
            prefill_time = time.time() - prefill_start
            if logits is None:
                return

            eos_id = int(self._tokenizer.eos_token_id)
            generated: List[int] = []

            next_token = self._sample_token(logits.copy(), generated, eos_id)
            decode_start = time.time()

            for _ in range(int(max_new_tokens)):
                if next_token == eos_id:
                    break
                if self._current_pos >= self.cfg.max_seq_len:
                    logger.warning("[LocalLLM] reached max_seq_len during decode")
                    break

                token_str = self._tokenizer.decode([int(next_token)])
                generated.append(int(next_token))
                yield token_str

                logits = self._forward_one(int(next_token))
                next_token = self._sample_token(logits.copy(), generated, eos_id)

            decode_time = time.time() - decode_start
            logger.info(
                f"[LocalLLM] prefill={len(input_ids)} tok in {prefill_time:.2f}s, "
                f"decode={len(generated)} tok in {decode_time:.2f}s"
            )

    def release(self) -> None:
        with self._lock:
            if not self._initialized:
                return
            acl = self._acl
            try:
                if acl is not None and self._kv_cache_dev_ptr:
                    acl.rt.free(self._kv_cache_dev_ptr)
                    self._kv_cache_dev_ptr = None
            except Exception:
                pass

            try:
                if acl is not None and self._model_id:
                    acl.mdl.unload(self._model_id)
                    self._model_id = None
            except Exception:
                pass

            try:
                if acl is not None and self._context:
                    acl.rt.destroy_context(self._context)
                    self._context = None
            except Exception:
                pass

            try:
                if acl is not None:
                    acl.rt.reset_device(self.cfg.device_id)
                    acl.finalize()
            except Exception:
                pass

            self._initialized = False


_GLOBAL_ENGINE: Optional[LocalQwenOmEngine] = None
_GLOBAL_ENGINE_LOCK = threading.Lock()


def get_global_local_qwen_engine(cfg: LocalQwenOmConfig) -> LocalQwenOmEngine:
    global _GLOBAL_ENGINE
    with _GLOBAL_ENGINE_LOCK:
        if _GLOBAL_ENGINE is None:
            _GLOBAL_ENGINE = LocalQwenOmEngine(cfg)
        return _GLOBAL_ENGINE

