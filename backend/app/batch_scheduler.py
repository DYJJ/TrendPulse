"""
大规模采集任务调度器

实现任务拆分、多数据源异步并发采集、速率限制、断点续采和进度追踪。
当 limit > 1000 时自动拆分为多个采集批次。
单数据源失败时继续其他数据源采集。

需求: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import AsyncGenerator, Callable, Dict, List, Optional

from backend.app.collection_monitor import CollectionMonitor
from backend.app.models.data_models import DataSource, RawPost

logger = logging.getLogger(__name__)

# 任务拆分阈值：超过此值自动拆分批次
SPLIT_THRESHOLD = 1000

# 默认速率限制延迟（秒）
DEFAULT_RATE_LIMIT_DELAY = 1.0

# 最大速率限制延迟（秒）
MAX_RATE_LIMIT_DELAY = 3.0


@dataclass
class SourceProgress:
    """单数据源的采集进度

    Args:
        source: 数据源名称
        collected: 已采集条数
        target: 目标采集条数
        status: 状态（pending/collecting/completed/failed）
        error: 错误信息
        last_cursor: 最后游标位置（用于断点续采）
    """
    source: str
    collected: int = 0
    target: int = 0
    status: str = "pending"
    error: Optional[str] = None
    last_cursor: Optional[str] = None


@dataclass
class TaskProgress:
    """采集任务整体进度

    Args:
        task_id: 任务 ID
        total_target: 总目标采集条数
        total_collected: 总已采集条数
        progress_percent: 进度百分比（0-100）
        source_progress: 各数据源进度
        status: 任务状态
    """
    task_id: str
    total_target: int = 0
    total_collected: int = 0
    progress_percent: float = 0.0
    source_progress: Dict[str, SourceProgress] = field(default_factory=dict)
    status: str = "pending"


class BatchScheduler:
    """大规模采集任务调度器

    负责将大规模采集任务拆分为多个批次，
    协调多数据源异步并发采集，集成速率限制器，
    支持断点续采和实时进度追踪。

    需求: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6
    """

    def __init__(
        self,
        rate_limit_delay: float = DEFAULT_RATE_LIMIT_DELAY,
        db_session_factory: Optional[Callable] = None,
    ) -> None:
        """初始化调度器

        Args:
            rate_limit_delay: 批次间速率限制延迟（秒），范围 0-3
            db_session_factory: 数据库会话工厂函数（用于断点续采持久化）
        """
        self._rate_limit_delay = max(0.0, min(rate_limit_delay, MAX_RATE_LIMIT_DELAY))
        self._db_session_factory = db_session_factory
        # 存储活跃任务的进度信息
        self._active_tasks: Dict[str, TaskProgress] = {}
        # 采集监控器
        self._monitor = CollectionMonitor()

    @staticmethod
    def split_task(limit: int, sources: List[str]) -> List[Dict]:
        """将大规模采集任务拆分为多个批次

        当 limit > 1000 时自动拆分。每个数据源独立拆分批次。

        Args:
            limit: 总采集条数上限
            sources: 数据源列表

        Returns:
            List[Dict]: 批次列表，每个批次包含 source、offset、batch_limit
        """
        batches = []
        for source in sources:
            if limit <= SPLIT_THRESHOLD:
                # 不需要拆分
                batches.append({
                    "source": source,
                    "offset": 0,
                    "batch_limit": limit,
                    "batch_index": 0,
                })
            else:
                # 按 SPLIT_THRESHOLD 拆分
                remaining = limit
                offset = 0
                batch_index = 0
                while remaining > 0:
                    batch_limit = min(SPLIT_THRESHOLD, remaining)
                    batches.append({
                        "source": source,
                        "offset": offset,
                        "batch_limit": batch_limit,
                        "batch_index": batch_index,
                    })
                    offset += batch_limit
                    remaining -= batch_limit
                    batch_index += 1
        return batches

    async def schedule_task(
        self,
        keyword: str,
        limit: int,
        sources: List[str],
        language: str = "en",
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        subreddits: Optional[List[str]] = None,
        on_progress: Optional[Callable[[TaskProgress], None]] = None,
    ) -> str:
        """调度大规模采集任务

        拆分为批次并发执行多数据源采集。
        单数据源失败时继续其他数据源。

        Args:
            keyword: 搜索关键词
            limit: 总采集条数上限
            sources: 数据源列表（如 ["reddit", "youtube", "twitter"]）
            language: 语言代码
            start_date: 起始日期（可选）
            end_date: 结束日期（可选）
            subreddits: Reddit 指定 subreddit 列表（可选）
            on_progress: 进度回调函数

        Returns:
            str: 任务 ID
        """
        task_id = str(uuid.uuid4())

        # 记录任务开始日志
        self._monitor.on_task_start(task_id, keyword, limit, sources)

        # 初始化任务进度
        task_progress = TaskProgress(
            task_id=task_id,
            total_target=limit * len(sources),
            status="collecting",
        )
        for source in sources:
            task_progress.source_progress[source] = SourceProgress(
                source=source,
                target=limit,
                status="pending",
            )
        self._active_tasks[task_id] = task_progress

        # 为每个数据源创建并发采集协程
        source_tasks = []
        for source in sources:
            coro = self._collect_source(
                task_id=task_id,
                keyword=keyword,
                limit=limit,
                source=source,
                language=language,
                start_date=start_date,
                end_date=end_date,
                subreddits=subreddits,
                on_progress=on_progress,
            )
            source_tasks.append(coro)

        # 并发执行所有数据源采集（单个失败不影响其他）
        results = await asyncio.gather(*source_tasks, return_exceptions=True)

        # 处理结果
        for source, result in zip(sources, results):
            sp = task_progress.source_progress[source]
            if isinstance(result, Exception):
                sp.status = "failed"
                sp.error = str(result)
                self._monitor.on_source_error(task_id, source, str(result))
                logger.error("数据源 %s 采集失败: %s", source, result)
            else:
                if sp.status != "failed":
                    sp.status = "completed"

        # 更新任务整体状态
        self._update_task_progress(task_id)
        all_failed = all(
            sp.status == "failed"
            for sp in task_progress.source_progress.values()
        )
        task_progress.status = "failed" if all_failed else "completed"

        # 记录任务完成日志
        self._monitor.on_task_complete(task_id)

        if on_progress:
            on_progress(task_progress)

        # 持久化最终状态
        self._persist_progress(task_id)

        return task_id

    async def _collect_source(
        self,
        task_id: str,
        keyword: str,
        limit: int,
        source: str,
        language: str,
        start_date: Optional[datetime],
        end_date: Optional[datetime],
        subreddits: Optional[List[str]],
        on_progress: Optional[Callable[[TaskProgress], None]],
    ) -> List[RawPost]:
        """采集单个数据源的数据

        根据 limit 自动拆分批次，每批次间应用速率限制延迟。

        Args:
            task_id: 任务 ID
            keyword: 搜索关键词
            limit: 采集条数上限
            source: 数据源名称
            language: 语言代码
            start_date: 起始日期
            end_date: 结束日期
            subreddits: subreddit 列表
            on_progress: 进度回调

        Returns:
            List[RawPost]: 采集到的所有帖子
        """
        task_progress = self._active_tasks[task_id]
        sp = task_progress.source_progress[source]
        sp.status = "collecting"

        # 记录续采时的已有采集基数，避免覆盖
        base_collected = sp.collected or 0

        all_posts: List[RawPost] = []
        collector = self._create_collector(source, language)

        try:
            # 获取采集器的异步生成器
            gen = self._get_collector_generator(
                collector, keyword, limit, source, language,
                start_date, end_date, subreddits,
            )

            batch_count = 0
            async for batch in gen:
                # 记录批次开始
                self._monitor.on_batch_start(task_id, source)

                all_posts.extend(batch)
                sp.collected = base_collected + len(all_posts)

                # 更新整体进度
                self._update_task_progress(task_id)

                if on_progress:
                    on_progress(task_progress)

                batch_count += 1

                # 记录批次完成日志（含异常检测）
                self._monitor.on_batch_complete(
                    task_id, source, batch_count, len(batch),
                )

                logger.info(
                    "任务 %s 数据源 %s 第 %d 批完成，已采集 %d / %d",
                    task_id, source, batch_count, sp.collected, limit,
                )

                # 检查是否因连续空批次被暂停
                if self._monitor.is_source_paused(task_id, source):
                    logger.warning(
                        "任务 %s 数据源 %s 因连续空批次被暂停",
                        task_id, source,
                    )
                    break

                # 速率限制延迟
                if self._rate_limit_delay > 0:
                    await asyncio.sleep(self._rate_limit_delay)

        except Exception as e:
            sp.status = "failed"
            sp.error = str(e)
            self._monitor.on_source_error(task_id, source, str(e))
            logger.error("数据源 %s 采集异常: %s", source, e)
            raise
        finally:
            await self._close_collector(collector)

        return all_posts

    def _create_collector(self, source: str, language: str):
        """根据数据源名称创建对应的批量采集器

        Args:
            source: 数据源名称
            language: 语言代码

        Returns:
            对应的批量采集器实例
        """
        import os

        if source == "reddit":
            from backend.app.collectors.reddit_batch_collector import RedditBatchCollector
            # 读取代理配置（Reddit 在国内需要代理）
            proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")
            return RedditBatchCollector(
                client_id=os.environ.get("REDDIT_CLIENT_ID", ""),
                client_secret=os.environ.get("REDDIT_CLIENT_SECRET", ""),
                user_agent=os.environ.get("REDDIT_USER_AGENT", "TrendPulse/1.0"),
                proxy=proxy,
            )
        elif source == "youtube":
            from backend.app.collectors.youtube_batch_collector import YouTubeBatchCollector
            return YouTubeBatchCollector(language=language)
        elif source == "twitter":
            from backend.app.collectors.twitter_zero_cost_collector import (
                ZeroCostCollector,
                is_zero_cost_enabled,
            )

            if is_zero_cost_enabled():
                # 零成本采集器：无需 Twitter 账号，通过搜索引擎/Syndication/Bluesky/RSS 采集
                batch_delay = float(os.environ.get("TWITTER_BATCH_DELAY", "2.0"))
                proxy = os.environ.get("TWITTER_PROXY") or os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")

                logger.info(
                    "创建零成本 Twitter 采集器: 批次延迟=%.1fs, 代理=%s",
                    batch_delay, proxy or "未配置",
                )

                return ZeroCostCollector(
                    batch_delay=batch_delay,
                    proxy=proxy,
                )
            else:
                # 回退到原有 TwitterBatchCollector（需要 Twitter 账号）
                from backend.app.collectors.twitter_batch_collector import TwitterBatchCollector
                from backend.app.collectors.twitter_config import AccountPoolManager

                accounts_env = os.environ.get("TWITTER_ACCOUNTS", "")
                accounts = AccountPoolManager.parse_accounts_from_env(accounts_env)
                cookies_path = os.environ.get("TWITTER_COOKIES_PATH")
                batch_delay = float(os.environ.get("TWITTER_BATCH_DELAY", "2.0"))
                proxy = os.environ.get("TWITTER_PROXY") or os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")

                logger.info(
                    "创建 Twitter 批量采集器: 账号数=%d, Cookie路径=%s, 批次延迟=%.1fs, 代理=%s",
                    len(accounts), cookies_path or "未配置", batch_delay, proxy or "未配置",
                )

                return TwitterBatchCollector(
                    batch_delay=batch_delay,
                    accounts=accounts,
                    cookies_path=cookies_path,
                    proxy=proxy,
                )
        else:
            raise ValueError(f"不支持的数据源: {source}")

    @staticmethod
    def _get_collector_generator(
        collector,
        keyword: str,
        limit: int,
        source: str,
        language: str,
        start_date: Optional[datetime],
        end_date: Optional[datetime],
        subreddits: Optional[List[str]],
    ) -> AsyncGenerator[List[RawPost], None]:
        """获取采集器的异步生成器

        根据不同数据源传递不同的参数。

        Args:
            collector: 采集器实例
            keyword: 搜索关键词
            limit: 采集条数上限
            source: 数据源名称
            language: 语言代码
            start_date: 起始日期
            end_date: 结束日期
            subreddits: subreddit 列表

        Returns:
            AsyncGenerator: 数据批次生成器
        """
        if source == "reddit":
            subreddit = subreddits[0] if subreddits else None
            return collector.collect(
                keyword=keyword,
                limit=limit,
                subreddit=subreddit,
                start_date=start_date,
                end_date=end_date,
            )
        elif source == "youtube":
            return collector.collect(
                keyword=keyword,
                limit=limit,
                language=language,
            )
        elif source == "twitter":
            return collector.collect(
                keyword=keyword,
                limit=limit,
                start_date=start_date,
                end_date=end_date,
                language=language,
            )
        else:
            raise ValueError(f"不支持的数据源: {source}")

    @staticmethod
    async def _close_collector(collector) -> None:
        """安全关闭采集器

        Args:
            collector: 采集器实例
        """
        try:
            if hasattr(collector, "close"):
                await collector.close()
        except Exception as e:
            logger.warning("关闭采集器失败: %s", e)

    def _update_task_progress(self, task_id: str) -> None:
        """更新任务整体进度百分比

        进度 = 所有数据源已采集总数 / 总目标数 * 100
        进度值单调递增，不会回退。

        Args:
            task_id: 任务 ID
        """
        tp = self._active_tasks.get(task_id)
        if not tp:
            return

        total_collected = sum(
            sp.collected for sp in tp.source_progress.values()
        )
        tp.total_collected = total_collected

        if tp.total_target > 0:
            new_percent = min(100.0, (total_collected / tp.total_target) * 100)
            # 单调递增：只允许进度增加
            tp.progress_percent = max(tp.progress_percent, new_percent)
        else:
            tp.progress_percent = 0.0

    def _persist_progress(self, task_id: str) -> None:
        """将任务进度持久化到数据库（用于断点续采）

        Args:
            task_id: 任务 ID
        """
        if not self._db_session_factory:
            return

        tp = self._active_tasks.get(task_id)
        if not tp:
            return

        try:
            from backend.app.models.db_models import CollectionTaskDB
            session = self._db_session_factory()
            try:
                task_db = session.query(CollectionTaskDB).filter(
                    CollectionTaskDB.id == task_id
                ).first()
                if task_db:
                    task_db.collected_count = tp.total_collected
                    task_db.progress = int(tp.progress_percent)
                    task_db.status = tp.status
                    # 保存各数据源的游标信息（JSON 格式）
                    import json
                    cursors = {}
                    for source, sp in tp.source_progress.items():
                        if sp.last_cursor:
                            cursors[source] = sp.last_cursor
                    if cursors:
                        task_db.last_cursor = json.dumps(cursors)
                    session.commit()
            finally:
                session.close()
        except Exception as e:
            logger.error("持久化任务进度失败: %s", e)

    async def resume_task(
        self,
        task_id: str,
        keyword: str,
        limit: int,
        sources: List[str],
        language: str = "en",
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        subreddits: Optional[List[str]] = None,
        on_progress: Optional[Callable[[TaskProgress], None]] = None,
    ) -> str:
        """从断点续采

        从数据库中读取上次的采集进度和游标位置，
        计算剩余需要采集的数量，继续采集。

        Args:
            task_id: 原任务 ID
            keyword: 搜索关键词
            limit: 原始总采集条数上限
            sources: 数据源列表
            language: 语言代码
            start_date: 起始日期
            end_date: 结束日期
            subreddits: subreddit 列表
            on_progress: 进度回调

        Returns:
            str: 任务 ID（与传入的相同）
        """
        # 从数据库加载已有进度
        previously_collected = 0
        saved_cursors: Dict[str, str] = {}

        if self._db_session_factory:
            try:
                from backend.app.models.db_models import CollectionTaskDB
                import json
                session = self._db_session_factory()
                try:
                    task_db = session.query(CollectionTaskDB).filter(
                        CollectionTaskDB.id == task_id
                    ).first()
                    if task_db:
                        previously_collected = task_db.collected_count or 0
                        if task_db.last_cursor:
                            saved_cursors = json.loads(task_db.last_cursor)
                finally:
                    session.close()
            except Exception as e:
                logger.error("读取断点续采信息失败: %s", e)

        # 计算每个数据源剩余需要采集的数量
        remaining_per_source = max(0, limit - previously_collected // max(len(sources), 1))

        if remaining_per_source <= 0:
            logger.info("任务 %s 已完成，无需续采", task_id)
            return task_id

        # 记录续采任务开始日志
        self._monitor.on_task_start(task_id, keyword, remaining_per_source, sources)

        # 初始化任务进度（从已有进度开始）
        task_progress = TaskProgress(
            task_id=task_id,
            total_target=limit * len(sources),
            total_collected=previously_collected,
            progress_percent=(previously_collected / max(limit * len(sources), 1)) * 100,
            status="collecting",
        )
        for source in sources:
            task_progress.source_progress[source] = SourceProgress(
                source=source,
                target=limit,
                collected=previously_collected // max(len(sources), 1),
                status="pending",
                last_cursor=saved_cursors.get(source),
            )
        self._active_tasks[task_id] = task_progress

        # 为每个数据源创建续采协程
        source_tasks = []
        for source in sources:
            coro = self._collect_source(
                task_id=task_id,
                keyword=keyword,
                limit=remaining_per_source,
                source=source,
                language=language,
                start_date=start_date,
                end_date=end_date,
                subreddits=subreddits,
                on_progress=on_progress,
            )
            source_tasks.append(coro)

        # 并发执行
        results = await asyncio.gather(*source_tasks, return_exceptions=True)

        for source, result in zip(sources, results):
            sp = task_progress.source_progress[source]
            if isinstance(result, Exception):
                sp.status = "failed"
                sp.error = str(result)
                self._monitor.on_source_error(task_id, source, str(result))
            else:
                if sp.status != "failed":
                    sp.status = "completed"

        self._update_task_progress(task_id)
        all_failed = all(
            sp.status == "failed"
            for sp in task_progress.source_progress.values()
        )
        task_progress.status = "failed" if all_failed else "completed"

        # 记录续采任务完成日志
        self._monitor.on_task_complete(task_id)

        if on_progress:
            on_progress(task_progress)

        self._persist_progress(task_id)

        return task_id

    def get_task_progress(self, task_id: str) -> Optional[TaskProgress]:
        """获取任务进度

        Args:
            task_id: 任务 ID

        Returns:
            TaskProgress: 任务进度信息，不存在返回 None
        """
        return self._active_tasks.get(task_id)
