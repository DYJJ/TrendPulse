"""
零成本采集方案的通用工具函数

提供 URL 解析、查询构造、ID 生成、随机延迟和 User-Agent 选择等功能。
"""

import asyncio
import random
import re
from typing import Optional

from backend.app.collectors.zero_cost.constants import (
    SEARCH_DELAY_MIN,
    SEARCH_DELAY_MAX,
    USER_AGENTS,
)

# 匹配 x.com 或 twitter.com 推文 URL 的正则表达式
_TWEET_URL_PATTERN = re.compile(
    r"https?://(?:www\.)?(?:x\.com|twitter\.com)/[^/]+/status/(\d+)"
)


def extract_tweet_id(url: str) -> Optional[str]:
    """从推文 URL 中提取推文 ID

    支持 x.com 和 twitter.com 两种域名格式。
    URL 格式：https://x.com/{user}/status/{tweet_id}

    Args:
        url: 推文 URL 字符串

    Returns:
        推文 ID 数字字符串，无法提取时返回 None
    """
    match = _TWEET_URL_PATTERN.search(url)
    if match:
        return match.group(1)
    return None


def build_search_query(keyword: str) -> str:
    """构造 site:x.com 搜索查询

    Args:
        keyword: 搜索关键词

    Returns:
        包含 site:x.com 前缀的搜索查询字符串
    """
    return f"site:x.com {keyword}"


def generate_raw_post_id(prefix: str, external_id: str) -> str:
    """生成 RawPost 唯一标识符

    格式：{prefix}_{external_id}

    Args:
        prefix: 来源前缀（tw/bsky/rss）
        external_id: 外部平台 ID

    Returns:
        格式化的唯一标识符字符串
    """
    return f"{prefix}_{external_id}"


async def random_delay(
    min_s: float = SEARCH_DELAY_MIN,
    max_s: float = SEARCH_DELAY_MAX,
) -> None:
    """异步随机延迟，用于限流保护

    Args:
        min_s: 最小延迟秒数
        max_s: 最大延迟秒数
    """
    delay = random.uniform(min_s, max_s)
    await asyncio.sleep(delay)


def random_user_agent() -> str:
    """从 User-Agent 池中随机选择一个

    Returns:
        随机选取的 User-Agent 字符串
    """
    return random.choice(USER_AGENTS)
