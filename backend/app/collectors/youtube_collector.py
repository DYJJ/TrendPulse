"""
YouTube数据采集器

支持两种采集模式：
1. API模式（YouTube Data API v3）：配置了YOUTUBE_API_KEY时使用，速度快
2. 爬虫模式（Playwright）：未配置API时降级使用

需求: 3.1-3.5
"""

import asyncio
import logging
import random
import re
import uuid
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

from backend.app.collectors.base import BaseCollector
from backend.app.models.data_models import DataSource, RawPost

logger = logging.getLogger(__name__)
MAX_RETRIES = 3


class YouTubeCollector(BaseCollector):
    """YouTube数据采集器

    自动检测是否配置了YouTube Data API Key：
    - 有Key：使用官方API批量搜索+获取视频详情
    - 无Key：降级为Playwright爬虫
    """

    source = DataSource.YOUTUBE

    def __init__(self, api_key: str = "") -> None:
        """初始化YouTube采集器

        Args:
            api_key: YouTube Data API v3密钥
        """
        self._api_key = api_key
        self._use_api = bool(api_key)
        self._playwright = None
        self._browser = None
        if self._use_api:
            logger.info("YouTube采集器: 使用API模式")
        else:
            logger.info("YouTube采集器: 未配置API Key，使用爬虫降级模式")

    async def _extract_transcript(self, video_id: str) -> Optional[str]:
        """提取视频字幕"""
        if not video_id:
            return None
        try:
            from youtube_transcript_api import YouTubeTranscriptApi
            loop = asyncio.get_event_loop()
            transcript_list = await loop.run_in_executor(
                None,
                lambda: YouTubeTranscriptApi.get_transcript(video_id),
            )
            text = " ".join(entry["text"] for entry in transcript_list)
            return text[:2000]
        except Exception:
            return None

    async def _collect_via_api(
        self, keyword: str, limit: int, language: str = "en",
        on_progress: Optional[Callable[[int], None]] = None,
    ) -> List[RawPost]:
        """通过YouTube Data API v3批量采集"""
        from googleapiclient.discovery import build

        loop = asyncio.get_event_loop()
        youtube = await loop.run_in_executor(
            None, lambda: build("youtube", "v3", developerKey=self._api_key),
        )
        posts: List[RawPost] = []
        next_page_token = None
        batch_count = 0

        try:
            while len(posts) < limit:
                max_results = min(50, limit - len(posts))
                search_req = youtube.search().list(
                    q=keyword, part="id,snippet", type="video",
                    maxResults=max_results, order="relevance",
                    relevanceLanguage=language, pageToken=next_page_token,
                )
                search_resp = await loop.run_in_executor(None, search_req.execute)
                items = search_resp.get("items", [])
                if not items:
                    break

                video_ids = [i["id"]["videoId"] for i in items if i["id"].get("videoId")]
                if video_ids:
                    vid_req = youtube.videos().list(
                        id=",".join(video_ids), part="snippet,statistics",
                    )
                    vid_resp = await loop.run_in_executor(None, vid_req.execute)
                    for video in vid_resp.get("items", []):
                        if len(posts) >= limit:
                            break
                        snippet = video.get("snippet", {})
                        stats = video.get("statistics", {})
                        published = snippet.get("publishedAt", "")
                        try:
                            timestamp = datetime.fromisoformat(published.replace("Z", "+00:00"))
                        except (ValueError, AttributeError):
                            timestamp = datetime.now(timezone.utc)

                        transcript = await self._extract_transcript(video["id"])
                        parts = []
                        desc = snippet.get("description", "")
                        if desc:
                            parts.append(desc)
                        if transcript:
                            parts.append(f"[字幕] {transcript}")
                        content = "\n\n".join(parts) if parts else snippet.get("title", "")

                        posts.append(RawPost(
                            id=str(uuid.uuid4()), source=DataSource.YOUTUBE,
                            external_id=video["id"],
                            title=snippet.get("title"),
                            content=content,
                            author=snippet.get("channelTitle", "unknown"),
                            url=f"https://www.youtube.com/watch?v={video['id']}",
                            timestamp=timestamp,
                            likes=int(stats.get("viewCount", 0)),
                            comments=int(stats.get("commentCount", 0)),
                            shares=0,
                        ))
                        batch_count += 1

                if on_progress and batch_count % 200 == 0:
                    on_progress(len(posts))
                next_page_token = search_resp.get("nextPageToken")
                if not next_page_token:
                    break
                await asyncio.sleep(0.2)
        except Exception as e:
            logger.error("YouTube API采集异常: %s，已采集 %d 条", e, len(posts))
            if not posts:
                raise

        if on_progress:
            on_progress(len(posts))
        logger.info("YouTube API采集完成: %d 条", len(posts))
        return posts

    async def _collect_via_scraper(
        self, keyword: str, limit: int, language: str = "en",
    ) -> List[RawPost]:
        """通过Playwright爬虫采集（降级方案）"""
        from playwright.async_api import async_playwright

        if self._playwright is None:
            self._playwright = await async_playwright().start()
        if self._browser is None or not self._browser.is_connected():
            self._browser = await self._playwright.chromium.launch(
                headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
        context = await self._browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0",
            viewport={"width": 1920, "height": 1080},
        )
        page = await context.new_page()
        posts: List[RawPost] = []
        try:
            await page.goto(
                f"https://www.youtube.com/results?search_query={keyword}",
                wait_until="domcontentloaded", timeout=30000,
            )
            await asyncio.sleep(random.uniform(1.5, 3.0))
            try:
                btn = await page.query_selector("button[aria-label*='Accept']")
                if btn:
                    await btn.click()
                    await asyncio.sleep(1)
            except Exception:
                pass
            await page.wait_for_selector("ytd-video-renderer", timeout=15000)

            scroll_attempts = 0
            while len(posts) < limit and scroll_attempts < 10:
                elements = await page.query_selector_all("ytd-video-renderer")
                for el in elements[len(posts):]:
                    if len(posts) >= limit:
                        break
                    try:
                        title_el = await el.query_selector("a#video-title")
                        title = await title_el.get_attribute("title") if title_el else ""
                        href = await title_el.get_attribute("href") if title_el else ""
                        video_url = f"https://www.youtube.com{href}" if href else ""
                        video_id = ""
                        if href:
                            m = re.search(r"v=([a-zA-Z0-9_-]+)", href)
                            if m:
                                video_id = m.group(1)
                        channel_el = await el.query_selector("ytd-channel-name a")
                        author = await channel_el.inner_text() if channel_el else "unknown"
                        posts.append(RawPost(
                            id=str(uuid.uuid4()), source=DataSource.YOUTUBE,
                            external_id=video_id,
                            title=title.strip() if title else None,
                            content=title or "", author=author.strip() or "unknown",
                            url=video_url, timestamp=datetime.now(timezone.utc),
                            likes=0, comments=0, shares=0,
                        ))
                    except Exception as e:
                        logger.warning("YouTube爬虫: 提取视频失败: %s", e)
                if len(posts) >= limit:
                    break
                await page.evaluate("window.scrollBy(0, 1000)")
                await asyncio.sleep(random.uniform(1.5, 3.0))
                scroll_attempts += 1
        finally:
            await context.close()
        logger.info("YouTube爬虫采集完成: %d 条", len(posts))
        return posts[:limit]

    async def collect(
        self, keyword: str, limit: int, language: str = "en",
        on_progress: Optional[Callable[[int], None]] = None,
    ) -> List[RawPost]:
        """采集YouTube视频数据（带重试）"""
        if limit > 1000 and not self._use_api:
            logger.warning("YouTube: 请求 %d 条但未配置API，限制为500条", limit)
            limit = 500
        last_error: Optional[Exception] = None
        for attempt in range(MAX_RETRIES):
            try:
                if self._use_api:
                    return await self._collect_via_api(keyword, limit, language, on_progress)
                else:
                    return await self._collect_via_scraper(keyword, limit, language)
            except Exception as e:
                last_error = e
                logger.warning("YouTube采集器: 第 %d/%d 次失败: %s", attempt + 1, MAX_RETRIES, e)
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep((attempt + 1) * 2.0)
        raise last_error  # type: ignore[misc]

    async def close(self) -> None:
        """释放资源"""
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None
