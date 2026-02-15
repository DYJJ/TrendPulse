"""
X(Twitter) 大规模批量采集器

使用 twscrape 作为主方案，Nitter 镜像站（Playwright）作为中间降级方案，
x.com Playwright 无头浏览器 + 登录态 Cookie 作为最终降级方案。
支持按关键词、时间范围、语言过滤，大规模采集时分批执行。
每 500 条数据 yield 一批并报告进度。

降级策略：twscrape → Nitter(Playwright) → x.com(Playwright)

需求: 1.1, 4.1, 4.2, 4.3, 4.4, 5.1, 5.2, 5.3, 6.1, 6.2, 6.3, 6.4
"""

import asyncio
import logging
import time
from datetime import datetime
from typing import AsyncGenerator, Callable, List, Optional

from backend.app.collectors.twitter_config import AccountPoolManager, CookieManager
from backend.app.collectors.twitter_nitter_provider import NitterProvider
from backend.app.collectors.twitter_playwright_provider import PlaywrightProvider
from backend.app.collectors.twitter_twscrape_provider import TwscrapeProvider
from backend.app.collectors.twitter_twikit_provider import TwikitProvider
from backend.app.models.data_models import RawPost

logger = logging.getLogger(__name__)

# 每批 yield 的数据量
BATCH_SIZE = 500

# 批次间延迟（秒）
BATCH_DELAY = 2.0

# 最大重试次数
MAX_RETRIES = 3

# 重试间隔（秒），指数退避
RETRY_DELAYS = [1.0, 3.0, 9.0]

# 连续空批次停止阈值
MAX_EMPTY_BATCHES = 3

# 网络请求超时（秒）
REQUEST_TIMEOUT = 30


