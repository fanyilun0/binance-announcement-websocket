import os
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# 代理配置 - 优先使用环境变量，否则使用默认值
HTTP_PROXY = os.getenv('HTTP_PROXY', 'http://127.0.0.1:7890')
HTTPS_PROXY = os.getenv('HTTPS_PROXY', 'http://127.0.0.1:7890')

# WebSocket连接配置
WEBSOCKET_PROXY_HOST = "127.0.0.1"
WEBSOCKET_PROXY_PORT = 7890
