import logging
import sys
from config import AGENT_NAME, LOG_LEVEL

def setup_logger(name: str = AGENT_NAME) -> logging.Logger:
    """
    配置标准化的日志记录器
    符合系统开发规范：标准化日志模块
    """
    logger = logging.getLogger(name)
    
    # 设置日志级别
    try:
        level = getattr(logging, LOG_LEVEL)
    except AttributeError:
        level = logging.INFO
    logger.setLevel(level)

    # 避免重复添加 Handler
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger
