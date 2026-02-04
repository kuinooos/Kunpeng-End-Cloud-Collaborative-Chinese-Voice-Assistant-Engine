import threading
import queue
import time
from tools.logger import logger

class LLMWorker(threading.Thread):
    """Dedicated thread that owns ACL context and handles all local LLM inference.

    Usage:
      worker = LLMWorker(cfg)
      worker.start()
      res = worker.generate_text(messages)
      for chunk in worker.generate_stream(messages): ...
    """
    def __init__(self, cfg):
        super().__init__(daemon=True, name="LLM-Worker")
        self.cfg = cfg
        self.req_queue = queue.Queue()
        self.started = threading.Event()
        self._stop_event = threading.Event()

    def run(self):
        try:
            # Import and initialize engine inside this thread so ACL context binds here
            from models.local_llm_qwen_ascend_om import get_global_local_qwen_engine

            logger.info("LLM worker: initializing engine in worker thread")
            self.engine = get_global_local_qwen_engine(self.cfg)
            self.engine.ensure_initialized()
            logger.info("LLM worker: engine initialized")
            self.started.set()

            while not self._stop_event.is_set():
                try:
                    req = self.req_queue.get(timeout=0.5)
                except queue.Empty:
                    continue

                typ = req.get("type")
                if typ == "generate_text":
                    messages = req.get("messages")
                    max_new_tokens = req.get("max_new_tokens")
                    reply_q = req.get("reply_queue")
                    try:
                        res = self.engine.generate_text(messages, max_new_tokens=max_new_tokens)
                        reply_q.put({"ok": True, "result": res})
                    except Exception as e:
                        reply_q.put({"ok": False, "error": str(e)})

                elif typ == "generate_stream":
                    messages = req.get("messages")
                    max_new_tokens = req.get("max_new_tokens")
                    chunk_q = req.get("chunk_queue")
                    try:
                        for chunk in self.engine.generate_stream(messages, max_new_tokens=max_new_tokens):
                            chunk_q.put({"chunk": chunk})
                        chunk_q.put({"done": True})
                    except Exception as e:
                        chunk_q.put({"error": str(e)})

                elif typ == "stop":
                    break

        except Exception as e:
            logger.error(f"LLM worker failed to initialize or crashed: {e}")
            import traceback; traceback.print_exc()
            self.started.set()

    def generate_text(self, messages, max_new_tokens=None, timeout=60):
        q = queue.Queue()
        self.req_queue.put({
            "type": "generate_text",
            "messages": messages,
            "max_new_tokens": max_new_tokens,
            "reply_queue": q,
        })
        try:
            resp = q.get(timeout=timeout)
        except queue.Empty:
            raise TimeoutError(f"LLM worker generate_text timeout after {timeout}s")
        if not resp.get("ok"):
            raise RuntimeError(resp.get("error", "Unknown LLM worker error"))
        return resp.get("result")

    def generate_stream(self, messages, max_new_tokens=None, initial_timeout=10, chunk_timeout=30):
        """Return a generator that yields chunks.

        - initial_timeout: seconds to wait for the first chunk (prevents long hang)
        - chunk_timeout: seconds to wait between subsequent chunks
        """
        chunk_q = queue.Queue()
        self.req_queue.put({
            "type": "generate_stream",
            "messages": messages,
            "max_new_tokens": max_new_tokens,
            "chunk_queue": chunk_q,
        })

        # wait for first chunk with timeout
        try:
            item = chunk_q.get(timeout=initial_timeout)
        except queue.Empty:
            raise TimeoutError(f"LLM worker stream initial response timeout after {initial_timeout}s")

        # process first item (may be chunk, done or error)
        while True:
            if "chunk" in item:
                yield item["chunk"]
            elif "done" in item:
                break
            elif "error" in item:
                raise RuntimeError(item.get("error"))

            # subsequent chunks: wait with chunk_timeout
            try:
                item = chunk_q.get(timeout=chunk_timeout)
            except queue.Empty:
                raise TimeoutError(f"LLM worker stream timed out waiting for next chunk after {chunk_timeout}s")

    def stop(self):
        self._stop_event.set()
        self.req_queue.put({"type": "stop"})

