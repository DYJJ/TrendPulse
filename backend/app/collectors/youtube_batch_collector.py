"""
YouTube 大规模批量采集器

使用 yt-dlp Python API 进行大规模 YouTube 数据采集。
支持搜索视频、提取元数据、评论和字幕。
每 200 条数据 yield 一批并报告进度。

yt-dlp 失败时降级为 Playwright 爬虫。

需求: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6
"""

import asyncio
import logging
import uuid
from asyncio import sleep as async_sleep
from datetime import datetime, timezone
from typing import AsyncGenerator, Callable, List, Optional

from backend.app.models.data_models import DataSource, RawPost

logger = logging.getLogger(__name__)

# 每批 yield 的数据量
BATCH_SIZE = 200

# 网络请求超时（秒）
REQUEST_TIMEOUT = 60

# 最大重试次数
MAX_RETRIES = 3

# 并发搜索阈值：limit 超过此值时启用并发多关键词搜索
CONCURRENT_SEARCH_THRESHOLD = 100
# 并发搜索最大线程数（增大以支持 400+ 变体并发）
CONCURRENT_SEARCH_WORKERS = 30

# yt-dlp 单次搜索上限（YouTube 平台限制约 500-600 条/搜索词）
YTDLP_SINGLE_SEARCH_CAP = 800


