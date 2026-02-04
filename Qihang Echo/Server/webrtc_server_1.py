import asyncio
import json
import logging
from aiohttp import web
from aiortc import RTCPeerConnection, RTCSessionDescription, RTCDataChannel
from handle.text_handler import TextHandler
from handle.audio_handler import AudioHandler
from handle.auth_handler import AuthHandler
from service_manager import ServiceManager
from tools.logger import logger

class WebRTCServer:
    """
    WebRTC服务器，使用DataChannel进行实时音频传输
    - audio通道: 不可靠模式(UDP)，用于音频数据传输，零重传，低延迟
    - text通道: 可靠模式，用于控制消息和JSON数据
    """
    def __init__(self, host="0.0.0.0", port=8000, access_token="123456", 
                 device_id="00:11:22:33:44:55", protocol_version=2, 
                 service_manager: ServiceManager = None):
        self.host = host
        self.port = port
        self.service_manager = service_manager
        
        # 复用原有的处理器
        self.text_handler = TextHandler(self.service_manager)
        self.audio_handler = AudioHandler(self.service_manager)
        self.auth_handler = AuthHandler(access_token, device_id, protocol_version)
        
        # 存储活跃的连接 (pcs = PeerConnections)
        self.pcs = set()
        
        # 存储每个连接的DataChannel
        self.audio_channels = {}
        self.text_channels = {}

    async def offer(self, request):
        """
        处理 WebRTC 信令交换 (Signaling): 接收 Offer -> 返回 Answer
        """
        try:
            params = await request.json()
            offer = RTCSessionDescription(sdp=params["sdp"], type=params["type"])

            pc = RTCPeerConnection()
            pc_id = id(pc)
            self.pcs.add(pc)
            
            logger.info(f"New WebRTC connection: {pc_id}")

            # 鉴权检查（可选，可以在DataChannel中进一步验证）
            headers = request.headers
            auth_token = headers.get('Authorization', '')
            if auth_token and not self.auth_handler.authenticate_token(auth_token):
                return web.json_response({"error": "Unauthorized"}, status=401)

            @pc.on("datachannel")
            def on_datachannel(channel: RTCDataChannel):
                logger.info(f"DataChannel event: {channel.label} (id={channel.id})")

                def setup_channel():
                    if channel.label == "audio":
                        self.audio_channels[pc_id] = channel
                    elif channel.label == "text":
                        self.text_channels[pc_id] = channel
                        # 启动发送队列处理
                        asyncio.create_task(self.process_send_queue(pc_id, channel))

                @channel.on("message")
                def on_message(message):
                    """处理接收到的消息"""
                    try:
                        if channel.label == "audio":
                            # 音频通道 (二进制 PCM/Opus)
                            if isinstance(message, bytes):
                                asyncio.create_task(
                                    self.audio_handler.handle_audio_message(message)
                                )
                        elif channel.label == "text":
                            # 文本/控制通道 (JSON)
                            try:
                                if isinstance(message, str):
                                    data = json.loads(message)
                                else:
                                    data = json.loads(message.decode('utf-8'))
                                
                                # 注入当前连接的发送队列引用，以便TextHandler可以发送回复
                                if not hasattr(self.service_manager, 'current_pc_id'):
                                    self.service_manager.current_pc_id = pc_id
                                    
                                asyncio.create_task(
                                    self.text_handler.handle_text_message(data)
                                )
                            except json.JSONDecodeError as e:
                                logger.error(f"JSON decode error: {e}")
                    except Exception as e:
                        logger.error(f"Message handler error: {e}")
                
                @channel.on("open")
                def on_open():
                    logger.info(f"DataChannel {channel.label} is now open")
                    setup_channel()
                
                @channel.on("close")
                def on_close():
                    logger.info(f"DataChannel {channel.label} closed")
                    if channel.label == "audio" and pc_id in self.audio_channels:
                        del self.audio_channels[pc_id]
                    elif channel.label == "text" and pc_id in self.text_channels:
                        del self.text_channels[pc_id]

                # 如果通道已经打开，立即设置
                if channel.readyState == "open":
                    setup_channel()

            @pc.on("connectionstatechange")
            async def on_connectionstatechange():
                logger.info(f"WebRTC connection state: {pc.connectionState}")
                if pc.connectionState == "connected":
                    logger.info(f"WebRTC connection {pc_id} established")
                elif pc.connectionState in ["failed", "closed"]:
                    logger.info(f"WebRTC connection {pc_id} closed")
                    await self.cleanup_connection(pc, pc_id)

            @pc.on("iceconnectionstatechange")
            async def on_iceconnectionstatechange():
                logger.info(f"ICE connection state: {pc.iceConnectionState}")

            # 处理 Offer
            await pc.setRemoteDescription(offer)
            
            # 创建 Answer
            answer = await pc.createAnswer()
            await pc.setLocalDescription(answer)

            return web.json_response({
                "sdp": pc.localDescription.sdp,
                "type": pc.localDescription.type
            })
            
        except Exception as e:
            logger.error(f"Error in offer handler: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def process_send_queue(self, pc_id, channel: RTCDataChannel):
        """
        从发送队列取数据并通过 DataChannel 发送回客户端
        """
        logger.info(f"Starting send queue processor for connection {pc_id}")
        try:
            while channel.readyState == "open":
                try:
                    if not self.service_manager.ws_send_queue.empty():
                        data = self.service_manager.ws_send_queue.get_nowait()
                        
                        # 判断数据类型并发送到相应通道
                        if isinstance(data, bytes):
                            # 二进制音频数据，通过audio通道发送
                            # 尝试等待音频通道就绪 (最多等待 5 秒)
                            # WebRTC DataChannel 建立可能比 Text Channel 慢，或者存在竞态
                            retry_count = 0
                            while pc_id not in self.audio_channels or self.audio_channels[pc_id].readyState != "open":
                                if retry_count >= 50: # 5秒
                                    break
                                await asyncio.sleep(0.1)
                                retry_count += 1
                            
                            if pc_id in self.audio_channels:
                                audio_channel = self.audio_channels[pc_id]
                                if audio_channel.readyState == "open":
                                    audio_channel.send(data)
                                else:
                                    logger.warning(f"Audio channel not open for {pc_id} after wait")
                            else:
                                logger.warning(f"No audio channel for {pc_id} after wait")
                        else:
                            # JSON文本数据，通过text通道发送
                            if isinstance(data, str):
                                channel.send(data)
                            else:
                                channel.send(str(data))
                    else:
                        await asyncio.sleep(0.01)  # 减少CPU占用
                except Exception as e:
                    logger.error(f"Send queue error: {e}")
                    break
        except Exception as e:
            logger.error(f"Send queue processor crashed: {e}")
        finally:
            logger.info(f"Send queue processor stopped for connection {pc_id}")

    async def cleanup_connection(self, pc: RTCPeerConnection, pc_id):
        """清理连接资源"""
        try:
            await pc.close()
            self.pcs.discard(pc)
            
            # 清理通道引用
            if pc_id in self.audio_channels:
                del self.audio_channels[pc_id]
            if pc_id in self.text_channels:
                del self.text_channels[pc_id]
            
            # 重置服务
            self.service_manager.reset_services()
            logger.info(f"Connection {pc_id} cleaned up")
        except Exception as e:
            logger.error(f"Error cleaning up connection: {e}")

    async def index(self, request):
        """提供一个简单的测试页面"""
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>WebRTC Audio Server</title>
        </head>
        <body>
            <h1>WebRTC Audio Server</h1>
            <p>Server is running. Use WebRTC client to connect.</p>
            <p>POST to /offer with SDP offer to establish connection.</p>
        </body>
        </html>
        """
        return web.Response(text=html, content_type='text/html')

    async def start_server(self):
        """启动WebRTC信令服务器"""
        app = web.Application()
        
        # 路由配置
        app.router.add_get("/", self.index)
        app.router.add_post("/offer", self.offer)
        
        # 添加CORS支持（如果需要Web客户端）
        async def cors_middleware(app, handler):
            async def middleware_handler(request):
                if request.method == "OPTIONS":
                    return web.Response(
                        headers={
                            "Access-Control-Allow-Origin": "*",
                            "Access-Control-Allow-Methods": "POST, GET, OPTIONS",
                            "Access-Control-Allow-Headers": "Content-Type, Authorization",
                        }
                    )
                response = await handler(request)
                response.headers["Access-Control-Allow-Origin"] = "*"
                return response
            return middleware_handler
        
        app.middlewares.append(cors_middleware)
        
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, self.host, self.port)
        
        logger.info(f"WebRTC Signaling Server started on http://{self.host}:{self.port}")
        logger.info("Clients should POST SDP offer to /offer endpoint")
        
        await site.start()
        
        # 保持运行
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            pass

    async def cleanup(self):
        """关闭所有连接"""
        logger.info("Shutting down WebRTC server...")
        coros = [pc.close() for pc in self.pcs]
        await asyncio.gather(*coros, return_exceptions=True)
        self.pcs.clear()
        self.audio_channels.clear()
        self.text_channels.clear()
        logger.info("WebRTC server shutdown complete")

