import os
import sys
# Ensure project root (Server dir) is on sys.path so local `tools` package is importable
_project_root = os.path.abspath(os.path.dirname(__file__))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

# Also ensure parent dir is present for safety
_parent = os.path.abspath(os.path.join(_project_root, '..'))
if _parent not in sys.path:
    sys.path.insert(0, _parent)

import asyncio
import argparse
from threads.tts_thread import TTSGenerateThread
from threads.audio_send_thread import AudioSendThread
from tools.logger import logger
from service_manager import ServiceManager
from tools.affinity import set_process_affinity, configure_runtime_threads
from tools.diag import print_runtime_diagnostics
from config.settings import global_settings
# defer importing deps_check until runtime to avoid startup import errors in some envs
# (we'll try to import inside main and fall back gracefully)
_check_deps_available = True
try:
    # quick probe to ensure tools package exists (not raising here intentionally)
    import importlib
    importlib.import_module('tools')
except Exception:
    _check_deps_available = False
    logger.warning("tools package not found at startup; runtime deps checks will be skipped unless the package becomes available in PYTHONPATH")

# Monkey-patch to avoid aioice STUN Transaction set_exception on a done future
try:
    import asyncio as _asyncio
    from aioice import stun as _stun
    _orig_retry = _stun.Transaction.__retry
    def _safe_retry(self):
        try:
            return _orig_retry(self)
        except _asyncio.InvalidStateError:
            logger.warning("Transaction.__retry: ignored InvalidStateError (future already done)")
    _stun.Transaction.__retry = _safe_retry
except Exception:
    # If aioice not installed or patch fails, continue silently
    pass

async def main(host: str,
               port: int,
               access_token: str,
               device_id: str,
               protocol_version: int,
               use_webrtc: bool = False):

    # 启动前依赖自检：缺 piper/模型文件会直接给出明确错误
    # 动态导入以避免在不完整 PYTHONPATH 时在模块导入阶段崩溃
    try:
        from tools.deps_check import check_local_backends_or_raise
    except Exception as e:
        logger.warning(f"tools.deps_check 无法导入，跳过本地后端自检: {e}")
        def check_local_backends_or_raise():
            return None
    check_local_backends_or_raise()

    # 初始化vad asr chat intent tts服务
    service_manager = ServiceManager()

    # 配置运行时线程数与进程 CPU 亲和
    configure_runtime_threads()
    # 打印运行时诊断信息（确认是否使用了 aarch64 优化路径）
    print_runtime_diagnostics()
    if global_settings.ENABLE_AFFINITY and global_settings.PROCESS_CPU_SET:
        set_process_affinity(global_settings.PROCESS_CPU_SET)

    # 启动 TTS 生成线程
    tts_generate_thread = TTSGenerateThread(service_manager)
    # tts_generate_thread.start()

    # 启动 audio 数据发送线程
    tts_send_thread = AudioSendThread(service_manager)
    tts_send_thread.start()

    # 根据参数选择启动 WebSocket 或 WebRTC 服务器
    if use_webrtc:
        logger.info("=== 启动 WebRTC 服务器模式 (低延迟UDP传输) ===")
        try:
            from webrtc_server import WebRTCServer
        except ModuleNotFoundError as e:
            missing = getattr(e, "name", None) or str(e)
            if missing and missing != "webrtc_server":
                raise ModuleNotFoundError(
                    "WebRTC 模式缺少依赖模块：'{0}'。\n"
                    "请先安装 WebRTC 依赖：pip install aiortc（或 pip install -r requirements-webrtc.txt），\n"
                    "并确认当前运行的 Python 环境就是安装依赖的那个环境。"
                    .format(missing)
                ) from e

            raise ModuleNotFoundError(
                "WebRTC 模式缺少模块 'webrtc_server'。\n"
                "请确认 webrtc_server.py 存在于 Server 目录下，或已正确安装/拷贝对应模块。"
            ) from e
        server = WebRTCServer(host=host,
                             port=port,
                             access_token=access_token,
                             device_id=device_id,
                             protocol_version=protocol_version,
                             service_manager=service_manager)
    else:
        logger.info("=== 启动 WebSocket 服务器模式 (传统TCP传输) ===")
        try:
            from ws_server import WebSocketServer
        except ModuleNotFoundError as e:
            raise ModuleNotFoundError(
                "WebSocket 模式缺少依赖 'websockets' 或相关模块。\n"
                "请执行: pip install -r requirements.txt"
            ) from e
        server = WebSocketServer(host=host,
                                port=port,
                                access_token=access_token,
                                device_id=device_id,
                                protocol_version=protocol_version,
                                service_manager=service_manager)
    
    try:
        await server.start_server()
    except KeyboardInterrupt:
        logger.info("\n服务器正在关闭...")
    finally:
        # 停止线程
        service_manager.stop_event.set()  # 设置停止事件
        # tts_generate_thread.join()
        tts_send_thread.join()
        
        # 如果是WebRTC服务器，执行清理
        if use_webrtc and hasattr(server, 'cleanup'):
            await server.cleanup()
        
        logger.info("服务器已关闭。")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AIChat Server - WebSocket/WebRTC Mode")
    parser.add_argument("--host", default="0.0.0.0", help="listen host")
    parser.add_argument("--port", type=int, default=8000, help="listen port")
    parser.add_argument("--access_token", default="123456", help="token for client auth")
    parser.add_argument("--device_id", default="00:11:22:33:44:55", help="expected client device id (optional)")
    parser.add_argument("--protocol_version", type=int, default=2, help="protocol version expected from client")
    parser.add_argument("--aliyun_api_key", default=None, help="DashScope/ALIYUN API key for Qwen/related services")
    parser.add_argument("--webrtc", action="store_true", help="启用WebRTC模式 (UDP低延迟传输)")

    args = parser.parse_args()

    # 覆盖全局 LLM API Key（如果提供）
    if args.aliyun_api_key:
        try:
            global_settings.Set_API_Key(args.aliyun_api_key)
            logger.info("DashScope API key has been set from CLI.")
        except Exception as e:
            logger.warning(f"Failed to set API key from CLI: {e}")

    # 显示启动模式
    if args.webrtc:
        logger.info("🚀 WebRTC模式: 使用UDP DataChannel实现低延迟音频传输")
        logger.info("⚡ 特性: 零重传、允许丢包、消除队头阻塞")
    else:
        logger.info("🔌 WebSocket模式: 使用TCP传输 (传统模式)")
        logger.info("💡 提示: 使用 --webrtc 参数启用低延迟模式")

    try:
        asyncio.run(main(args.host, args.port, args.access_token, args.device_id, args.protocol_version, args.webrtc))
    except KeyboardInterrupt:
        logger.info("程序已被用户中断")
    finally:
        # 确保事件循环关闭
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.stop()
        except RuntimeError:
            pass
        logger.info("事件循环已关闭")

