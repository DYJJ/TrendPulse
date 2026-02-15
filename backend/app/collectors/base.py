"""
采集引擎基类模块

提供数据采集的基础架构，包括：
- BaseCollector: 单个数据源采集器的抽象基类
- CollectionEngine: 协调多数据源采集的引擎类

需求: 1.2 (将采集任务加入处理队列), 15.1 (异常捕获和日志记录)
"""

import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from backend.app.models.data_models import (
    CollectionParams,
    DataSource,
    RawPost,
    ValidationResult,
)
from backend.app.utils.validators import validate_collection_params

logger = logging.getLogger(__name__)


@dataclass
class CollectionResult:
    """采集结果

    Args:
        posts: 采集到的帖子列表
        errors: 各数据源的错误信息
        source_counts: 各数据源的采集数量
    """

    posts: List[RawPost] = field(default_factory=list)
    errors: Dict[str, str] = field(default_factory=dict)
    source_counts: Dict[str, int] = field(default_factory=dict)


class BaseCollector(ABC):
    """数据源采集器抽象基类

    所有平台采集器（Reddit、YouTube、X）都必须继承此类，
    并实现 collect 方法。
    """

    source: DataSource

    @abstractmethod
    async def collect(
        self, keyword: str, limit: int, language: str = "en"
    ) -> List[RawPost]:
        """从数据源采集帖子

        Args:
            keyword: 搜索关键词
            limit: 采集条数限制
            language: 语言代码

        Returns:
            采集到的帖子列表
        """
        pass

    @abstractmethod
    async def close(self) -> None:
        """释放采集器资源（如浏览器实例）"""
        pass


class CollectionEngine:
    """采集引擎

    协调多个数据源的采集任务，支持异步并发采集。
    单个数据源失败不影响其他数据源的采集。

    需求: 1.2, 15.1
    """

    def __init__(self) -> None:
        """初始化采集引擎，注册可用的采集器"""
        self._collectors: Dict[DataSource, BaseCollector] = {}

    def register_collector(
        self, source: DataSource, collector: BaseCollector
    ) -> None:
        """注册数据源采集器

        Args:
            source: 数据源类型
            collector: 对应的采集器实例
        """
        self._collectors[source] = collector

    def validate_params(
        self, keyword: str, language: str, limit: int
    ) -> ValidationResult:
        """验证采集参数

        Args:
            keyword: 搜索关键词
            language: 语言代码
            limit: 条数限制

        Returns:
            验证结果
        """
        return validate_collection_params(keyword, language, limit)

    async def collect(
        self,
        keyword: str,
        language: str,
        limit: int,
        sources: List[DataSource],
    ) -> CollectionResult:
        """执行多数据源并发采集

        对每个指定的数据源并发执行采集任务。
        单个数据源失败时记录错误，不影响其他数据源。

        Args:
            keyword: 搜索关键词
            language: 语言代码 (en/zh)
            limit: 每个数据源的采集条数限制
            sources: 要采集的数据源列表

        Returns:
            包含所有数据源采集结果的 CollectionResult
        """
        # 先验证参数
        validation = self.validate_params(keyword, language, limit)
        if not validation.is_valid:
            logger.error("采集参数验证失败: %s", validation.error)
            result = CollectionResult()
            result.errors["validation"] = validation.error or "参数验证失败"
            return result

        result = CollectionResult()

        # 为每个数据源创建采集协程
        tasks = []
        task_sources = []
        for source in sources:
            collector = self._collectors.get(source)
            if collector is None:
                logger.warning("未注册的数据源: %s，跳过", source.value)
                result.errors[source.value] = f"未注册的数据源: {source.value}"
                continue
            tasks.append(collector.collect(keyword, limit, language))
            task_sources.append(source)

        if not tasks:
            logger.warning("没有可用的采集器")
            return result

        # 并发执行所有采集任务
        outcomes = await asyncio.gather(*tasks, return_exceptions=True)

        for source, outcome in zip(task_sources, outcomes):
            if isinstance(outcome, Exception):
                error_msg = f"{source.value} 采集失败: {outcome}"
                logger.error(error_msg)
                result.errors[source.value] = error_msg
                result.source_counts[source.value] = 0
            else:
                posts: List[RawPost] = outcome
                result.posts.extend(posts)
                result.source_counts[source.value] = len(posts)
                logger.info(
                    "%s 采集完成，获取 %d 条数据", source.value, len(posts)
                )

        return result

    async def close(self) -> None:
        """释放所有采集器资源"""
        for source, collector in self._collectors.items():
            try:
                await collector.close()
            except Exception as e:
                logger.error("关闭 %s 采集器失败: %s", source.value, e)