class TwitterBatchCollector:
    """X(Twitter) 大规模批量采集器

    使用 twscrape 账号池作为主方案，Nitter 镜像站作为中间降级方案，
    Playwright 无头浏览器作为最终降级方案。
    大规模采集时分批执行，每批间设置延迟避免触发反爬机制。

    降级策略：
    1. twscrape（主方案）
    2. Nitter 镜像站 + Playwright（中间降级方案，无需登录）
    3. x.com Playwright 爬虫 + Cookie 登录态（最终降级方案）

    需求: 1.1, 4.1, 4.2, 4.3, 4.4, 5.1, 5.2, 5.3, 6.1, 6.2, 6.3, 6.4
    """

    def __init__(
        self,
        batch_delay: float = BATCH_DELAY,
        accounts: Optional[list[dict]] = None,
        cookies_path: Optional[str] = None,
        proxy: Optional[str] = None,
    ) -> None:
        """初始化 X 批量采集器

        Args:
            batch_delay: 批次间延迟秒数
            accounts: twscrape 账号列表
            cookies_path: Playwright Cookie 文件路径
            proxy: HTTP/SOCKS5 代理地址，如 http://127.0.0.1:7890
        """
        self._batch_delay = batch_delay
        self._accounts = accounts or []
        self._cookies_path = cookies_path
        self._proxy = proxy
        self._twikit_provider: Optional[TwikitProvider] = None
        self._twscrape_provider: Optional[TwscrapeProvider] = None
        self._nitter_provider: Optional[NitterProvider] = None
        self._playwright_provider: Optional[PlaywrightProvider] = None

    async def collect(
        self,
        keyword: str,
        limit: int,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        language: str = "en",
        on_progress: Optional[Callable[[int], None]] = None,
    ) -> AsyncGenerator[List[RawPost], None]:
        """批量采集推文数据

        降级策略：twscrape → Nitter(Playwright) → x.com(Playwright)
        每 500 条 yield 一批，支持进度回调。

        Args:
            keyword: 搜索关键词
            limit: 采集条数上限
            start_date: 起始日期（可选）
            end_date: 结束日期（可选）
            language: 语言代码（默认 en）
            on_progress: 进度回调函数，参数为已采集条数

        Yields:
            List[RawPost]: 每次 yield 一批数据（500 条）
        """
        start_time = time.time()
        provider_name = None

        # 主方案: twscrape
        if self._accounts:
            try:
                provider_name = "twscrape"
                async for batch in self._collect_with_retry(
                    self._collect_via_twscrape,
                    keyword, limit, start_date, end_date, language, on_progress,
                ):
                    yield batch
                elapsed = time.time() - start_time
                logger.info(
                    "采集任务完成: 方案=%s, 耗时=%.1fs", provider_name, elapsed,
                )
                return
            except Exception as e:
                logger.warning("twscrape 不可用: %s，尝试降级到 Nitter", e)
        else:
            logger.warning("twscrape 账号池为空，尝试 Nitter 降级方案")

        # 中间降级方案 A: twikit（免费，无需 API key，支持无限翻页）
        try:
            provider_name = "twikit"
            async for batch in self._collect_with_retry(
                self._collect_via_twikit,
                keyword, limit, start_date, end_date, language, on_progress,
            ):
                yield batch
            elapsed = time.time() - start_time
            logger.info(
                "采集任务完成: 方案=%s, 耗时=%.1fs", provider_name, elapsed,
            )
            return
        except Exception as e:
            logger.warning("twikit 不可用: %s，尝试降级到 Nitter", str(e)[:200])

        # 中间降级方案 B: Nitter 镜像站（Playwright）
        try:
            provider_name = "nitter"
            async for batch in self._collect_with_retry(
                self._collect_via_nitter,
                keyword, limit, on_progress,
            ):
                yield batch
            elapsed = time.time() - start_time
            logger.info(
                "采集任务完成: 方案=%s, 耗时=%.1fs", provider_name, elapsed,
            )
            return
        except Exception as e:
            logger.warning("Nitter 不可用: %s，尝试降级到 x.com Playwright", e)

        # 最终降级方案: x.com Playwright
        try:
            provider_name = "playwright"
            async for batch in self._collect_with_retry(
                self._collect_via_playwright,
                keyword, limit, on_progress,
            ):
                yield batch
            elapsed = time.time() - start_time
            logger.info(
                "采集任务完成: 方案=%s, 耗时=%.1fs", provider_name, elapsed,
            )
            return
        except Exception as e:
            logger.error("x.com Playwright 也不可用: %s", e)

        # 所有方案均失败
        raise RuntimeError(
            "所有采集方案均已尝试但均失败: twscrape、Nitter 和 Playwright 均不可用"
        )

    async def _collect_with_retry(
        self,
        collect_func,
        *args,
    ) -> AsyncGenerator[List[RawPost], None]:
        """带指数退避重试的采集包装器

        最多重试 MAX_RETRIES 次，间隔递增（1s/3s/9s）。
        检测到 Cloudflare 拦截等不可恢复错误时立即放弃，不再重试。

        Args:
            collect_func: 采集函数
            *args: 传递给采集函数的参数

        Yields:
            List[RawPost]: 数据批次
        """
        last_error = None
        for attempt in range(MAX_RETRIES):
            try:
                async for batch in collect_func(*args):
                    yield batch
                return
            except Exception as e:
                last_error = e
                err_str = str(e).lower()
                # Cloudflare 拦截、IP 封禁等不可恢复错误，立即放弃
                if any(kw in err_str for kw in ("cloudflare", "403", "blocked", "ip 可能被封禁")):
                    logger.warning(
                        "采集遇到不可恢复错误，跳过重试: %s",
                        str(e)[:200],
                    )
                    raise
                if attempt < MAX_RETRIES - 1:
                    delay = RETRY_DELAYS[attempt]
                    logger.warning(
                        "采集失败（第 %d/%d 次），%0.1fs 后重试: %s",
                        attempt + 1, MAX_RETRIES, delay, str(e)[:200],
                    )
                    await asyncio.sleep(delay)
        raise last_error  # type: ignore[misc]

    async def _collect_via_twikit(
        self,
        keyword: str,
        limit: int,
        start_date: Optional[datetime],
        end_date: Optional[datetime],
        language: str,
        on_progress: Optional[Callable[[int], None]],
    ) -> AsyncGenerator[List[RawPost], None]:
        """通过 twikit 采集推文数据（免费，无需 API key，支持无限翻页）

        twikit 使用 Twitter 内部 API，支持搜索和游标翻页，
        理论上可以采集到搜索结果中的所有推文。
        使用多关键词变体分片采集，大幅扩大数据量。

        Args:
            keyword: 搜索关键词
            limit: 采集条数上限
            start_date: 起始日期
            end_date: 结束日期
            language: 语言代码
            on_progress: 进度回调
        """
        if self._twikit_provider is None:
            self._twikit_provider = TwikitProvider(proxy=self._proxy)

        provider = self._twikit_provider
        seen_ids: set[str] = set()
        batch_buffer: List[RawPost] = []
        total_collected = 0

        # 生成搜索变体，每个变体搜索不同的结果集
        variants = self._generate_twitter_search_variants(keyword)
        per_variant_limit = max(limit // len(variants) + 1, 500)

        logger.info(
            "twikit 增强采集: %d 个关键词变体, 每个变体上限 %d 条",
            len(variants), per_variant_limit,
        )

        consecutive_failures = 0
        max_consecutive_failures = 3  # 连续失败 3 次即放弃

        for variant in variants:
            if total_collected >= limit:
                break

            variant_count = 0
            variant_limit = min(per_variant_limit, limit - total_collected)

            try:
                async for post in provider.search(
                    variant, variant_limit, start_date, end_date, language,
                ):
                    if total_collected >= limit:
                        break

                    # 全局去重
                    if post.external_id in seen_ids:
                        continue
                    if not post.content or not post.content.strip():
                        continue

                    seen_ids.add(post.external_id)
                    batch_buffer.append(post)
                    total_collected += 1
                    variant_count += 1

                    # 分批 yield
                    if len(batch_buffer) >= BATCH_SIZE:
                        yield batch_buffer[:BATCH_SIZE]
                        batch_buffer = batch_buffer[BATCH_SIZE:]
                        if on_progress:
                            on_progress(total_collected)
                        logger.info(
                            "twikit 采集进度: %d / %d (变体='%s': %d 条)",
                            total_collected, limit, variant[:30], variant_count,
                        )

                        # 批次间延迟
                        await asyncio.sleep(self._batch_delay)

                # 成功采集，重置连续失败计数
                consecutive_failures = 0

            except Exception as e:
                consecutive_failures += 1
                err_str = str(e)
                # Cloudflare/403 拦截，直接抛出不再尝试其他变体
                if any(kw in err_str.lower() for kw in ("cloudflare", "403", "blocked")):
                    raise RuntimeError(
                        f"twikit 被 Cloudflare 拦截，放弃所有变体: {err_str[:200]}"
                    )
                if consecutive_failures >= max_consecutive_failures:
                    raise RuntimeError(
                        f"twikit 连续 {max_consecutive_failures} 个变体失败，放弃: {err_str[:200]}"
                    )
                logger.warning("twikit 变体 '%s' 采集失败: %s，跳过", variant[:30], err_str[:200])
                continue

            if variant_count > 0:
                logger.info("twikit 变体 '%s' 完成: %d 条", variant[:30], variant_count)

        # yield 剩余数据
        if batch_buffer:
            yield batch_buffer
            if on_progress:
                on_progress(total_collected)

        logger.info("twikit 全部采集完成: %d 条（%d 个变体）", total_collected, len(variants))

    async def _collect_via_twscrape(
        self,
        keyword: str,
        limit: int,
        start_date: Optional[datetime],
        end_date: Optional[datetime],
        language: str,
        on_progress: Optional[Callable[[int], None]],
    ) -> AsyncGenerator[List[RawPost], None]:
        """通过 twscrape 采集推文数据

        Args:
            keyword: 搜索关键词
            limit: 采集条数上限
            start_date: 起始日期
            end_date: 结束日期
            language: 语言代码
            on_progress: 进度回调
        """
        # 初始化 twscrape 提供者（仅首次创建）
        if self._twscrape_provider is None:
            self._twscrape_provider = TwscrapeProvider(self._accounts, proxy=self._proxy)

        provider = self._twscrape_provider
        seen_ids: set[str] = set()
        batch_buffer: List[RawPost] = []
        total_collected = 0
        empty_batch_count = 0

        async for post in provider.search(
            keyword, limit, start_date, end_date, language,
        ):
            # 基于 external_id 去重
            if post.external_id in seen_ids:
                continue

            # 无效数据过滤：空内容或缺少 external_id
            if not post.content or not post.content.strip():
                logger.warning("推文内容为空，跳过: id=%s", post.external_id)
                continue
            if not post.external_id:
                logger.warning("推文缺少 external_id，跳过")
                continue

            seen_ids.add(post.external_id)
            batch_buffer.append(post)
            total_collected += 1

            # 分批 yield
            if len(batch_buffer) >= BATCH_SIZE:
                yield batch_buffer[:BATCH_SIZE]
                batch_buffer = batch_buffer[BATCH_SIZE:]
                if on_progress:
                    on_progress(total_collected)
                logger.info("twscrape 采集进度: %d / %d", total_collected, limit)
                empty_batch_count = 0

                # 批次间延迟
                await asyncio.sleep(self._batch_delay)

            if total_collected >= limit:
                break

        # yield 剩余数据
        if batch_buffer:
            yield batch_buffer
            if on_progress:
                on_progress(total_collected)

        logger.info("twscrape 采集完成: %d 条", total_collected)

    async def _collect_via_nitter(
        self,
        keyword: str,
        limit: int,
        on_progress: Optional[Callable[[int], None]],
    ) -> AsyncGenerator[List[RawPost], None]:
        """通过 Nitter 镜像站采集推文数据（增强版：多关键词变体扩量）

        使用关键词变体分片采集，每个变体返回不同的搜索结果集，
        大幅扩大数据量。Nitter 不需要登录，通过 Playwright 绕过 Cloudflare。

        Args:
            keyword: 搜索关键词
            limit: 采集条数上限
            on_progress: 进度回调
        """
        # 初始化 Nitter 提供者
        if self._nitter_provider is None:
            self._nitter_provider = NitterProvider(proxy=self._proxy)

        provider = self._nitter_provider
        seen_ids: set[str] = set()
        batch_buffer: List[RawPost] = []
        total_collected = 0

        # 生成关键词变体，每个变体搜索不同的结果集
        variants = self._generate_twitter_search_variants(keyword)
        per_variant_limit = max(limit // len(variants) + 1, 200)

        logger.info(
            "Nitter 增强采集: %d 个关键词变体, 每个变体上限 %d 条",
            len(variants), per_variant_limit,
        )

        consecutive_failures = 0
        max_consecutive_failures = 3

        for variant in variants:
            if total_collected >= limit:
                break

            variant_count = 0
            variant_limit = min(per_variant_limit, limit - total_collected)

            try:
                async for post in provider.search(variant, variant_limit):
                    if total_collected >= limit:
                        break

                    # 基于 external_id 去重（跨变体全局去重）
                    if post.external_id in seen_ids:
                        continue
                    if not post.content or not post.content.strip():
                        continue
                    if not post.external_id:
                        continue

                    seen_ids.add(post.external_id)
                    batch_buffer.append(post)
                    total_collected += 1
                    variant_count += 1

                    # 分批 yield
                    if len(batch_buffer) >= BATCH_SIZE:
                        yield batch_buffer[:BATCH_SIZE]
                        batch_buffer = batch_buffer[BATCH_SIZE:]
                        if on_progress:
                            on_progress(total_collected)
                        logger.info(
                            "Nitter 采集进度: %d / %d (变体='%s': %d 条)",
                            total_collected, limit, variant[:30], variant_count,
                        )

                consecutive_failures = 0

            except Exception as e:
                consecutive_failures += 1
                if consecutive_failures >= max_consecutive_failures:
                    raise RuntimeError(
                        f"Nitter 连续 {max_consecutive_failures} 个变体失败，放弃: {str(e)[:200]}"
                    )
                logger.warning("Nitter 变体 '%s' 采集失败: %s，跳过", variant[:30], str(e)[:200])
                continue

            if variant_count > 0:
                logger.info("Nitter 变体 '%s' 完成: %d 条", variant[:30], variant_count)

        # yield 剩余数据
        if batch_buffer:
            yield batch_buffer
            if on_progress:
                on_progress(total_collected)

        logger.info("Nitter 全部采集完成: %d 条（%d 个变体）", total_collected, len(variants))

    async def _collect_via_playwright(
        self,
        keyword: str,
        limit: int,
        on_progress: Optional[Callable[[int], None]],
    ) -> AsyncGenerator[List[RawPost], None]:
        """通过 Playwright 爬虫采集推文数据（增强版：多关键词变体扩量）

        Args:
            keyword: 搜索关键词
            limit: 采集条数上限
            on_progress: 进度回调
        """
        # 初始化 Playwright 提供者
        if self._playwright_provider is None:
            cookie_manager = CookieManager(self._cookies_path)
            self._playwright_provider = PlaywrightProvider(cookie_manager)

        provider = self._playwright_provider
        seen_ids: set[str] = set()
        batch_buffer: List[RawPost] = []
        total_collected = 0

        # 生成关键词变体
        variants = self._generate_twitter_search_variants(keyword)
        per_variant_limit = max(limit // len(variants) + 1, 200)

        consecutive_failures = 0
        max_consecutive_failures = 3

        for variant in variants:
            if total_collected >= limit:
                break

            variant_limit = min(per_variant_limit, limit - total_collected)

            try:
                async for post in provider.search(variant, variant_limit):
                    if total_collected >= limit:
                        break

                    if post.external_id in seen_ids:
                        continue
                    if not post.content or not post.content.strip():
                        continue
                    if not post.external_id:
                        continue

                    seen_ids.add(post.external_id)
                    batch_buffer.append(post)
                    total_collected += 1

                    if len(batch_buffer) >= BATCH_SIZE:
                        yield batch_buffer[:BATCH_SIZE]
                        batch_buffer = batch_buffer[BATCH_SIZE:]
                        if on_progress:
                            on_progress(total_collected)
                        logger.info("Playwright 采集进度: %d / %d", total_collected, limit)

                consecutive_failures = 0

            except Exception as e:
                consecutive_failures += 1
                if consecutive_failures >= max_consecutive_failures:
                    raise RuntimeError(
                        f"Playwright 连续 {max_consecutive_failures} 个变体失败，放弃: {str(e)[:200]}"
                    )
                logger.warning("Playwright 变体 '%s' 采集失败: %s", variant[:30], str(e)[:200])
                continue

        # yield 剩余数据
        if batch_buffer:
            yield batch_buffer
            if on_progress:
                on_progress(total_collected)

        logger.info("Playwright 全部采集完成: %d 条", total_collected)

    async def close(self) -> None:
        """释放所有资源"""
        if self._twikit_provider:
            await self._twikit_provider.close()
            self._twikit_provider = None
        if self._twscrape_provider:
            await self._twscrape_provider.close()
            self._twscrape_provider = None
        if self._nitter_provider:
            await self._nitter_provider.close()
            self._nitter_provider = None
        if self._playwright_provider:
            await self._playwright_provider.close()
            self._playwright_provider = None
        logger.info("TwitterBatchCollector 已关闭")
    @staticmethod
    def _generate_twitter_search_variants(keyword: str) -> list:
        """根据关键词生成大量 Twitter 搜索变体，用于大幅扩大数据量

        Twitter 搜索支持高级搜索语法，利用不同的搜索条件
        获取不同的结果集。目标 100+ 变体以支持 10 万+数据采集。

        策略：
        1. 原始关键词
        2. 细粒度时间分片（按季度/月份搜索）
        3. 多语言变体
        4. 互动量分级过滤
        5. 内容类型过滤
        6. 情感/话题变体
        7. 组合变体（时间 + 语言 + 互动量）

        Args:
            keyword: 原始搜索关键词

        Returns:
            list: 搜索变体列表
        """
        variants = [keyword]

        # 细粒度时间分片：按季度搜索，覆盖更多时间段
        time_ranges = [
            # 2026
            f"{keyword} since:2026-01-01 until:2026-03-01",
            f"{keyword} since:2025-10-01 until:2026-01-01",
            # 2025 按季度
            f"{keyword} since:2025-07-01 until:2025-10-01",
            f"{keyword} since:2025-04-01 until:2025-07-01",
            f"{keyword} since:2025-01-01 until:2025-04-01",
            # 2024 按季度
            f"{keyword} since:2024-10-01 until:2025-01-01",
            f"{keyword} since:2024-07-01 until:2024-10-01",
            f"{keyword} since:2024-04-01 until:2024-07-01",
            f"{keyword} since:2024-01-01 until:2024-04-01",
            # 2023 按半年
            f"{keyword} since:2023-07-01 until:2024-01-01",
            f"{keyword} since:2023-01-01 until:2023-07-01",
            # 2022 按半年
            f"{keyword} since:2022-07-01 until:2023-01-01",
            f"{keyword} since:2022-01-01 until:2022-07-01",
        ]
        variants.extend(time_ranges)

        # 多语言变体
        languages = ["en", "zh", "ja", "es", "fr", "de", "ko", "pt", "ar", "ru", "it", "hi"]
        for lang in languages:
            variants.append(f"{keyword} lang:{lang}")

        # 互动量分级过滤（不同级别返回不同结果集）
        engagement_levels = [
            ("min_faves", [1, 5, 10, 50, 100, 500, 1000]),
            ("min_retweets", [1, 5, 10, 50, 100, 500]),
            ("min_replies", [1, 5, 10, 50]),
        ]
        for metric, thresholds in engagement_levels:
            for threshold in thresholds:
                variants.append(f"{keyword} {metric}:{threshold}")

        # 内容类型过滤
        content_filters = [
            "filter:links", "filter:images", "filter:videos",
            "filter:media", "-filter:replies", "-filter:retweets",
            "filter:native_video", "filter:quote",
        ]
        for cf in content_filters:
            variants.append(f"{keyword} {cf}")

        # 情感/话题变体（不使用高级语法，直接拼接关键词）
        topic_suffixes = [
            "news", "update", "breaking", "analysis", "opinion",
            "prediction", "crash", "bull", "bear", "scam",
            "warning", "review", "guide", "explained", "thread",
            "price", "market", "trading", "investment", "future",
        ]
        for suffix in topic_suffixes:
            variants.append(f"{keyword} {suffix}")

        # 组合变体：时间 + 语言
        combo_time_lang = [
            (f"since:2025-01-01 until:2025-07-01", "en"),
            (f"since:2025-01-01 until:2025-07-01", "zh"),
            (f"since:2025-07-01 until:2026-01-01", "en"),
            (f"since:2025-07-01 until:2026-01-01", "zh"),
            (f"since:2024-01-01 until:2024-07-01", "en"),
            (f"since:2024-07-01 until:2025-01-01", "en"),
            (f"since:2026-01-01 until:2026-03-01", "en"),
            (f"since:2026-01-01 until:2026-03-01", "zh"),
        ]
        for time_range, lang in combo_time_lang:
            variants.append(f"{keyword} {time_range} lang:{lang}")

        # 组合变体：时间 + 互动量
        combo_time_engagement = [
            ("since:2025-01-01 until:2026-01-01", "min_faves:10"),
            ("since:2025-01-01 until:2026-01-01", "min_faves:100"),
            ("since:2024-01-01 until:2025-01-01", "min_faves:10"),
            ("since:2024-01-01 until:2025-01-01", "min_faves:100"),
        ]
        for time_range, engagement in combo_time_engagement:
            variants.append(f"{keyword} {time_range} {engagement}")

        # 去重
        seen = set()
        unique = []
        for v in variants:
            v_lower = v.lower().strip()
            if v_lower not in seen:
                seen.add(v_lower)
                unique.append(v)

        logger.info("Twitter 搜索变体: 生成 %d 个", len(unique))
        return unique


