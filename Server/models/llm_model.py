import dashscope
from dashscope.api_entities.dashscope_response import Role
from tools.logger import logger
from http import HTTPStatus
import json

class LLMModel:
    def __init__(self, model_name="qwen-turbo"):
        self.model_name = model_name
        self.messages = []
        self.system_content = "You are a helpful assistant."

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

    def get_LLM_response(self, user_input):
        """获取非流式回复"""
        self.add_message('user', user_input)
        try:
            # 显式获取当前的 API Key
            current_key = dashscope.api_key
            
            # Debug: 打印当前使用的 API Key (隐去中间部分)
            if current_key:
                masked_key = current_key[:6] + "*" * 6 + current_key[-4:]
                logger.info(f"Calling LLM with Key: {masked_key}")
            else:
                logger.error("Calling LLM but dashscope.api_key is None/Empty!")

            response = dashscope.Generation.call(
                model=self.model_name,
                messages=self.messages,
                result_format='message',
                api_key=current_key  # 显式传递 Key
            )
            if response.status_code == HTTPStatus.OK:
                content = response.output.choices[0]['message']['content']
                self.add_message('assistant', content)
                return content
            else:
                logger.error(f"LLM Request Failed: Code: {response.code}, Message: {response.message}")
                return "抱歉，我现在无法回答。"
        except Exception as e:
            logger.error(f"LLM Exception: {e}")
            return "抱歉，发生了一些错误。"

    def get_LLM_response_stream(self, user_input):
        """获取流式回复"""
        self.add_message('user', user_input)
        try:
            # 显式获取当前的 API Key
            current_key = dashscope.api_key

            # Debug: 打印当前使用的 API Key
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
                api_key=current_key  # 显式传递 Key
            )
            full_content = ""
            for response in responses:
                if response.status_code == HTTPStatus.OK:
                    content = response.output.choices[0]['message']['content']
                    full_content += content
                    yield content
                else:
                    logger.error(f"LLM Stream Request Failed: Code: {response.code}, Message: {response.message}")
                    yield ""
            
            self.add_message('assistant', full_content)
            
        except Exception as e:
            logger.error(f"LLM Stream Exception: {e}")
            yield "抱歉，发生了一些错误。"
