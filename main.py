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
from config import HTTP_PROXY

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
        
        # 增强的环境变量检查和日志
        logger.info("正在初始化 BinanceAnnouncementMonitor...")
        if not self.api_key:
            logger.error("BINANCE_API_KEY 环境变量未设置")
            raise ValueError("请在.env文件中设置BINANCE_API_KEY")
        if not self.api_secret:
            logger.error("BINANCE_SECRET_KEY 环境变量未设置")
            raise ValueError("请在.env文件中设置BINANCE_SECRET_KEY")
        
        logger.info(f"API Key: {self.api_key[:8]}...")  # 只显示前8位用于调试
        logger.info("API Secret 已设置")
        
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
        """定期发送PING消息（已废弃，使用aiohttp内置heartbeat）"""
        pass

    def clean_announcement_body(self, body: str) -> str:
        """清理公告内容中的固定开场白"""
        if not body:
            return ""
            
        # 定义需要移除的固定文本
        opening_text = "This is a general announcement."
        opening_text_2 = "Products and services referred to here may not be available in your region."
        
        body = body.replace(opening_text, '').replace(opening_text_2, '')

        return body

    def parse_announcement(self, data_str: str) -> Dict:
        """解析公告数据"""
        try:
            logger.debug('data_str: ' + data_str + '\n')
            data = json.loads(data_str)
            logger.debug(' data: ' + str(data) + '\n')
            
            # 清理公告内容
            body = self.clean_announcement_body(data.get('body', ''))
            
            return {
                'catalogId': data.get('catalogId'),
                'catalogName': data.get('catalogName'),
                'publishDate': datetime.fromtimestamp(
                    int(data.get('publishDate', 0)) / 1000
                ).strftime('%Y-%m-%d %H:%M:%S'),
                'title': data.get('title'),
                'body': body
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
                logger.info(f"内容: {announcement.get('body').slice(0, 1000)}")
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
            
            body = self.clean_announcement_body(body)

            content = (
                f"📢 币安新公告\n"
                f"📌 分类: {announcement.get('catalogName', 'N/A')}\n"
                f"📑 标题: {title}\n"
                f"⏰ 时间: {announcement.get('publishDate', 'N/A')}\n"
                f"📄 内容: {body}\n"
            )
            
            # 发送消息
            await send_message_async(content)
            
        except Exception as e:
            logger.error(f"发送Webhook消息失败: {e}")

    async def subscribe(self, websocket) -> None:
        """订阅公告频道（websockets库）"""
        subscribe_message = {
            "command": "SUBSCRIBE",
            "value": "com_announcement_en"  # 使用正确的topic
        }
        await websocket.send(json.dumps(subscribe_message))
        response = await websocket.recv()
        logger.info(f"订阅响应: {response}")
    
    async def subscribe_aiohttp(self, websocket) -> None:
        """订阅公告频道（aiohttp库）"""
        subscribe_message = {
            "command": "SUBSCRIBE",
            "value": "com_announcement_en"  # 使用正确的topic
        }
        await websocket.send_str(json.dumps(subscribe_message))
        logger.info("已发送订阅消息")

    async def setup_session(self):
        """设置aiohttp session"""
        if self.session is None:
            # 配置代理连接器
            connector = aiohttp.TCPConnector()
            self.session = aiohttp.ClientSession(
                connector=connector,
                timeout=aiohttp.ClientTimeout(total=60)
            )
    
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
            logger.info("开始连接到 Binance WebSocket API...")
            
            while True:
                try:
                    # 准备连接URL和headers
                    url = self.get_connection_url()
                    headers = {"X-MBX-APIKEY": self.api_key}
                    logger.info(f"尝试连接到: {url[:50]}...")  # 只显示URL前50个字符
                    
                    # 使用aiohttp的WebSocket客户端支持代理
                    async with self.session.ws_connect(
                        url,
                        headers=headers,
                        proxy=HTTP_PROXY,
                        heartbeat=self.ping_interval
                    ) as websocket:
                        logger.info("已连接到Binance WebSocket API")
                        
                        # 订阅频道
                        await self.subscribe_aiohttp(websocket)
                        
                        try:
                            async for msg in websocket:
                                if msg.type == aiohttp.WSMsgType.TEXT:
                                    await self.handle_message(json.loads(msg.data))
                                elif msg.type == aiohttp.WSMsgType.ERROR:
                                    logger.error(f'WebSocket错误: {websocket.exception()}')
                                    break
                        except Exception as e:
                            logger.error(f"接收消息时出错: {e}")
                                
                except aiohttp.ClientConnectorError:
                    logger.warning("WebSocket连接失败，准备重连...")
                except Exception as e:
                    logger.error(f"发生错误: {e}", exc_info=True)  # 添加详细错误堆栈
                
                logger.info(f"{self.reconnect_delay}秒后尝试重连...")
                await asyncio.sleep(self.reconnect_delay)
                
        finally:
            # 清理session
            await self.cleanup_session()

    async def run(self) -> None:
        """启动监控"""
        try:
            await self.connect_and_listen()
        except KeyboardInterrupt:
            logger.info("程序已停止")
        except Exception as e:
            logger.error(f"程序运行出错: {e}", exc_info=True)

async def main():
    """程序主入口"""
    logger.info("========== BinanceAnnouncementMonitor 启动 ==========")
    logger.info("正在初始化程序...")
    
    try:
        monitor = BinanceAnnouncementMonitor()
        await monitor.run()
        
    except Exception as e:
        logger.error(f"程序在主函数中遇到无法恢复的错误: {e}", exc_info=True)
        # 发送启动失败通知（静默失败）
        try:
            await send_message_async("程序启动失败", f"程序启动时遇到严重错误: {e}")
        except Exception as e:
            logger.warning(f"发送启动失败通知失败: {e}")

if __name__ == "__main__":
    asyncio.run(main())