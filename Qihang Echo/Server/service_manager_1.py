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
import time
from threads.llm_worker import LLMWorker

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
        # 标记当前服务器是否正在播放（streaming）TTS 音频
        self.is_playing = False

        self.tts_text_queue = queue.Queue() # 用于存放 TTS 生成的文本
        self.audio_queue = queue.Queue()    # 用于存放生成的音频数据
        self.ws_send_queue = queue.Queue()  # 用于存储ws需要发送的数据

        self.stop_event = threading.Event() # 用于控制线程停止

        self.task_manager = TaskManager()   # 短生命周期的任务管理器
        
        # 启动本地 LLM 专属 worker 线程（在该线程中创建 ACL context 并处理推理）
        engine = getattr(global_settings, "LLM_ENGINE", "").strip().lower()
        self.llm_worker = None
        if engine in ("local_ascend_qwen_om", "local", "ascend_om"):
            try:
                from models.local_llm_qwen_ascend_om import LocalQwenOmConfig
                cfg = LocalQwenOmConfig(
                    device_id=int(getattr(global_settings, "LOCAL_LLM_DEVICE_ID", 0)),
                    model_om_path=str(getattr(global_settings, "LOCAL_LLM_OM_PATH", "")),
                    tokenizer_path=str(getattr(global_settings, "LOCAL_LLM_TOKENIZER_PATH", "")),
                    max_seq_len=int(getattr(global_settings, "LOCAL_LLM_MAX_SEQ_LEN", 1024)),
                    vocab_size=int(getattr(global_settings, "LOCAL_LLM_VOCAB_SIZE", 151936)),
                    kv_num_layers=int(getattr(global_settings, "LOCAL_LLM_KV_NUM_LAYERS", 96)),
                    kv_head_dim=int(getattr(global_settings, "LOCAL_LLM_KV_HEAD_DIM", 64)),
                )
                self.llm_worker = LLMWorker(cfg)
                self.llm_worker.start()
                if not self.llm_worker.started.wait(timeout=60):
                    logger.warning("LLM worker 初始化超时，可能仍在后台启动。")
                else:
                    logger.info("✅ LLM worker 已启动并准备就绪。")
            except Exception as e:
                logger.error(f"启动 LLM worker 失败: {e}")
                import traceback; traceback.print_exc()
        else:
            logger.info("ℹ️  当前使用云端 LLM，无需启动本地 LLM worker。")

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
        self.is_playing = False
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
        # 标记为正在播放（server端状态），以便其它逻辑可知当前在播放
        self.is_playing = True
        # 将生成的音频数据放入语音队列
        self.audio_queue.put(data)
        # logger.info(f"Received TTS data: {len(data)} bytes")

    def _rule_based_intent(self, user_input: str):
        """简单关键字/正则的快速意图检测，用于处理常见快速命令"""
        import re
        text = (user_input or "").lower()
        # 常见退出
        if re.search(r"\b(再见|拜拜|退出|走了)\b", text):
            return [{"function_call": {"name": "exit_chat"}}]
        # 做笑脸
        if re.search(r"(笑脸|做个笑|做一个笑)", text):
            return [{"function_call": {"name": "make_smile"}}]
        # 灯控
        m = re.search(r"(开|关)[^\n]{0,20}灯", text)
        if m:
            action = "on" if m.group(1) == "开" else "off"
            return [{"function_call": {"name": "light_control", "arguments": {"state": action}}}]
        # 机器人移动
        if re.search(r"(左转|右转|前进|后退|向左|向右|往前|往后)", text):
            # 简单抽取方向
            if re.search(r"左", text):
                dir = "left"
            elif re.search(r"右", text):
                dir = "right"
            elif re.search(r"前", text):
                dir = "forward"
            elif re.search(r"后", text):
                dir = "backward"
            else:
                dir = "forward"
            return [{"function_call": {"name": "robot_move", "arguments": {"direction": dir}}}]
        return None

    def _build_brief_tools_prompt(self, max_tools: int = 10) -> str:
        """构造一个精简的工具列表提示，只包含工具名与简短描述，用于降低 prompt 长度。"""
        try:
            tools = global_registry.get_registered_tools()
            brief = []
            for t in (tools or [])[:max_tools]:
                name = t.get("name") or t.get("id") or ""
                desc = t.get("description") or t.get("desc") or ""
                brief.append(f"- {name}: {desc[:120]}")
            tools_text = "\n".join(brief)
            prompt = (
                "你是一个带意图识别的语音助手。请根据下面注册的工具名称及简短描述，判断用户的最后一句话的意图，"
                "并只返回 JSON 列表，表示要执行的函数调用（返回格式举例: [{\"function_call\": {\"name\": \"exit_chat\", \"arguments\": {}}}])。"
                "不要添加任何额外的说明。"
                "\n<start>\n"
                f"工具列表:\n{tools_text}\n"
                "<end>"
            )
            return prompt
        except Exception:
            return "你是一个带意图识别的语音助手。请分析用户的最后一句话并仅返回 JSON 格式的函数调用。"

    def _get_or_load_tokenizer(self):
        """懒加载并缓存 tokenizer，用于计算 token 数与裁剪 prompt。"""
        if getattr(self, "_tokenizer", None) is not None:
            return self._tokenizer
        try:
            from transformers import AutoTokenizer
            tok_path = str(getattr(global_settings, "LOCAL_LLM_TOKENIZER_PATH", "")) or None
            if not tok_path:
                logger.warning("LOCAL_LLM_TOKENIZER_PATH 未设置，无法使用 tokenizer 进行精确裁剪")
                self._tokenizer = None
                return None
            logger.info(f"🧰 加载 tokenizer 用于 token 裁剪: {tok_path}")
            self._tokenizer = AutoTokenizer.from_pretrained(tok_path, trust_remote_code=True)
            return self._tokenizer
        except Exception as e:
            logger.warning(f"无法加载 tokenizer（将回退到字符裁剪）: {e}")
            self._tokenizer = None
            return None

    def _measure_tokens(self, text: str) -> int:
        """返回文本大致的 token 数（优先用 tokenizer，失败时用字符数估算）"""
        try:
            tok = self._get_or_load_tokenizer()
            if tok is not None:
                ids = tok.encode(text)
                return len(ids)
        except Exception as e:
            logger.debug(f"token 估算失败，回退到字符估算: {e}")
        # 粗略估计：按每 2 个字符约 1 token
        return max(1, len(text) // 2)

    def _trim_messages_by_tokens(self, messages: list, max_prefill_tokens: int = 512) -> list:
        """基于 tokenizer 将 messages 裁剪到 prefill token 数限制以内。

        messages: list of {role, content}
        保持 system 在头部，优先保留最近的 history。
        """
        if not messages:
            return messages

        # 系统提示保留
        system = messages[0] if messages[0].get("role") == "system" else None
        others = messages[1:] if system else messages

        # Helper to build text from messages
        def _msgs_to_text(msgs):
            parts = []
            for m in msgs:
                role = m.get("role", "user")
                parts.append(f"[{role}] {m.get('content', '')}")
            return "\n".join(parts)

        # If already within limit, return
        base_text = _msgs_to_text([system] if system else [])
        total_text = base_text + ("\n" + _msgs_to_text(others) if others else "")
        total_tokens = self._measure_tokens(total_text)
        logger.info(f"🔢 初始预填充估算 tokens: {total_tokens}, 限制: {max_prefill_tokens}")
        if total_tokens <= max_prefill_tokens:
            return messages

        # Start trimming: remove oldest history messages one by one
        # others is [history..., user]
        trimmed = list(others)
        while trimmed and self._measure_tokens(base_text + "\n" + _msgs_to_text(trimmed)) > max_prefill_tokens:
            # remove the oldest (from head)
            trimmed.pop(0)
            # If only user remains, we'll need to truncate its content
            if len(trimmed) == 1:
                # truncate user content by characters until fits
                user_msg = trimmed[0]
                content = user_msg.get("content", "")
                # approximate truncation: reduce until measurement fits
                while content and self._measure_tokens(base_text + "\n" + _msgs_to_text([{"role":"user","content":content}])) > max_prefill_tokens:
                    content = content[: max(1, len(content) - 50)]
                user_msg["content"] = content
                trimmed[0] = user_msg
                break

        new_msgs = ([system] if system else []) + trimmed
        new_total = self._measure_tokens(_msgs_to_text(new_msgs))
        logger.info(f"🔢 裁剪后估算 tokens: {new_total}")
        return new_msgs

    def _detect_intent(self, user_input: str):
        """通过本地 LLM worker 来执行意图识别（先尝试规则检测，再尝试简短提示词提高速度，失败再回退到完整提示）"""
        try:
            # 1) 规则快速检测
            rule = self._rule_based_intent(user_input)
            if rule is not None:
                logger.info(f"🔍 规则意图检测命中: {rule}")
                return rule

            # 优先使用长期运行的 LLM worker（避免 ACL 线程绑定问题）
            if hasattr(self, "llm_worker") and self.llm_worker is not None:
                logger.info("🔍 使用 LLM worker 进行意图识别（先尝试简短提示词）")

                # 简短的意图识别提示（避免把完整工具列表/示例传入，减少 prefill）
                compact_prompt = (
                    "请分析下面的用户一句话，并仅返回一个 JSON 列表，表示要执行的函数调用。"
                    "格式示例：[{\"function_call\": {\"name\": \"exit_chat\", \"arguments\": {}}}]。"
                    "不要额外的说明或多余文本。只返回 JSON。"
                    f"\n用户: {user_input}"
                )
                compact_messages = [{"role": "user", "content": compact_prompt}]

                # 先用短超时尝试快速得到意图
                try:
                    response = self.llm_worker.generate_text(compact_messages, timeout=6)
                except TimeoutError:
                    logger.info("⚠️ 简短意图识别超时，改用完整版提示并延长超时")
                    # 使用完整版提示，允许更长的超时
                    full_prompt = self._build_brief_tools_prompt()
                    messages = [{"role": "system", "content": full_prompt}, {"role": "user", "content": user_input}]
                    try:
                        response = self.llm_worker.generate_text(messages, timeout=12)
                    except Exception as e:
                        logger.error(f"LLM worker 意图识别失败（完整版）: {e}")
                        return [{"function_call": {"name": "continue_chat"}}]
                except Exception as e:
                    logger.error(f"LLM worker 意图识别失败: {e}")
                    return [{"function_call": {"name": "continue_chat"}}]

                # 解析 response
                parsed = None
                if isinstance(response, str):
                    # 去掉多余包裹
                    if response.startswith("```json"):
                        response = response.strip("```json").strip()
                    elif response.startswith("```"):
                        response = response.strip("```").strip()
                    logger.info(f"[意图识别结果]: {response}")

                    try:
                        parsed = json.loads(response)
                    except json.JSONDecodeError:
                        # 可能模型返回了附带文本或部分说明，尝试从字符串中抽取首个 { 或 [ 开始的 JSON
                        import re
                        m = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", response)
                        if m:
                            try:
                                parsed = json.loads(m.group(1))
                            except Exception:
                                parsed = None
                        else:
                            parsed = None
                elif isinstance(response, (dict, list)):
                    parsed = response
                    logger.info(f"[意图识别结果]: {response}")

                if not parsed:
                    logger.warning("意图识别解析失败或返回空，使用 continue_chat 作为回退。")
                    return [{"function_call": {"name": "continue_chat"}}]

                if isinstance(parsed, dict):
                    parsed = [parsed]

                # 解析每个函数调用的参数并转换数字为字符串
                for function_call in parsed:
                    if "function_call" in function_call and "arguments" in function_call["function_call"]:
                        try:
                            if isinstance(function_call["function_call"]["arguments"], str):
                                function_call["function_call"]["arguments"] = json.loads(function_call["function_call"]["arguments"])
                            function_call["function_call"]["arguments"] = self.intent_service._convert_numbers_to_strings(function_call["function_call"]["arguments"])
                        except Exception as e:
                            logger.error(f"函数参数解析失败: {e}")
                            function_call["function_call"]["arguments"] = {}

                return parsed

            # 回退到原有的 IntentService 实现
            return self.intent_service.detect_intent(user_input)
        except Exception as e:
            logger.error(f"意图识别失败（通用捕获）: {e}")
            return [{"function_call": {"name": "continue_chat"}}]

    def _tts_on_complete(self):
        # 播放完成，清理播放标志
        self.is_playing = False
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
        # 1.进行意图识别（优先通过 LLM worker 执行以避免 ACL 线程绑定问题）
        function_calls = self._detect_intent(text)
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
        engine_name = getattr(global_settings, "LLM_ENGINE", "").strip().lower()

        # 记录 prompt 长度以便诊断（字符数）
        try:
            prompt_overview = ''
            if self.chat_service.chat_llm_model.system_content:
                prompt_overview += self.chat_service.chat_llm_model.system_content
            if history_list:
                prompt_overview += ' ' + json.dumps(history_list, ensure_ascii=False)
            prompt_overview += ' ' + (text or '')
            logger.info(f"📏 Prompt length (chars): {len(prompt_overview)}")
        except Exception:
            pass
        if engine_name in ("local_ascend_qwen_om", "local", "ascend_om") and hasattr(self, "llm_worker") and self.llm_worker is not None:
            # 构造 messages: system + 截断后的 history + 截断后的 user
            def _trim_history_and_text(history_list, user_text, max_history=3, max_user_chars=200):
                # 只保留最近 max_history 条历史（每条是 list of messages）
                trimmed = history_list[-max_history:] if history_list else []
                # 剪裁 user_text 到 max_user_chars
                if user_text and len(user_text) > max_user_chars:
                    user_text = user_text[:max_user_chars]
                    logger.info(f"🔧 截断输入文本到 {max_user_chars} 字符以避免超长 prefill")
                return trimmed, user_text

            trimmed_history, trimmed_text = _trim_history_and_text(history_list, text)

            messages = []
            if self.chat_service.chat_llm_model.system_content:
                messages.append({"role": "system", "content": self.chat_service.chat_llm_model.system_content})
            for h in trimmed_history:
                messages.extend(h)
            messages.append({"role": "user", "content": trimmed_text})

            # 基于 tokenizer 的 token 裁剪以限制 prefill 大小
            max_prefill = int(getattr(global_settings, "LOCAL_LLM_PREFILL_MAX_TOKENS", 512))
            messages = self._trim_messages_by_tokens(messages, max_prefill_tokens=max_prefill)

            try:
                # 初始块等待 30s，后续块最大间隔 30s（增加初始超时以应对较慢的首次 prefill）
                try:
                    answers = self.llm_worker.generate_stream(messages, initial_timeout=30, chunk_timeout=30)
                except TypeError as e:
                    # 向后兼容：若 worker 的 generate_stream 不接受这些参数，则退回到不带超时的调用
                    logger.warning(f"LLM worker.generate_stream 不支持 initial_timeout/chunk_timeout 参数: {e}，尝试不带超时参数调用")
                    answers = self.llm_worker.generate_stream(messages)
            except TimeoutError as e:
                logger.error(f"Local LLM Stream Timeout: {e}")
                # 发送超时提示给客户端并返回失败，避免主线程卡住
                try:
                    self.ws_send_queue.put(json.dumps({"type": "status", "state": "timeout", "message": "LLM 响应超时，请稍后重试"}))
                except Exception:
                    pass
                return -1
            except Exception as e:
                logger.error(f"Local LLM Stream Exception: {e}")
                logger.exception(e)
                try:
                    self.ws_send_queue.put(json.dumps({"type": "status", "state": "error", "message": "LLM 生成失败"}))
                except Exception:
                    pass
                return -1
        else:
            answers = self.chat_service.generate_chat_response(text, history=history_list, is_stream=True)
            if answers == -1:
                logger.error("LLM 生成失败")
                return -1
        logger.info(f"[回复]: ")

        # 心跳线程：在拿到第一个返回前定期告诉客户端 server 正在思考，避免客户端超时断开
        first_chunk_event = threading.Event()
        def thinking_heartbeat():
            while not first_chunk_event.is_set():
                try:
                    self.ws_send_queue.put(json.dumps({"type": "status", "state": "thinking", "message": "服务器正在思考..."}))
                except Exception:
                    pass
                time.sleep(3)
        hb_thread = threading.Thread(target=thinking_heartbeat, daemon=True, name="LLM-Heartbeat")
        hb_thread.start()
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

        try:
            for part in answers:
                # 收到第一个 chunk，停止心跳
                if not first_chunk_event.is_set():
                    first_chunk_event.set()

                # 把部分文本实时发给客户端（partial），也继续累积用于 TTS
                try:
                    self.ws_send_queue.put(json.dumps({"type": "chat", "dialogue": part, "state": "partial"}))
                except Exception:
                    pass

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

            # 发送最终聊天完成消息
            try:
                self.ws_send_queue.put(json.dumps({"type": "chat", "dialogue": "", "state": "end"}))
            except Exception:
                pass

        except Exception as e:
            # 确保心跳停止
            first_chunk_event.set()
            logger.error(f"LLM 生成过程中出现错误: {e}")
            try:
                self.ws_send_queue.put(json.dumps({"type": "status", "state": "error", "message": "模型生成失败"}))
            except Exception:
                pass
            return -1