class YouTubeBatchCollector:
    """YouTube 大规模批量采集器

    使用 yt-dlp 批量采集 YouTube 视频数据和评论。
    当 yt-dlp 不可用时自动降级到 Playwright 爬虫。

    默认使用快速模式（fast_mode=True），仅通过 yt-dlp 搜索获取基本元数据，
    无需逐个视频请求详情，采集速度极快（数百条仅需数秒）。
    如需评论和字幕等详细信息，可设置 fast_mode=False。

    需求: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6
    """

    def __init__(
        self,
        language: str = "en",
        concurrency: int = 5,
        fast_mode: bool = True,
    ) -> None:
        """初始化 YouTube 批量采集器

        Args:
            language: 默认语言代码，用于字幕提取
            concurrency: 详情提取的并发数，默认 5
            fast_mode: 快速模式，True 时仅用搜索结果（极快），
                       False 时逐个提取详情（含评论/字幕，较慢）
        """
        self._language = language
        self._concurrency = concurrency
        self._fast_mode = fast_mode

    async def collect(
        self,
        keyword: str,
        limit: int,
        language: Optional[str] = None,
        on_progress: Optional[Callable[[int], None]] = None,
    ) -> AsyncGenerator[List[RawPost], None]:
        """批量采集 YouTube 数据，优先使用 yt-dlp

        使用两级降级策略：
        1. yt-dlp（主方案）
        2. Playwright 爬虫（降级方案）

        Args:
            keyword: 搜索关键词
            limit: 采集条数上限（最大 200000）
            language: 语言代码（可选，覆盖默认值）
            on_progress: 进度回调函数，参数为已采集条数

        Yields:
            List[RawPost]: 每次 yield 一批数据（200 条）
        """
        lang = language or self._language

        try:
            async for batch in self._collect_ytdlp(
                keyword, limit, lang, on_progress
            ):
                yield batch
            return
        except Exception as e:
            logger.warning("yt-dlp 不可用: %s，尝试降级到 Playwright", e)

        # 降级方案: Playwright 爬虫
        async for batch in self._collect_playwright(
            keyword, limit, on_progress
        ):
            yield batch

    async def _collect_ytdlp(
        self,
        keyword: str,
        limit: int,
        language: str,
        on_progress: Optional[Callable[[int], None]] = None,
    ) -> AsyncGenerator[List[RawPost], None]:
        """通过 yt-dlp 采集 YouTube 数据（流式分批搜索）

        将搜索变体分批执行，每批搜索完成后立即 yield 数据，
        避免等待所有变体搜索完成。达到目标数量后提前终止。

        Args:
            keyword: 搜索关键词
            limit: 采集条数上限
            language: 语言代码
            on_progress: 进度回调
        """
        try:
            import yt_dlp
        except ImportError:
            raise RuntimeError("yt-dlp 未安装，无法使用主采集方案")

        import concurrent.futures

        loop = asyncio.get_event_loop()
        total_collected = 0
        batch_buffer: List[RawPost] = []
        seen_ids: set = set()

        search_opts = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": "in_playlist",
            "force_generic_extractor": False,
            "ignoreerrors": True,
        }

        # 生成搜索变体
        if limit <= CONCURRENT_SEARCH_THRESHOLD:
            variants = [keyword]
        else:
            variants = self._generate_search_variants(keyword)

        # 每个变体搜索量
        per_variant = min(600, limit)

        def do_search(query: str, n: int) -> list:
            """单个变体的搜索任务"""
            url = f"ytsearch{n}:{query}"
            try:
                with yt_dlp.YoutubeDL(search_opts) as ydl:
                    result = ydl.extract_info(url, download=False)
                    if result and "entries" in result:
                        return [e for e in result["entries"] if e is not None]
            except Exception:
                pass
            return []

        # 分批并发搜索，每批搜完立即 yield 数据
        search_batch_size = CONCURRENT_SEARCH_WORKERS
        for batch_start in range(0, len(variants), search_batch_size):
            if total_collected >= limit:
                break

            batch_variants = variants[batch_start:batch_start + search_batch_size]
            logger.info(
                "YouTube 搜索批次 %d-%d/%d（已采集 %d/%d 条）",
                batch_start + 1, batch_start + len(batch_variants),
                len(variants), total_collected, limit,
            )

            # 并发搜索当前批次的变体
            batch_entries: list = []
            try:
                with concurrent.futures.ThreadPoolExecutor(
                    max_workers=min(len(batch_variants), CONCURRENT_SEARCH_WORKERS)
                ) as pool:
                    futures = {
                        loop.run_in_executor(pool, do_search, v, per_variant): v
                        for v in batch_variants
                    }
                    for coro in asyncio.as_completed(futures):
                        result = await coro
                        for entry in result:
                            vid = entry.get("id", "")
                            if vid and vid not in seen_ids:
                                seen_ids.add(vid)
                                batch_entries.append(entry)
            except Exception as e:
                logger.warning("YouTube 搜索批次失败: %s，继续下一批", e)
                continue

            if not batch_entries:
                continue

            # 将搜索结果转为 RawPost 并分批 yield
            if self._fast_mode:
                for entry in batch_entries:
                    if total_collected >= limit:
                        break
                    video_id = entry.get("id", "")
                    if not video_id:
                        continue
                    post = self._parse_search_entry(entry, video_id)
                    batch_buffer.append(post)
                    total_collected += 1

                    if len(batch_buffer) >= BATCH_SIZE:
                        yield batch_buffer[:BATCH_SIZE]
                        batch_buffer = batch_buffer[BATCH_SIZE:]
                        if on_progress:
                            on_progress(total_collected)
                        logger.info(
                            "YouTube 快速采集进度: %d / %d",
                            total_collected, limit,
                        )
            else:
                # 详情模式：并发提取视频详情
                semaphore = asyncio.Semaphore(self._concurrency)

                async def extract_with_semaphore(entry_item: dict) -> Optional[RawPost]:
                    video_id = entry_item.get("id", "")
                    if not video_id:
                        return None
                    async with semaphore:
                        try:
                            return await asyncio.wait_for(
                                self._extract_video_info(loop, yt_dlp, entry_item, video_id, language),
                                timeout=15.0,
                            )
                        except (asyncio.TimeoutError, Exception):
                            return self._parse_search_entry(entry_item, video_id)

                entries_to_process = batch_entries[:limit - total_collected]
                for i in range(0, len(entries_to_process), BATCH_SIZE):
                    chunk = entries_to_process[i:i + BATCH_SIZE]
                    tasks = [extract_with_semaphore(e) for e in chunk]
                    results = await asyncio.gather(*tasks)
                    for post in results:
                        if post is not None:
                            batch_buffer.append(post)
                            total_collected += 1
                    if batch_buffer:
                        yield batch_buffer
                        batch_buffer = []
                        if on_progress:
                            on_progress(total_collected)
                    await async_sleep(0.5)

        # yield 剩余数据
        if batch_buffer:
            yield batch_buffer
            if on_progress:
                on_progress(total_collected)

        logger.info(
            "YouTube yt-dlp 流式采集完成: %d 条（快速模式=%s, %d 个变体）",
            total_collected, self._fast_mode, len(variants),
        )

    async def _ytdlp_search(
        self, loop, yt_dlp, keyword: str, limit: int
    ) -> list:
        """使用 yt-dlp 搜索 YouTube 视频

        当 limit > CONCURRENT_SEARCH_THRESHOLD 时，自动生成关键词变体
        分批并发搜索，去重合并结果。达到目标数量后提前终止。

        Args:
            loop: 事件循环
            yt_dlp: yt-dlp 模块
            keyword: 搜索关键词
            limit: 搜索数量上限

        Returns:
            list: 视频条目列表（已去重）
        """
        search_opts = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": "in_playlist",
            "force_generic_extractor": False,
            "ignoreerrors": True,
        }

        if limit <= CONCURRENT_SEARCH_THRESHOLD:
            # 小量搜索，单线程即可
            return await self._single_search(loop, yt_dlp, search_opts, keyword, limit)

        # 大量搜索：分批并发多关键词变体
        variants = self._generate_search_variants(keyword)
        # 每个变体搜索 600 条（YouTube 单次搜索实际约返回 500 条）
        per_variant = min(600, limit)

        import concurrent.futures

        def do_search(query: str, n: int) -> list:
            """单个变体的搜索任务"""
            url = f"ytsearch{n}:{query}"
            try:
                with yt_dlp.YoutubeDL(search_opts) as ydl:
                    result = ydl.extract_info(url, download=False)
                    if result and "entries" in result:
                        return [e for e in result["entries"] if e is not None]
            except Exception:
                pass
            return []

        # 全局去重集合和结果列表
        seen_ids: set = set()
        unique_entries: list = []
        total_raw = 0

        # 分批并发搜索：每批 CONCURRENT_SEARCH_WORKERS 个变体
        batch_size = CONCURRENT_SEARCH_WORKERS
        for batch_start in range(0, len(variants), batch_size):
            if len(unique_entries) >= limit:
                break

            batch_variants = variants[batch_start:batch_start + batch_size]
            logger.info(
                "YouTube 搜索批次 %d-%d/%d（已采集 %d/%d 条）",
                batch_start + 1, batch_start + len(batch_variants),
                len(variants), len(unique_entries), limit,
            )

            try:
                with concurrent.futures.ThreadPoolExecutor(
                    max_workers=min(len(batch_variants), CONCURRENT_SEARCH_WORKERS)
                ) as pool:
                    futures = {
                        loop.run_in_executor(pool, do_search, v, per_variant): v
                        for v in batch_variants
                    }
                    for coro in asyncio.as_completed(futures):
                        result = await coro
                        total_raw += len(result)
                        for entry in result:
                            vid = entry.get("id", "")
                            if vid and vid not in seen_ids:
                                seen_ids.add(vid)
                                unique_entries.append(entry)

                        # 提前终止：已经够了
                        if len(unique_entries) >= limit:
                            break

            except Exception as e:
                logger.warning("YouTube 搜索批次失败: %s，继续下一批", e)
                continue

        logger.info(
            "yt-dlp 分批搜索完成: %d 条（去重前 %d 条，使用 %d/%d 个变体）",
            len(unique_entries), total_raw,
            min(len(variants), (len(unique_entries) // max(per_variant // 2, 1) + 1) * batch_size),
            len(variants),
        )
        return unique_entries[:limit]

    async def _single_search(
        self, loop, yt_dlp, search_opts: dict, keyword: str, limit: int
    ) -> list:
        """单线程 yt-dlp 搜索（基础方案）"""
        search_url = f"ytsearch{limit}:{keyword}"

        def do_search():
            with yt_dlp.YoutubeDL(search_opts) as ydl:
                result = ydl.extract_info(search_url, download=False)
                if result and "entries" in result:
                    return list(result["entries"])
                return []

        try:
            entries = await loop.run_in_executor(None, do_search)
            entries = [e for e in entries if e is not None]
            logger.info("yt-dlp 搜索到 %d 个视频", len(entries))
            return entries
        except Exception as e:
            logger.error("yt-dlp 搜索失败: %s", e)
            raise

    @staticmethod
    def _generate_search_variants(keyword: str) -> list:
        """根据关键词生成大量搜索变体，用于并发搜索大幅扩大数据量

        策略组合（目标 350+ 变体，每个变体约 300-500 条，理论上限 10 万+）：
        1. 原始关键词
        2. 时间分片（年份 + 半年 + 季度 + 月份）
        3. 内容类型后缀（tutorial, review, news, analysis 等）
        4. 排序暗示词（latest, best, top 等）
        5. 问句变体（what is, how to 等）
        6. 情感/观点变体（opinion, pros cons 等）
        7. 平台/场景变体（reddit, twitter, podcast 等）
        8. 地区/语言变体
        9. 组合变体（年份 + 类型）
        10. 受众/行业变体
        11. 视频格式/时长变体
        12. 动作/结果变体

        Args:
            keyword: 原始搜索关键词

        Returns:
            list: 关键词变体列表（包含原始关键词）
        """
        variants = [keyword]

        # 时间分片：按年份搜索
        years = ["2017", "2018", "2019", "2020", "2021", "2022", "2023", "2024", "2025", "2026"]
        for year in years:
            variants.append(f"{keyword} {year}")

        # 半年/季度分片
        half_years = [
            "early 2023", "late 2023",
            "early 2024", "late 2024", "early 2025", "late 2025",
            "Q1 2024", "Q2 2024", "Q3 2024", "Q4 2024",
            "Q1 2025", "Q2 2025", "Q3 2025", "Q4 2025",
            "Q1 2026",
        ]
        for hy in half_years:
            variants.append(f"{keyword} {hy}")

        # 月份分片（最近两年的每个月）
        months = [
            "January", "February", "March", "April", "May", "June",
            "July", "August", "September", "October", "November", "December",
        ]
        for year in ["2024", "2025"]:
            for month in months:
                variants.append(f"{keyword} {month} {year}")

        # 内容类型后缀
        content_types = [
            "explained", "tutorial", "review", "news", "analysis",
            "discussion", "update", "guide", "crash", "prediction",
            "price", "market", "beginner", "advanced", "comparison",
            "vs", "documentary", "interview", "podcast", "live",
            "breakdown", "deep dive", "reaction", "highlights",
            "summary", "tips", "strategy", "warning", "scam",
            "future", "history", "fundamentals", "technical analysis",
            "overview", "introduction", "walkthrough", "demo",
            "case study", "report", "outlook", "forecast",
            "investing", "trading", "mining", "staking",
        ]
        for ct in content_types:
            variants.append(f"{keyword} {ct}")

        # 排序暗示词
        sort_hints = [
            "latest", "best", "top", "new", "most popular", "trending",
            "viral", "must watch", "important", "breaking",
            "ultimate", "complete", "full", "comprehensive",
            "2024", "2025", "today", "this week", "this month",
        ]
        for hint in sort_hints:
            variants.append(f"{hint} {keyword}")

        # 问句变体
        question_prefixes = [
            "what is", "how to", "why", "should I", "is it worth",
            "how does", "when to", "where to", "can you", "will",
            "what happened to", "how much", "who uses",
            "is it safe", "is it legal", "what are the risks",
            "how to start", "how to buy", "how to sell",
            "what are the best", "which is better",
        ]
        for prefix in question_prefixes:
            variants.append(f"{prefix} {keyword}")

        # 情感/观点变体
        opinion_suffixes = [
            "opinion", "pros and cons", "worth it", "scam or legit",
            "honest review", "warning", "risk", "benefits",
            "advantages", "disadvantages", "truth about",
            "myths", "facts", "mistakes", "secrets",
            "success story", "failure", "lessons learned",
            "experience", "testimony", "real talk",
        ]
        for suffix in opinion_suffixes:
            variants.append(f"{keyword} {suffix}")

        # 平台/场景变体
        platform_suffixes = [
            "reddit", "twitter", "tiktok", "podcast", "conference",
            "webinar", "course", "class", "lecture", "talk",
            "debate", "panel", "summit", "expo",
            "stream", "vlog", "shorts", "compilation",
            "news channel", "documentary film",
        ]
        for ps in platform_suffixes:
            variants.append(f"{keyword} {ps}")

        # 地区/语言变体
        regions = [
            "USA", "Europe", "Asia", "China", "Japan", "Korea",
            "India", "UK", "Germany", "France", "Brazil",
            "Canada", "Australia", "Russia", "Africa",
            "español", "中文", "日本語", "한국어", "deutsch",
            "português", "français", "italiano", "हिन्दी",
        ]
        for region in regions:
            variants.append(f"{keyword} {region}")

        # 受众/行业变体
        audience_suffixes = [
            "for beginners", "for experts", "for investors",
            "for developers", "for students", "for business",
            "for dummies", "simplified", "in depth",
            "professional", "enterprise", "startup",
            "mainstream", "institutional", "retail",
        ]
        for suffix in audience_suffixes:
            variants.append(f"{keyword} {suffix}")

        # 视频格式/时长变体
        format_prefixes = [
            "short", "long", "full", "quick", "detailed",
            "animated", "whiteboard", "infographic",
        ]
        for prefix in format_prefixes:
            variants.append(f"{prefix} {keyword}")

        # 组合变体：年份 + 内容类型（高价值组合）
        combo_types = [
            "news", "analysis", "review", "prediction", "update",
            "crash", "price", "guide", "tutorial", "explained",
            "outlook", "forecast", "summary",
        ]
        combo_years = ["2022", "2023", "2024", "2025", "2026"]
        for year in combo_years:
            for ct in combo_types:
                variants.append(f"{keyword} {ct} {year}")

        # 否定/对比变体
        contrast_variants = [
            f"{keyword} vs gold", f"{keyword} vs stocks",
            f"{keyword} vs ethereum", f"{keyword} vs dollar",
            f"{keyword} vs real estate", f"{keyword} vs bonds",
            f"why not {keyword}", f"{keyword} dead",
            f"{keyword} bull run", f"{keyword} bear market",
            f"{keyword} all time high", f"{keyword} bottom",
            f"{keyword} bubble", f"{keyword} rally",
            f"{keyword} dump", f"{keyword} pump",
            f"alternatives to {keyword}", f"{keyword} competitors",
        ]
        variants.extend(contrast_variants)

        # 动作/结果变体
        action_variants = [
            f"buy {keyword}", f"sell {keyword}", f"hold {keyword}",
            f"earn {keyword}", f"make money with {keyword}",
            f"profit from {keyword}", f"lose money {keyword}",
            f"get started {keyword}", f"learn {keyword}",
            f"understand {keyword}", f"master {keyword}",
        ]
        variants.extend(action_variants)

        # 去重
        seen = set()
        unique_variants = []
        for v in variants:
            v_lower = v.lower().strip()
            if v_lower not in seen:
                seen.add(v_lower)
                unique_variants.append(v)

        # 提升上限到 400 个变体（400 × ~300 条/变体去重后 ≈ 10 万+）
        max_variants = min(len(unique_variants), 400)
        logger.info("YouTube 搜索变体: 生成 %d 个（上限 400）", max_variants)
        return unique_variants[:max_variants]

    async def _extract_video_info(
        self,
        loop,
        yt_dlp,
        entry: dict,
        video_id: str,
        language: str,
    ) -> Optional[RawPost]:
        """提取单个视频的详细信息

        从搜索结果条目中提取元数据，尝试获取评论和字幕。

        Args:
            loop: 事件循环
            yt_dlp: yt-dlp 模块
            entry: 搜索结果条目
            video_id: 视频 ID
            language: 语言代码

        Returns:
            RawPost: 解析后的帖子对象，失败返回 None
        """
        try:
            title = entry.get("title", "")
            # 尝试获取详细信息（元数据 + 评论）
            detail = await self._ytdlp_extract_detail(
                loop, yt_dlp, video_id, language
            )

            if detail:
                return self._parse_video_detail(detail, video_id, language)
            else:
                # 使用搜索结果中的基本信息
                return self._parse_search_entry(entry, video_id)
        except Exception as e:
            logger.warning("提取视频 %s 信息失败: %s", video_id, e)
            return None

    async def _ytdlp_extract_detail(
        self, loop, yt_dlp, video_id: str, language: str
    ) -> Optional[dict]:
        """使用 yt-dlp 提取视频详细信息（元数据 + 评论）

        Args:
            loop: 事件循环
            yt_dlp: yt-dlp 模块
            video_id: 视频 ID
            language: 语言代码

        Returns:
            dict: 视频详细信息，失败返回 None
        """
        detail_opts = {
            "quiet": True,
            "no_warnings": True,
            "ignoreerrors": True,
            "skip_download": True,
            "getcomments": True,
            "writesubtitles": False,
            "writeautomaticsub": False,
            "subtitleslangs": [language],
        }

        video_url = f"https://www.youtube.com/watch?v={video_id}"

        def do_extract():
            with yt_dlp.YoutubeDL(detail_opts) as ydl:
                return ydl.extract_info(video_url, download=False)

        try:
            return await loop.run_in_executor(None, do_extract)
        except Exception as e:
            logger.debug("yt-dlp 提取视频 %s 详情失败: %s", video_id, e)
            return None

    def _parse_video_detail(
        self, detail: dict, video_id: str, language: str
    ) -> RawPost:
        """解析 yt-dlp 返回的视频详细信息

        Args:
            detail: yt-dlp 返回的视频信息字典
            video_id: 视频 ID
            language: 语言代码

        Returns:
            RawPost: 解析后的帖子对象
        """
        title = detail.get("title", "")
        description = detail.get("description", "")
        uploader = detail.get("uploader", "") or detail.get("channel", "unknown")
        view_count = detail.get("view_count", 0) or 0
        like_count = detail.get("like_count", 0) or 0
        comment_count = detail.get("comment_count", 0) or 0
        upload_date = detail.get("upload_date", "")

        # 解析上传日期
        timestamp = self._parse_upload_date(upload_date)

        # 构建内容：描述 + 字幕 + 热门评论
        content_parts: List[str] = []
        if description:
            content_parts.append(description[:2000])

        # 提取字幕文本
        subtitle_text = self._extract_subtitle_from_detail(detail, language)
        if subtitle_text:
            content_parts.append(f"[字幕] {subtitle_text}")

        # 提取热门评论
        comments_text = self._extract_comments_from_detail(detail)
        if comments_text:
            content_parts.append(f"[评论] {comments_text}")

        content = "\n\n".join(content_parts) if content_parts else title

        return RawPost(
            id=str(uuid.uuid4()),
            source=DataSource.YOUTUBE,
            external_id=video_id,
            title=title,
            content=content,
            author=uploader or "unknown",
            url=f"https://www.youtube.com/watch?v={video_id}",
            timestamp=timestamp,
            likes=int(like_count) if isinstance(like_count, (int, float)) else 0,
            comments=int(comment_count) if isinstance(comment_count, (int, float)) else 0,
            shares=0,
        )

    def _parse_search_entry(self, entry: dict, video_id: str) -> RawPost:
        """解析搜索结果条目为 RawPost（基本信息）

        当无法获取详细信息时使用搜索结果中的基本数据。

        Args:
            entry: 搜索结果条目
            video_id: 视频 ID

        Returns:
            RawPost: 解析后的帖子对象
        """
        title = entry.get("title", "")
        uploader = entry.get("uploader", "") or entry.get("channel", "unknown")
        view_count = entry.get("view_count", 0) or 0
        duration = entry.get("duration", 0) or 0

        return RawPost(
            id=str(uuid.uuid4()),
            source=DataSource.YOUTUBE,
            external_id=video_id,
            title=title,
            content=title or f"YouTube video {video_id}",
            author=uploader or "unknown",
            url=f"https://www.youtube.com/watch?v={video_id}",
            timestamp=datetime.now(timezone.utc),
            likes=int(view_count) if isinstance(view_count, (int, float)) else 0,
            comments=0,
            shares=0,
        )

    @staticmethod
    def _parse_upload_date(upload_date: str) -> datetime:
        """解析 yt-dlp 返回的上传日期字符串

        Args:
            upload_date: 格式为 YYYYMMDD 的日期字符串

        Returns:
            datetime: 解析后的日期时间对象
        """
        if upload_date and len(upload_date) == 8:
            try:
                return datetime.strptime(upload_date, "%Y%m%d").replace(
                    tzinfo=timezone.utc
                )
            except ValueError:
                pass
        return datetime.now(timezone.utc)

    @staticmethod
    def _extract_subtitle_from_detail(
        detail: dict, language: str
    ) -> Optional[str]:
        """从 yt-dlp 详情中提取字幕文本

        Args:
            detail: yt-dlp 返回的视频信息字典
            language: 语言代码

        Returns:
            str: 字幕文本，无字幕返回 None
        """
        subtitles = detail.get("subtitles", {})
        auto_subs = detail.get("automatic_captions", {})

        # 优先使用手动字幕，其次自动字幕
        sub_list = subtitles.get(language) or auto_subs.get(language)
        if not sub_list:
            return None

        # 查找 JSON3 或 VTT 格式的字幕
        for sub in sub_list:
            if isinstance(sub, dict) and sub.get("ext") in ("json3", "vtt", "srv1"):
                # yt-dlp 有时会直接在 data 字段中包含字幕内容
                data = sub.get("data", "")
                if data:
                    return data[:2000]

        return None

    @staticmethod
    def _extract_comments_from_detail(detail: dict) -> Optional[str]:
        """从 yt-dlp 详情中提取热门评论

        Args:
            detail: yt-dlp 返回的视频信息字典

        Returns:
            str: 评论文本摘要，无评论返回 None
        """
        comments = detail.get("comments", [])
        if not comments:
            return None

        # 取前 10 条热门评论
        top_comments = comments[:10]
        comment_texts = []
        for c in top_comments:
            if isinstance(c, dict):
                text = c.get("text", "")
                if text:
                    comment_texts.append(text[:200])

        if comment_texts:
            return " | ".join(comment_texts)
        return None

    async def _collect_playwright(
        self,
        keyword: str,
        limit: int,
        on_progress: Optional[Callable[[int], None]] = None,
    ) -> AsyncGenerator[List[RawPost], None]:
        """通过 Playwright 爬虫采集 YouTube 数据（降级方案）

        当 yt-dlp 不可用时使用此方案。
        使用现有的 YouTubeCollector 爬虫逻辑。

        Args:
            keyword: 搜索关键词
            limit: 采集条数上限（爬虫模式建议不超过 500）
            on_progress: 进度回调
        """
        from backend.app.collectors.youtube_collector import YouTubeCollector

        # 爬虫模式限制上限
        effective_limit = min(limit, 500)
        if limit > 500:
            logger.warning(
                "Playwright 爬虫模式上限 500 条，请求 %d 条将被截断", limit
            )

        collector = YouTubeCollector()
        try:
            posts = await collector.collect(
                keyword, effective_limit, self._language
            )

            # 按 BATCH_SIZE 分批 yield
            for i in range(0, len(posts), BATCH_SIZE):
                batch = posts[i : i + BATCH_SIZE]
                yield batch
                if on_progress:
                    on_progress(min(i + BATCH_SIZE, len(posts)))

            logger.info("YouTube Playwright 采集完成: %d 条", len(posts))
        finally:
            await collector.close()

    async def close(self) -> None:
        """释放资源"""
        pass
