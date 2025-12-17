from services.vad_service import VADService
from services.asr_service import ASRService
from services.chat_service import ChatService
from services.tts_service import TTSService
from tools.registry import global_registry
from services.intent_service import IntentService
from tools.audio_processor import AudioProcessor
from threads.task_manager import TaskManager
from tools.logger import logger
from config.settings import global_settings
import queue
import threading
import json

class ServiceManager:
    def __init__(self):
        # 初始化服务
        self.audio_processor = AudioProcessor()
        self.vad_service = VADService()
        self.asr_service = ASRService()
        self.intent_service = IntentService(global_registry)
        self.chat_service = ChatService()
        self.tts_service = TTSService()
        # 注册 TTS 回调：on_data 接收音频，on_close (对应 _tts_on_complete) 发送结束信号
        self.tts_service.tts_set(on_data=self._tts_on_data, on_close=self._tts_on_complete)
        self.is_vad = False  # 防止VAD发生后还语音加入

        self.tts_text_queue = queue.Queue() # 用于存放 TTS 生成的文本
        self.audio_queue = queue.Queue()    # 用于存放生成的音频数据
        self.ws_send_queue = queue.Queue()  # 用于存储ws需要发送的数据

        self.stop_event = threading.Event() # 用于控制线程停止

        self.task_manager = TaskManager()   # 短生命周期的任务管理器

        def continue_chat():
            return "继续聊天..."

        def handle_exit_intent():
            return "再见！"

        def make_smile():
            return "做一个笑脸"

        # 默认的一些意图注册到系统
        global_registry.register_function("continue_chat", "继续聊天意图", {}, continue_chat)
        global_registry.register_function("exit_chat", "结束对话意图", {}, handle_exit_intent)
        global_registry.register_function("make_smile", "做一个笑脸", {}, make_smile)

    def reset_services(self):
        """
        重置所有服务的状态
        """
        self.is_vad = False        
        # 清空发送队列，防止残留消息发送给新客户端
        while not self.ws_send_queue.empty():
            try:
                self.ws_send_queue.get_nowait()
            except queue.Empty:
                break
        
        self.vad_service.reset()
        self.asr_service.reset()
        self.chat_service.chat_clear()
        try:
            self.tts_service.tts_close()
        except Exception as e:
            pass

    def _tts_on_data(self, data):
        """
        TTS 生成回调函数
        :param data: 生成的音频数据
        """
        # 将生成的音频数据放入语音队列
        self.audio_queue.put(data)
        # logger.info(f"Received TTS data: {len(data)} bytes")

    def _tts_on_complete(self):
        msg = {
            "type": "tts",
            "state": "end",
        }
        self.ws_send_queue.put(json.dumps(msg))

    def chat_start_task(self, text):
        """
        处理识别到的文本，进行对话
        :param self: ServiceManager 实例
        :param text: 文本
        """
        # 1.进行意图识别
        function_calls = self.intent_service.detect_intent(text)
        history_list = []
        # 2.执行函数调用（如果有）
        for function_call in function_calls:
            if "function_call" in function_call and "name" in function_call["function_call"]:
                logger.info(f"[准备调用] {function_call}")
                # 执行函数调用
                if function_call["function_call"]["name"] == "continue_chat":
                    # 继续聊天意图
                    pass
                elif function_call["function_call"]["name"] == "exit_chat":
                    # 结束对话意图
                    response =  {
                            "type": "chat",
                            "dialogue": "end"
                    }
                    self.ws_send_queue.put(json.dumps(response))
                else:
                    # 其他函数调用, 发送到Client端, Client自己处理
                    self.ws_send_queue.put(json.dumps(function_call))
                    history_list.append([
                        {"role": "user", "content": f"函数调用: {function_call}"},
                        {"role": "assistant", "content": f"函数调用完成"}
                    ])
        # 3.调用聊天服务生成文字
        #把识别的文本送入对话模型
        #is_stream=True 说明是流式返回，一边生成一边发
        answers = self.chat_service.generate_chat_response(text, history=history_list, is_stream=True)
        if answers == -1:
            logger.error("LLM 生成失败")
            return -1
        logger.info(f"[回复]: ")
        # 4.将生成的文字放入 TTS任务队列
        # for ans_chunk in answers:
        #     print(ans_chunk, end="", flush=True)
        #     service_manager.tts_text_queue.put(ans_chunk)

        # 4.直接TTS生成（流式别名纠正+累积缓冲优化）
        alias_patterns = ["Echo", "echo", "Echo-Mate", "海鲲鹏"]
        robot_name = getattr(global_settings, "ROBOT_NAME", "鲲鹏")
        max_alias_len = max(len(p) for p in alias_patterns) if alias_patterns else 0
        overlap = max(1, max_alias_len - 1) if max_alias_len > 0 else 0
        pending = ""
        tts_buffer = ""  # TTS缓冲区，累积到一定长度或遇到标点才发送
        min_tts_length = 10  # 最小TTS长度（字符数）
        punctuation = '，。！？；：,.!?;:'  # 标点符号

        def _normalize(text: str) -> str:
            for pat in alias_patterns:
                if pat in text:
                    text = text.replace(pat, robot_name)
            return text

        for part in answers:
            # 合并待处理尾巴，做替换
            combined = _normalize(pending + part)
            if overlap > 0 and len(combined) > overlap:
                emit = combined[:-overlap]
                pending = combined[-overlap:]
            else:
                emit = ""
                pending = combined
            
            if emit:
                print(emit, end="", flush=True)
                tts_buffer += emit
                
                # 检查是否应该发送TTS：达到最小长度或遇到标点符号
                should_send = False
                if len(tts_buffer) >= min_tts_length:
                    # 如果最后一个字符是标点，立即发送
                    if tts_buffer[-1] in punctuation:
                        should_send = True
                    # 或者长度超过阈值较多时也发送
                    elif len(tts_buffer) >= min_tts_length * 2:
                        should_send = True
                
                if should_send and tts_buffer:
                    self.tts_service.tts_speech_stream(tts_buffer)
                    tts_buffer = ""
        
        # 处理剩余的别名纠正尾巴
        if pending:
            print(pending, end="", flush=True)
            tts_buffer += pending
        
        # 处理剩余的TTS缓冲区
        if tts_buffer:
            self.tts_service.tts_speech_stream(tts_buffer)
        
        print()  # 换行（流结束）
        # 关闭 TTS 流
        self.tts_service.tts_close()
