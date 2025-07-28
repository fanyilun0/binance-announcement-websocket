# Binance Announcement Monitor

这是一个使用Python实现的币安公告监控工具。它通过WebSocket实时监控币安的英文公告频道。

## 功能特点

- 实时监控币安公告
- 支持自定义通知处理
- 自动重连机制
- 异常处理和日志记录

## 安装

1. 克隆仓库:
```bash
git clone https://github.com/yourusername/binance-announcement-websocket.git
cd binance-announcement-websocket
```

2. 安装依赖:
```bash
pip install -r requirements.txt
```

## 使用方法

1. 运行监控程序:
```bash
python main.py
```

## 配置说明

在`.env`文件中配置以下参数:

```
LOG_LEVEL=INFO
```

## 许可证

MIT
