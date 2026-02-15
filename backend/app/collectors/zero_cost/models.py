"""
零成本采集方案的数据模型

定义搜索引擎结果和 Provider 统计信息的数据类。
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class SearchResult:
    """搜索引擎结果条目

    Args:
        url: 结果页面 URL
        title: 结果标题
        snippet: 结果摘要
        tweet_id: 从 URL 提取的推文 ID（可选）
    """

    url: str
    title: str
    snippet: str
    tweet_id: Optional[str] = None


@dataclass
class ProviderStats:
    """单个 Provider 的采集统计

    Args:
        provider_name: Provider 名称
        collected: 采集成功条数
        skipped: 跳过条数（去重/无效）
        errors: 错误条数
        error_message: 最后一次错误信息
    """

    provider_name: str
    collected: int = 0
    skipped: int = 0
    errors: int = 0
    error_message: Optional[str] = None
