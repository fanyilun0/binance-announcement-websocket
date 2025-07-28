import asyncio
import json
import logging
import os
import uuid
import hmac
import hashlib
from datetime import datetime
from typing import Dict, Any
from urllib.parse import urlencode

import websockets
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# 配置日志
logging_level = os.getenv('LOG_LEVEL', 'INFO')
logging.basicConfig(
    level=logging_level,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class BinanceAnnouncementMonitor:
    def __init__(self):
        self.api_key = os.getenv('BINANCE_API_KEY')
        self.api_secret = os.getenv('BINANCE_SECRET_KEY')
        if not self.api_key or not self.api_secret:
            raise ValueError("请在.env文件中设置BINANCE_API_KEY和BINANCE_SECRET_KEY")
        
        self.base_url = "wss://api.binance.com/sapi/wss"
        self.reconnect_delay = 5  # 重连延迟（秒）
        self.last_announcement_id = None
        self.ping_interval = 30  # PING间隔（秒）
        self.recv_window = 30000  # 接收窗口（毫秒）
        self.ping_timeout = 60  # PING超时时间（秒）
        
        # 设置更详细的日志级别用于调试
        if os.getenv('DEBUG'):
            logger.setLevel(logging.DEBUG)

    def generate_signature(self, params: Dict[str, Any]) -> str:
        """生成签名"""
        # 确保所有值都转换为字符串
        params = {k: str(v) for k, v in params.items()}
        
        # 按字母顺序排序并生成查询字符串
        query_string = '&'.join([f"{k}={v}" for k, v in sorted(params.items())])
        
        logger.debug(f"签名前的字符串: {query_string}")
        
        # 使用HMAC SHA256生成签名
        signature = hmac.new(
            self.api_secret.encode('utf-8'),
            query_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        logger.debug(f"生成的签名: {signature}")
        return signature

    def get_connection_url(self) -> str:
        """生成带签名的连接URL"""
        # 准备参数 - 注意顺序并确保值的类型正确
        params = {
            'random': uuid.uuid4().hex[:32],
            'recvWindow': str(self.recv_window),
            'timestamp': str(int(datetime.now().timestamp() * 1000)),
            'topic': 'com_announcement_en'  # 使用正确的topic
        }
        
        # 生成签名
        signature = self.generate_signature(params)
        
        # 添加签名到参数中
        params['signature'] = signature
        
        # 构建URL - 使用urlencode确保正确的URL编码
        query_string = urlencode(params)
        url = f"{self.base_url}?{query_string}"
        
        logger.debug(f"最终URL: {url}")
        return url

    async def ping_server(self, websocket) -> None:
        """定期发送PING消息"""
        while True:
            try:
                # 发送空payload的PING
                await websocket.ping()
                await asyncio.sleep(self.ping_interval)
            except Exception as e:
                logger.error(f"发送PING消息时出错: {e}")
                break

    async def handle_message(self, message: Dict[str, Any]) -> None:
        """处理接收到的消息"""
        try:
            # 处理订阅响应
            if message.get('type') == 'COMMAND':
                logger.info(f"收到命令响应: {message}")
                return
                
            # 处理公告消息
            data = message.get('data', {})
            announcement_id = data.get('id')
            
            # 避免重复处理相同的公告
            if announcement_id == self.last_announcement_id:
                return
            
            self.last_announcement_id = announcement_id
            
            # 格式化时间
            timestamp = data.get('publishDate', 0)
            publish_date = datetime.fromtimestamp(timestamp / 1000).strftime('%Y-%m-%d %H:%M:%S')
            
            # 打印公告信息
            logger.info(f"新公告: {data.get('title')}")
            logger.info(f"发布时间: {publish_date}")
            logger.info(f"链接: {data.get('url')}")
            logger.info("-" * 50)
            
        except Exception as e:
            logger.error(f"处理消息时出错: {e}")

    async def subscribe(self, websocket) -> None:
        """订阅公告频道"""
        subscribe_message = {
            "command": "SUBSCRIBE",
            "value": "com_announcement_en"  # 使用正确的topic
        }
        await websocket.send(json.dumps(subscribe_message))
        response = await websocket.recv()
        logger.info(f"订阅响应: {response}")

    async def connect_and_listen(self) -> None:
        """建立连接并监听消息"""
        while True:
            try:
                # 准备连接URL和headers
                url = self.get_connection_url()
                headers = {"X-MBX-APIKEY": self.api_key}
                
                async with websockets.connect(
                    url, 
                    extra_headers=headers,
                    ping_interval=None,  # 禁用自动ping，我们使用自己的ping逻辑
                    ping_timeout=self.ping_timeout
                ) as websocket:
                    logger.info("已连接到Binance WebSocket API")
                    
                    # 启动PING任务
                    ping_task = asyncio.create_task(self.ping_server(websocket))
                    
                    # 订阅频道
                    await self.subscribe(websocket)
                    
                    try:
                        while True:
                            message = await websocket.recv()
                            await self.handle_message(json.loads(message))
                    except Exception as e:
                        logger.error(f"接收消息时出错: {e}")
                        ping_task.cancel()
                        
            except websockets.exceptions.ConnectionClosed:
                logger.warning("WebSocket连接已关闭，准备重连...")
            except Exception as e:
                logger.error(f"发生错误: {e}")
            
            logger.info(f"{self.reconnect_delay}秒后尝试重连...")
            await asyncio.sleep(self.reconnect_delay)

    def run(self) -> None:
        """启动监控"""
        try:
            asyncio.run(self.connect_and_listen())
        except KeyboardInterrupt:
            logger.info("程序已停止")

if __name__ == "__main__":
    monitor = BinanceAnnouncementMonitor()
    monitor.run() 