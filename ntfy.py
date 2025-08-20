import asyncio
import aiohttp
import logging
import os
from typing import Optional, List
from urllib.parse import urlparse
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

logger = logging.getLogger(__name__)

def is_ntfy_sh_url(url: str) -> bool:
    """
    判断是否为ntfy.sh的URL
    """
    parsed = urlparse(url)
    return parsed.netloc == 'ntfy.sh'

async def send_ntfy_notification(
    title: str, 
    message: str, 
    priority: str = "default", 
    tags: Optional[List[str]] = None
) -> bool:
    """
    发送通知到ntfy服务
    
    Args:
        title (str): 通知标题
        message (str): 通知内容
        priority (str): 优先级 (default, low, high, urgent)
        tags (list): 标签列表
    
    Returns:
        bool: 是否发送成功
    """
    ntfy_url = os.getenv('NTFY_URL')
    if not ntfy_url:
        logger.error("未配置NTFY_URL环境变量")
        return False
        
    # 转换tags为字符串
    tags_str = ",".join(tags) if tags else ""
    
    try:
        async with aiohttp.ClientSession() as session:
            if is_ntfy_sh_url(ntfy_url):
                # ntfy.sh方式
                headers = {
                    "Title": title,
                    "Priority": priority,
                    "Tags": tags_str
                }
                async with session.post(ntfy_url, data=message, headers=headers) as response:
                    success = response.status == 200
            else:
                # API接口方式
                payload = {
                    "title": title,
                    "message": message,
                    "priority": priority,
                    "tags": tags_str
                }
                async with session.post(ntfy_url, json=payload) as response:
                    success = response.status == 200
                    
            if success:
                logger.info(f"通知发送成功: {title}")
            else:
                logger.error(f"通知发送失败: {response.status}, {await response.text()}")
            return success
            
    except Exception as e:
        logger.error(f"发送通知时出错: {e}")
        return False
