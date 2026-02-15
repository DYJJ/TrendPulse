"""
日志配置模块

配置统一的日志格式、日志级别和日志轮转策略。
所有模块通过 logging.getLogger(__name__) 获取日志器后，
自动继承此处的配置。

需求: 15.2 (日志格式: 时间戳、级别、模块、消息)
需求: 15.5 (使用Python logging模块进行统一日志管理)
"""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from typing import Optional

# 默认日志格式：时间戳 - 级别 - 模块名 - 消息
DEFAULT_LOG_FORMAT = "%(asctime)s - %(levelname)s - %(name)s - %(message)s"
DEFAULT_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# 日志文件配置
DEFAULT_LOG_FILE = "trendpulse.log"
DEFAULT_MAX_BYTES = 10 * 1024 * 1024  # 10MB
DEFAULT_BACKUP_COUNT = 5


def setup_logging(
    level: Optional[str] = None,
    log_file: Optional[str] = None,
    max_bytes: int = DEFAULT_MAX_BYTES,
    backup_count: int = DEFAULT_BACKUP_COUNT,
) -> None:
    """配置全局日志系统

    设置日志格式、级别、控制台输出和文件轮转。

    Args:
        level: 日志级别字符串（DEBUG/INFO/WARNING/ERROR/CRITICAL），
               默认从环境变量 LOG_LEVEL 读取，未设置则为 INFO
        log_file: 日志文件路径，默认从环境变量 LOG_FILE 读取，
                  未设置则为 trendpulse.log
        max_bytes: 单个日志文件最大字节数，默认 10MB
        backup_count: 保留的轮转日志文件数量，默认 5 个
    """
    # 确定日志级别
    log_level_str = level or os.environ.get("LOG_LEVEL", "INFO")
    log_level = getattr(logging, log_level_str.upper(), logging.INFO)

    # 确定日志文件路径
    log_file_path = log_file or os.environ.get("LOG_FILE", DEFAULT_LOG_FILE)

    # 创建格式器
    formatter = logging.Formatter(
        fmt=DEFAULT_LOG_FORMAT,
        datefmt=DEFAULT_DATE_FORMAT,
    )

    # 获取根日志器
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # 清除已有的处理器，避免重复添加
    root_logger.handlers.clear()

    # 控制台处理器
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # 降低第三方库的日志级别，减少刷屏
    # uvicorn access log 由中间件接管，这里抑制重复输出
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    # httpx 的每个 HTTP 请求都会打印一行 INFO，改为 WARNING
    logging.getLogger("httpx").setLevel(logging.WARNING)
    # httpcore 底层连接日志
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    # 文件轮转处理器
    try:
        file_handler = RotatingFileHandler(
            filename=log_file_path,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setLevel(log_level)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
    except (OSError, PermissionError) as e:
        # 文件处理器创建失败时仅使用控制台输出
        root_logger.warning("无法创建日志文件 '%s': %s，仅使用控制台输出", log_file_path, e)
