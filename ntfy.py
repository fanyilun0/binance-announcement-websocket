import asyncio
import aiohttp
import logging
import os
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

logger = logging.getLogger(__name__)

async def send_ntfy_notification(title, message, priority="default", tags=None):
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
    ntfy_topic = os.getenv('NTFY_TOPIC')
    
    if not ntfy_url or not ntfy_topic:
        logger.warning("未配置NTFY_URL或NTFY_TOPIC，无法发送通知")
        return False
    
    headers = {
        "Title": title,
        "Priority": priority,
    }
    
    if tags:
        headers["Tags"] = ",".join(tags)
    
    url = f"{ntfy_url}/{ntfy_topic}"
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=message, headers=headers) as response:
                if response.status == 200:
                    logger.info(f"通知发送成功: {title}")
                    return True
                else:
                    logger.error(f"通知发送失败: {response.status}, {await response.text()}")
                    return False
    except Exception as e:
        logger.error(f"发送通知时出错: {e}")
        return False
