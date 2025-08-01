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
import aiohttp
from webhook import send_message_async

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
        
        # 配置文件日志
        self.setup_logging()
        self.session = None  # aiohttp session
        
    def setup_logging(self):
        """配置日志处理"""
        # 创建logs目录
        if not os.path.exists('logs'):
            os.makedirs('logs')
            
        # 获取当前时间作为文件名
        current_time = datetime.now().strftime('%Y%m%d_%H%M%S')
        log_file = f'logs/binance_announcement_{current_time}.log'
        
        # 创建文件处理器
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setFormatter(logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        ))
        
        # 添加到logger
        logger.addHandler(file_handler)
        
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

    def parse_announcement(self, data_str: str) -> Dict:
        """解析公告数据"""
        try:
            data = json.loads(data_str)
            return {
                'catalogId': data.get('catalogId'),
                'catalogName': data.get('catalogName'),
                'publishDate': datetime.fromtimestamp(
                    int(data.get('publishDate', 0)) / 1000
                ).strftime('%Y-%m-%d %H:%M:%S'),
                'title': data.get('title'),
                'body': data.get('body'),
                'disclaimer': data.get('disclaimer')
            }
        except Exception as e:
            logger.error(f"解析公告数据失败: {e}")
            return {}

    async def handle_message(self, message: Dict[str, Any]) -> None:
        """处理接收到的消息"""
        try:
            # 处理订阅响应
            if message.get('type') == 'COMMAND':
                logger.info(f"收到命令响应: {message}")
                return
            
            # 处理公告消息
            if message.get('type') == 'DATA' and message.get('topic') == 'com_announcement_en':
                data_str = message.get('data', '{}')
                announcement = self.parse_announcement(data_str)
                
                if not announcement:
                    return
                
                # 避免重复处理相同的公告
                announcement_id = announcement.get('catalogId')
                if announcement_id == self.last_announcement_id:
                    return
                
                self.last_announcement_id = announcement_id
                
                # 打印公告信息
                logger.info("收到新公告:")
                logger.info(f"分类: {announcement.get('catalogName')}")
                logger.info(f"标题: {announcement.get('title')}")
                logger.info(f"发布时间: {announcement.get('publishDate')}")
                logger.info(f"内容: {announcement.get('body')}")
                logger.info(f"免责声明: {announcement.get('disclaimer')}")
                logger.info("-" * 50)
                
                # 保存公告到文件
                self.save_announcement(announcement)
                
                # 发送到Webhook
                await self.send_to_webhook(announcement)
                
        except Exception as e:
            logger.error(f"处理消息时出错: {e}")

    def save_announcement(self, announcement: Dict) -> None:
        """保存公告到JSON文件"""
        try:
            # 创建json目录
            json_dir = 'json'
            if not os.path.exists(json_dir):
                os.makedirs(json_dir)
            
            # 使用时间戳和标题创建文件名
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            title = announcement.get('title', 'untitled')
            
            # 移除文件名中的非法字符
            title = "".join(c for c in title if c.isalnum() or c in (' ', '-', '_')).strip()
            
            # 按日期创建子目录
            date_dir = os.path.join(json_dir, datetime.now().strftime('%Y%m%d'))
            if not os.path.exists(date_dir):
                os.makedirs(date_dir)
            
            # 构建完整的文件路径
            filename = f'{timestamp}_{title[:50]}.json'
            filepath = os.path.join(date_dir, filename)
            
            # 保存为JSON文件，使用缩进格式化
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(announcement, f, ensure_ascii=False, indent=2)
                
            logger.info(f"公告已保存到文件: {filepath}")
            
        except Exception as e:
            logger.error(f"保存公告到文件时出错: {e}")

    async def send_to_webhook(self, announcement: Dict) -> None:
        """发送公告到Webhook"""
        try:
            if not self.session:
                await self.setup_session()
            
            # 格式化消息内容
            title = announcement.get('title', 'N/A')
            body = announcement.get('body', 'N/A')
            
            # 处理正文内容，移除多余的换行和空格
            body = ' '.join(body.split('\n')[:3])  # 只取前三行
            if len(body) > 500:
                body = body[:497] + "..."
            
            content = (
                f"📢 币安新公告\n"
                f"━━━━━━━━━━\n"
                f"📌 分类: {announcement.get('catalogName', 'N/A')}\n"
                f"📑 标题: {title}\n"
                f"⏰ 时间: {announcement.get('publishDate', 'N/A')}\n"
                f"📄 内容: {body}\n"
                f"━━━━━━━━━━"
            )
            
            # 确保content是字符串类型
            content = str(content)
            
            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json"
            }
            
            # 发送消息
            success = await send_message_async(content)
            if success:
                logger.info("Webhook消息发送成功")
            else:
                logger.error("Webhook消息发送失败")
            
        except Exception as e:
            logger.error(f"发送Webhook消息失败: {e}")

    async def subscribe(self, websocket) -> None:
        """订阅公告频道"""
        subscribe_message = {
            "command": "SUBSCRIBE",
            "value": "com_announcement_en"  # 使用正确的topic
        }
        await websocket.send(json.dumps(subscribe_message))
        response = await websocket.recv()
        logger.info(f"订阅响应: {response}")

    async def setup_session(self):
        """设置aiohttp session"""
        if self.session is None:
            self.session = aiohttp.ClientSession()
    
    async def cleanup_session(self):
        """清理aiohttp session"""
        if self.session:
            await self.session.close()
            self.session = None

    async def connect_and_listen(self) -> None:
        """建立连接并监听消息"""
        try:
            # 设置aiohttp session
            await self.setup_session()
            
            while True:
                try:
                    # 准备连接URL和headers
                    url = self.get_connection_url()
                    headers = {"X-MBX-APIKEY": self.api_key}
                    
                    async with websockets.connect(
                        url, 
                        extra_headers=headers,
                        ping_interval=None,
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
                            if ping_task:
                                ping_task.cancel()
                                
                except websockets.exceptions.ConnectionClosed:
                    logger.warning("WebSocket连接已关闭，准备重连...")
                except Exception as e:
                    logger.error(f"发生错误: {e}")
                
                logger.info(f"{self.reconnect_delay}秒后尝试重连...")
                await asyncio.sleep(self.reconnect_delay)
                
        finally:
            # 清理session
            await self.cleanup_session()

    def run(self) -> None:
        """启动监控"""
        try:
            # 使用asyncio运行
            asyncio.run(self.connect_and_listen())
        except KeyboardInterrupt:
            logger.info("程序已停止")
        except Exception as e:
            logger.error(f"程序运行出错: {e}")

if __name__ == "__main__":
    monitor = BinanceAnnouncementMonitor()
    monitor.run() 