from service_manager import ServiceManager
from tools.logger import logger
from config.settings import global_settings
from tools.registry import global_registry

# 职责：处理客户端发送的 JSON 格式控制消息。
# 核心逻辑：
# hello 消息：握手成功后接收客户端的初始化参数（如 API Key）。
# functions_register 消息：接收客户端注册的硬件控制能力（如“开灯”、“前进”），并将其注册到 FunctionRegistry 中，供 LLM 随时调用。
# state 消息：同步客户端的状态机变化（Idle -> Listening -> Thinking -> Speaking）。
# 例如，当收到 listening 状态时，服务端会重置 VAD 和 ASR，准备开始新一轮对话。

class TextHandler:
    def __init__(self, service_manager: ServiceManager):
        self.service_manager = service_manager

    async def handle_text_message(self, data: dict):
        """
        处理 JSON 文本消息
        :param data: JSON 数据
        :return: 响应消息
        """
        if data.get('type') == 'hello':
            audio_params = data.get('audio_params', {})
            logger.info(f"Received hello message with audio params: {audio_params}")
            api_key = data.get('api_key', None)
            global_settings.Set_API_Key(api_key)
            # 暂时没设定可变的音频参数列表, 所以client发送过来的音频参数不会被使用
            # sample_rate = audio_params.get('sample_rate', AudioProcessor.sample_rate)
            # channels = audio_params.get('channels', AudioProcessor.CHANNELS)
            # frame_duration_ms = audio_params.get('frame_duration', AudioProcessor.frame_duration_ms)
            # logger.info(f"Set audio parameters: sample_rate={sample_rate}, channels={channels}, frame_duration_ms={frame_duration_ms}")
            # self.audio_processor.set_audio_params(sample_rate, channels, frame_duration_ms)

        elif data.get('type') == 'functions_register':
            # 获取要注册的函数列表
            functions = data.get('functions', [])
            if not isinstance(functions, list):
                logger.error("functions 字段必须是一个列表")
                return {"type": "error", "message": "Invalid functions format"}
            self.handle_register_functions(functions)

        elif data.get('type') == 'state':
            # client 端 idle 信息
            if data.get('state') == 'idle':
                self.service_manager.reset_services()
                logger.info("Client is idle, resetting services")

            elif data.get('state') == 'listening':
                self.service_manager.is_vad = False
                self.service_manager.vad_service.reset()
                self.service_manager.asr_service.reset()
                # 提前打开tts流,设置回调_tts_on_data
                self.service_manager.tts_service.tts_set(on_data=self.service_manager._tts_on_data, on_close=self.service_manager._tts_on_complete)

            elif data.get('state') == 'thinking':
                logger.info("Server is thinking")

            elif data.get('state') == 'speaking':
                logger.info("Client is speaking")

        else:
            logger.warning(f"Unknown JSON message type: {data.get('type')}")
            logger.info(f"Received unknown message: {data}")
            return {"type": "error", "message": "Unknown message type"}


    def handle_register_functions(self, functions: list):
        """
        处理函数注册请求
        :param functions: 函数列表
        """
        for func in functions:
            try:
                # 提取函数信息
                function_name = func.get('name')
                description = func.get('description', '')
                arguments = func.get('arguments', {})

                # 检查必要字段
                if not function_name or not isinstance(arguments, dict):
                    logger.error(f"函数注册失败，缺少必要字段: {func}")
                    continue

                # 注册函数，使用通用回调函数
                global_registry.register_function(
                    function_name=function_name,
                    description=description,
                    parameters=arguments,
                    impl=self._generic_function_callback
                )
                logger.info(f"成功注册函数: {function_name}, 描述: {description}, 参数: {arguments}")

            except Exception as e:
                logger.error(f"注册函数时发生错误: {e}")


    def _generic_function_callback(self, function_name: str, *args, **kwargs):
        """
        通用intent函数回调处理, server端只打印
        :param function_name: 函数名称
        :param args: 函数参数
        :param kwargs: 函数关键字参数
        :return: 函数执行结果
        """
        logger.info(f"Function '{function_name}' called with args: {args}, kwargs: {kwargs}")
        # 这里可以根据需要执行相应的操作
        # 例如，调用其他服务或处理数据
        return "Function executed successfully"