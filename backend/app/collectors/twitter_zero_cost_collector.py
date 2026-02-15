"""
零成本 Twitter 数据采集器

整合多个免费、无需认证的公开渠道（搜索引擎、Syndication API、Bluesky、RSS），
实现零成本、零账号的 Twitter/社交媒体数据采集。按优先级编排 Provider，
支持降级、去重和配额传递。

通过环境变量 TWITTER_ZERO_COST_ENABLED 控制启用（默认 true）。
"""

import logging
import os
from datetime import datetime
from typing import AsyncGenerator, Callable, List, Optional, Set

from backend.app.collectors.zero_cost.constants import BATCH_SIZE
from backend.app.collectors.zero_cost.models import ProviderStats
from backend.app.collectors.zero_cost.syndication_provider import SyndicationProvider
from backend.app.collectors.zero_cost.search_engine_provider import SearchEngineProvider
from backend.app.collectors.zero_cost.bluesky_provider import BlueskyProvider
from backend.app.collectors.zero_cost.rss_provider import RSSProvider
from backend.app.models.data_models import RawPost

logger = logging.getLogger(__name__)


def is_zero_cost_enabled() -> bool:
    """检查零成本采集器是否启用

    通过环境变量 TWITTER_ZERO_COST_ENABLED 控制，默认启用。

    Returns:
        True 表示启用，False 表示禁用
    """
    value = os.environ.get("TWITTER_ZERO_COST_ENABLED", "true").lower()
    return value not in ("false", "0", "no")


