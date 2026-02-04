from __future__ import annotations

from http import HTTPStatus
from typing import Dict, Iterator, List, Optional

from config.settings import global_settings
from tools.logger import logger

from models.local_llm_qwen_ascend_om import LocalQwenOmConfig, get_global_local_qwen_engine

class LLMModel:
    def __init__(self, model_name="qwen-turbo", **kwargs):
        self.model_name = model_name
        self.messages = []
        self.system_content = "You are a helpful assistant."
        self.engine = getattr(global_settings, "LLM_ENGINE", "dashscope")

    def set_model_sys_content(self, content):
        """设置系统提示词"""
        self.system_content = content
        # 如果 messages 为空或者第一条不是 system，则插入
        # 如果第一条是 system，则更新
        if self.messages and self.messages[0]['role'] == 'system':
            self.messages[0]['content'] = content
        else:
            self.messages.insert(0, {'role': 'system', 'content': content})

    def clear_messages(self):
        """清空对话历史，保留系统提示词"""
        self.messages = []
        if self.system_content:
             self.messages.append({'role': 'system', 'content': self.system_content})

    def add_message(self, role, content):
        """添加消息到历史记录"""
        self.messages.append({'role': role, 'content': content})

    def _get_engine_mode(self) -> str:
        # 允许通过 Settings 选择后端："local_ascend_qwen_om" / "dashscope"
        mode = (self.engine or "").strip().lower()
        if not mode:
            mode = "dashscope"
        return mode

    def _build_local_engine(self):
        cfg = LocalQwenOmConfig(
            device_id=int(getattr(global_settings, "LOCAL_LLM_DEVICE_ID", 0)),
            model_om_path=str(getattr(global_settings, "LOCAL_LLM_OM_PATH", "")),
            tokenizer_path=str(getattr(global_settings, "LOCAL_LLM_TOKENIZER_PATH", "")),
            max_seq_len=int(getattr(global_settings, "LOCAL_LLM_MAX_SEQ_LEN", 1024)),
            vocab_size=int(getattr(global_settings, "LOCAL_LLM_VOCAB_SIZE", 151936)),
            kv_num_layers=int(getattr(global_settings, "LOCAL_LLM_KV_NUM_LAYERS", 96)),
            kv_head_dim=int(getattr(global_settings, "LOCAL_LLM_KV_HEAD_DIM", 64)),
            temperature=float(getattr(global_settings, "LOCAL_LLM_TEMPERATURE", 0.8)),
            top_p=float(getattr(global_settings, "LOCAL_LLM_TOP_P", 0.95)),
            top_k=int(getattr(global_settings, "LOCAL_LLM_TOP_K", 50)),
            repetition_penalty=float(getattr(global_settings, "LOCAL_LLM_REPETITION_PENALTY", 1.2)),
            min_new_tokens=int(getattr(global_settings, "LOCAL_LLM_MIN_NEW_TOKENS", 12)),
            no_repeat_ngram=int(getattr(global_settings, "LOCAL_LLM_NO_REPEAT_NGRAM", 3)),
            max_new_tokens_default=int(getattr(global_settings, "LOCAL_LLM_MAX_NEW_TOKENS", 256)),
        )
        if not cfg.model_om_path or not cfg.tokenizer_path:
            raise RuntimeError(
                "已选择本地 LLM，但未配置 LOCAL_LLM_OM_PATH / LOCAL_LLM_TOKENIZER_PATH。"
            )
        return get_global_local_qwen_engine(cfg)

    def _call_dashscope(self, stream: bool, user_input: str) -> Iterator[str] | str:
        try:
            import dashscope  # type: ignore
        except Exception as e:
            raise ModuleNotFoundError(
                "当前 LLM_ENGINE=dashscope 但未安装 dashscope。若要本地运行，请在 settings.py 设置 LLM_ENGINE=local_ascend_qwen_om。"
            ) from e

        if not stream:
            self.add_message('user', user_input)
            try:
                current_key = getattr(dashscope, "api_key", None)
                if current_key:
                    masked_key = current_key[:6] + "*" * 6 + current_key[-4:]
                    logger.info(f"Calling LLM with Key: {masked_key}")
                else:
                    logger.error("Calling LLM but dashscope.api_key is None/Empty!")

                response = dashscope.Generation.call(
                    model=self.model_name,
                    messages=self.messages,
                    result_format='message',
                    api_key=current_key,
                )
                if response.status_code == HTTPStatus.OK:
                    content = response.output.choices[0]['message']['content']
                    self.add_message('assistant', content)
                    return content
                logger.error(f"LLM Request Failed: Code: {response.code}, Message: {response.message}")
                return "抱歉，我现在无法回答。"
            except Exception as e:
                logger.error(f"LLM Exception: {e}")
                return "抱歉，发生了一些错误。"

        # stream
        self.add_message('user', user_input)
        try:
            current_key = getattr(dashscope, "api_key", None)
            if current_key:
                masked_key = current_key[:6] + "*" * 6 + current_key[-4:]
                logger.info(f"Calling LLM Stream with Key: {masked_key}")
            else:
                logger.error("Calling LLM Stream but dashscope.api_key is None/Empty!")

            responses = dashscope.Generation.call(
                model=self.model_name,
                messages=self.messages,
                result_format='message',
                stream=True,
                incremental_output=True,
                api_key=current_key,
            )
            full_content = ""
            for response in responses:
                if response.status_code == HTTPStatus.OK:
                    content = response.output.choices[0]['message']['content']
                    full_content += content
                    yield content
                else:
                    logger.error(
                        f"LLM Stream Request Failed: Code: {response.code}, Message: {response.message}"
                    )
                    yield ""
            self.add_message('assistant', full_content)
        except Exception as e:
            logger.error(f"LLM Stream Exception: {e}")
            yield "抱歉，发生了一些错误。"

    def get_LLM_response(self, user_input):
        """获取非流式回复"""
        mode = self._get_engine_mode()
        if mode in ("local_ascend_qwen_om", "local", "ascend_om"):
            try:
                self.add_message('user', user_input)
                engine = self._build_local_engine()
                content = engine.generate_text(self.messages)
                self.add_message('assistant', content)
                return content
            except Exception as e:
                logger.error(f"Local LLM Exception: {e}")
                return "抱歉，本地大模型推理失败。"

        # default: dashscope
        return self._call_dashscope(stream=False, user_input=user_input)

    def get_LLM_response_stream(self, user_input):
        """获取流式回复"""
        mode = self._get_engine_mode()
        if mode in ("local_ascend_qwen_om", "local", "ascend_om"):
            self.add_message('user', user_input)
            full_content = ""
            try:
                engine = self._build_local_engine()
                for part in engine.generate_stream(self.messages):
                    full_content += part
                    yield part
                self.add_message('assistant', full_content)
            except Exception as e:
                logger.error(f"Local LLM Stream Exception: {e}")
                yield "抱歉，本地大模型推理失败。"
            return

        # default: dashscope
        yield from self._call_dashscope(stream=True, user_input=user_input)  # type: ignore[misc]

