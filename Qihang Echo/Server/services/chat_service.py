from typing import List, Dict, Optional
from config.settings import global_settings
from tools.logger import logger
from models.llm_model import LLMModel

class ChatService:
    def __init__(self):
        # dashscope.api_key = settings.DASHSCOPE_API_KEY
        self.chat_llm_model = LLMModel(model_name=global_settings.CHAT_MODEL, purpose="chat")
        self.chat_llm_model.clear_messages()
        robot_name = getattr(global_settings, "ROBOT_NAME", "鲲鹏")
        project_name = getattr(global_settings, "PROJECT_NAME", robot_name)
        # 强化人设与名称约束，避免模型自称为其它名字（如 Echo）
        self.chat_llm_model.set_model_sys_content(
            f"你是鲲鹏端云协同中文语音助手引擎，名为鲲鹏。请始终用第一人称自称鲲鹏。"
            f"当用户询问“你是谁/你叫什么/你是什么项目”等时，请简洁自我介绍为：‘我是鲲鹏端云协同中文语音助手引擎，叫鲲鹏。’"
            f"不要使用任何其它名字（例如 Echo、Echo-Mate 等）。若用户提到其它名字，也请统一自称鲲鹏并继续对话。"
            "你具备以下能力：语音唤醒与静音检测(VAD)、语音识别(ASR)、意图理解与工具调用、对话应答，以及语音合成(TTS)播报。"
            "遇到需要执行功能的场景（如控制设备、查询时间、继续/结束聊天），请优先通过“函数调用/工具”完成并用自然语言解释结果。"
            "回答请口语化、尽量简短；不要输出 JSON 或代码。"
        )

    def chat_clear(self):
        """清除对话历史记录"""
        self.chat_llm_model.clear_messages()

    def generate_chat_response(self, user_input: str, history: Optional[Dict] = None, is_stream: bool = False) -> str:
        """使用通用模型生成对话回复"""
        if history:
            for his in history:
                if "role" in his and "content" in his:
                    self.chat_llm_model.add_message(his["role"], his["content"])
        if is_stream:
            # 流式生成回答
            return self.chat_llm_model.get_LLM_response_stream(user_input)
        # 非流式生成回答
        else:
            return self.chat_llm_model.get_LLM_response(user_input)