class ZeroCostCollector:
    """零成本 Twitter 数据采集器

    编排多个免费 Provider 的采集流程，支持降级和去重。
    Provider 按优先级依次执行：SearchEngine → Bluesky → RSS。
    每个 Provider 失败时自动降级到下一个，所有 Provider 共享
    seen_ids 去重集合和配额。
    """

    def __init__(
        self,
        batch_delay: float = 2.0,
        proxy: Optional[str] = None,
    ) -> None:
        """初始化采集器及所有 Provider

        Args:
            batch_delay: 批次间延迟秒数
            proxy: 代理地址（可选）
        """
        self._batch_delay = batch_delay
        self._proxy = proxy

        # 初始化 SyndicationProvider（被 SearchEngine 和 RSS 共用）
        self._syndication = SyndicationProvider(proxy=proxy)

        # 初始化各 Provider
        self._search_engine = SearchEngineProvider(syndication=self._syndication, proxy=proxy)
        self._bluesky = BlueskyProvider(proxy=proxy)
        self._rss = RSSProvider(proxy=proxy)

    async def collect(
        self,
        keyword: str,
        limit: int,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        language: str = "en",
        on_progress: Optional[Callable[[int], None]] = None,
    ) -> AsyncGenerator[List[RawPost], None]:
        """批量采集数据，每 500 条 yield 一批

        按优先级依次执行 Provider（SearchEngine → Bluesky → RSS），
        每个 Provider 失败时记录错误并继续下一个。使用 seen_ids
        跨 Provider 去重，配额随采集量递减。

        Args:
            keyword: 搜索关键词
            limit: 采集条数上限
            start_date: 起始日期（可选，保持接口兼容）
            end_date: 结束日期（可选，保持接口兼容）
            language: 语言代码（默认 en）
            on_progress: 进度回调函数，参数为已采集条数

        Yields:
            List[RawPost]: 每次 yield 一批数据（最多 500 条）

        Raises:
            RuntimeError: 所有 Provider 均失败且未采集到任何数据
        """
        seen_ids: Set[str] = set()
        total_collected = 0
        provider_stats: List[ProviderStats] = []

        # Provider 列表，按优先级排序
        providers = [
            ("SearchEngine", self._collect_from_search_engine),
            ("Bluesky", self._collect_from_bluesky),
            ("RSS", self._collect_from_rss),
        ]

        for provider_name, collect_func in providers:
            if total_collected >= limit:
                break

            remaining = limit - total_collected
            stats = ProviderStats(provider_name=provider_name)

            logger.info(
                "开始 %s 采集: 关键词='%s', 剩余配额=%d",
                provider_name, keyword, remaining,
            )

            try:
                async for batch in collect_func(
                    keyword, remaining, seen_ids, on_progress,
                ):
                    # 过滤已达配额的多余数据
                    actual_remaining = limit - total_collected
                    if actual_remaining <= 0:
                        break
                    if len(batch) > actual_remaining:
                        batch = batch[:actual_remaining]

                    yield batch
                    batch_count = len(batch)
                    total_collected += batch_count
                    stats.collected += batch_count

                    logger.info(
                        "%s 产出 %d 条，累计 %d / %d",
                        provider_name, batch_count, total_collected, limit,
                    )

            except Exception as e:
                error_msg = f"{provider_name}: {str(e)[:200]}"
                stats.error_message = error_msg
                stats.errors += 1
                logger.error("Provider %s 采集失败: %s", provider_name, error_msg)

            provider_stats.append(stats)
            logger.info(
                "%s 采集结束: 成功=%d, 错误=%d",
                provider_name, stats.collected, stats.errors,
            )

        # 所有 Provider 均失败且无数据
        if total_collected == 0:
            error_details = "; ".join(
                s.error_message
                for s in provider_stats
                if s.error_message
            )
            if error_details:
                raise RuntimeError(
                    f"所有 Provider 均失败，未采集到任何数据: {error_details}"
                )

        logger.info("零成本采集完成: 共 %d 条", total_collected)

    async def _collect_from_search_engine(
        self,
        keyword: str,
        limit: int,
        seen_ids: Set[str],
        on_progress: Optional[Callable[[int], None]],
    ) -> AsyncGenerator[List[RawPost], None]:
        """通过 SearchEngineProvider 采集

        Args:
            keyword: 搜索关键词
            limit: 采集条数上限
            seen_ids: 去重 ID 集合
            on_progress: 进度回调
        """
        async for batch in self._search_engine.collect(
            keyword, limit, seen_ids=seen_ids, on_progress=on_progress,
        ):
            yield batch

    async def _collect_from_bluesky(
        self,
        keyword: str,
        limit: int,
        seen_ids: Set[str],
        on_progress: Optional[Callable[[int], None]],
    ) -> AsyncGenerator[List[RawPost], None]:
        """通过 BlueskyProvider 采集

        Args:
            keyword: 搜索关键词
            limit: 采集条数上限
            seen_ids: 去重 ID 集合
            on_progress: 进度回调
        """
        async for batch in self._bluesky.collect(
            keyword, limit, seen_ids=seen_ids, on_progress=on_progress,
        ):
            yield batch

    async def _collect_from_rss(
        self,
        keyword: str,
        limit: int,
        seen_ids: Set[str],
        on_progress: Optional[Callable[[int], None]],
    ) -> AsyncGenerator[List[RawPost], None]:
        """通过 RSSProvider 采集

        Args:
            keyword: 搜索关键词
            limit: 采集条数上限
            seen_ids: 去重 ID 集合
            on_progress: 进度回调
        """
        async for batch in self._rss.collect(
            keyword, limit, seen_ids=seen_ids,
            syndication=self._syndication, on_progress=on_progress,
        ):
            yield batch

    async def close(self) -> None:
        """释放所有 Provider 持有的资源

        依次关闭各 Provider 的 aiohttp 会话，
        单个 Provider 关闭失败不影响其他 Provider。
        """
        for name, provider in [
            ("SearchEngine", self._search_engine),
            ("Syndication", self._syndication),
            ("Bluesky", self._bluesky),
            ("RSS", self._rss),
        ]:
            try:
                await provider.close()
            except Exception as e:
                logger.warning("关闭 %s 资源失败: %s", name, e)
