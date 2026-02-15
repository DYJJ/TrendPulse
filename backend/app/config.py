"""
配置管理模块

从环境变量读取所有系统配置，并在启动时验证必需的配置项。
缺失必需环境变量时抛出清晰的错误信息。

需求: 12.1 (从环境变量读取敏感配置)
需求: 12.4 (缺失环境变量时启动报错并提示变量名)
"""

import os
import logging
from dataclasses import dataclass, field
from typing import List, Optional

from dotenv import load_dotenv

# 加载 .env 文件中的环境变量
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

logger = logging.getLogger(__name__)


class ConfigurationError(Exception):
    """配置错误异常

    当必需的环境变量缺失或配置值无效时抛出。
    """

    pass


@dataclass
class Config:
    """系统配置类

    从环境变量读取所有配置项，提供默认值和启动时验证。

    必需的环境变量:
        - LLM_API_KEY: 大语言模型API密钥

    可选的环境变量（有默认值）:
        - LLM_API_BASE_URL: API基础URL
        - LLM_MODEL: 模型名称
        - APP_HOST: 应用监听地址
        - APP_PORT: 应用监听端口
        - APP_DEBUG: 调试模式
        - DATABASE_URL: 数据库连接URL
        - TOKEN_WARNING_THRESHOLD: Token使用量警告阈值
    """

    # LLM配置
    llm_api_key: str = ""
    llm_api_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-3.5-turbo"
    llm_api_style: str = "openai"  # "openai" 或 "anthropic"

    # Reddit API配置（优先使用API，未配置时降级为爬虫）
    reddit_client_id: str = ""
    reddit_client_secret: str = ""
    reddit_user_agent: str = "TrendPulse/1.0"

    # YouTube Data API配置（优先使用API，未配置时降级为爬虫）
    youtube_api_key: str = ""

    # Twitter/X API配置（优先使用API，未配置时降级为爬虫）
    twitter_bearer_token: str = ""

    # 应用配置
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    app_debug: bool = False

    # 数据库配置
    database_url: str = "postgresql://user:password@localhost:5432/trendpulse"

    # Token成本控制（大规模采集场景下阈值需要足够大）
    token_warning_threshold: int = 10000000

    # 采集批次大小（大规模采集时每批写入数据库的条数）
    collection_batch_size: int = 500

    # 必需的环境变量列表
    _required_vars: List[str] = field(
        default_factory=lambda: ["LLM_API_KEY"],
        init=False,
        repr=False,
    )

    @classmethod
    def from_env(cls) -> "Config":
        """从环境变量创建配置实例

        读取所有环境变量并构建Config对象。

        Returns:
            Config: 配置实例

        Raises:
            ConfigurationError: 当必需的环境变量缺失时
        """
        config = cls(
            llm_api_key=os.environ.get("LLM_API_KEY", ""),
            llm_api_base_url=os.environ.get(
                "LLM_API_BASE_URL", "https://api.openai.com/v1"
            ),
            llm_model=os.environ.get("LLM_MODEL", "gpt-3.5-turbo"),
            llm_api_style=os.environ.get("LLM_API_STYLE", "openai"),
            reddit_client_id=os.environ.get("REDDIT_CLIENT_ID", ""),
            reddit_client_secret=os.environ.get("REDDIT_CLIENT_SECRET", ""),
            reddit_user_agent=os.environ.get(
                "REDDIT_USER_AGENT", "TrendPulse/1.0"
            ),
            youtube_api_key=os.environ.get("YOUTUBE_API_KEY", ""),
            twitter_bearer_token=os.environ.get("TWITTER_BEARER_TOKEN", ""),
            app_host=os.environ.get("APP_HOST", "0.0.0.0"),
            app_port=int(os.environ.get("APP_PORT", "8000")),
            app_debug=os.environ.get("APP_DEBUG", "false").lower()
            in ("true", "1", "yes"),
            database_url=os.environ.get(
                "DATABASE_URL", "postgresql://user:password@localhost:5432/trendpulse"
            ),
            token_warning_threshold=int(
                os.environ.get("TOKEN_WARNING_THRESHOLD", "10000000")
            ),
            collection_batch_size=int(
                os.environ.get("COLLECTION_BATCH_SIZE", "500")
            ),
        )
        return config

    def validate(self) -> None:
        """验证配置完整性

        检查所有必需的环境变量是否已设置。
        缺失时抛出ConfigurationError并列出所有缺失的变量名。

        Raises:
            ConfigurationError: 当必需的环境变量缺失时，
                错误信息包含所有缺失变量名的列表
        """
        missing: List[str] = []

        for var_name in self._required_vars:
            env_value = os.environ.get(var_name)
            if not env_value or not env_value.strip():
                missing.append(var_name)

        if missing:
            missing_str = ", ".join(missing)
            msg = f"缺失必需的环境变量: {missing_str}"
            logger.critical(msg)
            raise ConfigurationError(msg)

        # 验证端口范围
        if not (1 <= self.app_port <= 65535):
            msg = f"APP_PORT 值无效: {self.app_port}，必须在1-65535之间"
            logger.critical(msg)
            raise ConfigurationError(msg)

        # 验证Token阈值为正数
        if self.token_warning_threshold < 0:
            msg = (
                f"TOKEN_WARNING_THRESHOLD 值无效: "
                f"{self.token_warning_threshold}，必须为非负整数"
            )
            logger.critical(msg)
            raise ConfigurationError(msg)

        logger.info("配置验证通过")


# 全局配置实例（延迟初始化）
_config: Optional[Config] = None


def get_config() -> Config:
    """获取全局配置实例

    首次调用时从环境变量加载配置。

    Returns:
        Config: 全局配置实例
    """
    global _config
    if _config is None:
        _config = Config.from_env()
    return _config


def reset_config() -> None:
    """重置全局配置实例

    主要用于测试场景，强制下次调用get_config时重新加载。
    """
    global _config
    _config = None
