"""
RSS 聚合采集提供者

从 Google News RSS 等预配置源获取包含推文引用的新闻条目。
支持 Twitter 链接检测与 SyndicationProvider 补全、源不可用降级处理。
"""

import hashlib
import logging
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import AsyncGenerator, Callable, List, Optional, Set
from xml.etree.ElementTree import Element

import aiohttp
import defusedxml.ElementTree as ET

from backend.app.collectors.zero_cost.constants import (
    BATCH_SIZE,
    SEARCH_DELAY_MIN,
    SEARCH_DELAY_MAX,
)
from backend.app.collectors.zero_cost.syndication_provider import SyndicationProvider
from backend.app.collectors.zero_cost.utils import (
    extract_tweet_id,
    generate_raw_post_id,
    random_delay,
    random_user_agent,
)
from backend.app.models.data_models import DataSource, RawPost

logger = logging.getLogger(__name__)

# 预配置 RSS 源模板列表
# {keyword} 占位符会被替换为实际搜索关键词
RSS_FEED_TEMPLATES = [
    # Google News RSS
    "https://news.google.com/rss/search?q={keyword}+site:x.com&hl=en-US&gl=US&ceid=US:en",
    # Reddit RSS（搜索包含关键词的帖子）
    "https://www.reddit.com/search.rss?q={keyword}+twitter&sort=new&limit=100",
]


class RSSProvider:
    """RSS 聚合采集提供者

    从预配置的 RSS 源列表获取条目，检测其中的 Twitter 链接，
    有则通过 SyndicationProvider 补全推文详情，无则将 RSS 条目
    本身转换为 RawPost。支持源不可用时的降级跳过。
    """

    def __init__(self, session: Optional[aiohttp.ClientSession] = None, proxy: Optional[str] = None) -> None:
        """初始化 RSSProvider

        Args:
            session: 可选的 aiohttp 会话，未提供时自动创建
            proxy: HTTP 代理地址（可选），如 http://127.0.0.1:7890
        """
        self._external_session = session is not None
        self._session = session
        self._proxy = proxy

    async def _get_session(self) -> aiohttp.ClientSession:
        """获取或创建 aiohttp 会话"""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def _fetch_feed_xml(self, url: str) -> Optional[str]:
        """获取 RSS 源的 XML 内容

        Args:
            url: RSS 源 URL

        Returns:
            XML 文本内容，失败时返回 None
        """
        session = await self._get_session()
        headers = {"User-Agent": random_user_agent()}
        try:
            async with session.get(
                url,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=15),
                proxy=self._proxy,
            ) as resp:
                if resp.status != 200:
                    logger.warning("RSS 源返回状态码 %d: %s", resp.status, url)
                    return None
                return await resp.text()
        except aiohttp.ClientError as e:
            logger.warning("RSS 源网络错误: %s, URL: %s", e, url)
            return None
        except Exception as e:
            logger.warning("RSS 源请求异常: %s, URL: %s", e, url)
            return None

    @staticmethod
    def _parse_xml_items(xml_text: str) -> List[Element]:
        """从 RSS XML 中解析所有条目元素

        支持标准 RSS 2.0（<item>）和 Atom（<entry>）格式。

        Args:
            xml_text: RSS XML 文本

        Returns:
            条目 Element 列表，解析失败返回空列表
        """
        try:
            root = ET.fromstring(xml_text)
        except Exception as e:
            logger.warning("RSS XML 解析失败: %s", e)
            return []

        # RSS 2.0 格式：channel/item
        items = root.findall(".//item")
        if items:
            return items

        # Atom 格式：需要处理命名空间
        # 尝试带命名空间的 entry
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        entries = root.findall(".//atom:entry", ns)
        if entries:
            return entries

        # 无命名空间的 entry
        entries = root.findall(".//entry")
        return entries

    @staticmethod
    def parse_rss_entry(entry: dict) -> Optional[RawPost]:
        """将 RSS 条目解析为 RawPost

        从条目字典中提取标题、摘要、发布时间和链接，
        转换为统一的 RawPost 对象。缺少必填字段时返回 None。

        条目字典应包含以下键：
        - title: 条目标题
        - description: 条目摘要/内容
        - link: 条目链接
        - pub_date: 发布时间字符串（可选）
        - source_name: 来源名称（可选，用作 author）

        Args:
            entry: RSS 条目字典

        Returns:
            解析成功返回 RawPost 对象，数据无效时返回 None
        """
        try:
            title = entry.get("title", "")
            content = entry.get("description", "")
            link = entry.get("link", "")
            source_name = entry.get("source_name", "RSS")

            # content 和 author（source_name）为必填字段
            if not content:
                logger.warning("RSS 条目缺少内容字段，跳过")
                return None
            if not source_name:
                logger.warning("RSS 条目缺少来源名称，跳过")
                return None

            # 解析发布时间
            pub_date_str = entry.get("pub_date", "")
            timestamp = _parse_pub_date(pub_date_str)

            # 生成唯一 ID（基于链接或内容的哈希）
            id_source = link or content
            entry_hash = hashlib.md5(id_source.encode("utf-8")).hexdigest()[:16]
            external_id = entry.get("guid", entry_hash)

            return RawPost(
                id=generate_raw_post_id("rss", external_id),
                source=DataSource.TWITTER,
                external_id=external_id,
                title=title or None,
                content=content,
                author=source_name,
                url=link,
                timestamp=timestamp,
                likes=0,
                comments=0,
                shares=0,
            )

        except Exception as e:
            logger.error("解析 RSS 条目失败: %s", e)
            return None

    @staticmethod
    def _extract_entry_dict(item: Element) -> dict:
        """从 XML Element 提取条目字典

        兼容 RSS 2.0 和 Atom 格式的字段名差异。

        Args:
            item: XML 条目元素

        Returns:
            标准化的条目字典
        """
        ns = {"atom": "http://www.w3.org/2005/Atom"}

        def _text(tag: str, atom_tag: Optional[str] = None) -> str:
            """尝试获取元素文本，优先 RSS 2.0 标签，其次 Atom 标签"""
            el = item.find(tag)
            if el is not None and el.text:
                return el.text.strip()
            if atom_tag:
                el = item.find(atom_tag, ns)
                if el is not None and el.text:
                    return el.text.strip()
            return ""

        # 提取链接（Atom 格式使用 href 属性）
        link = _text("link", "atom:link")
        if not link:
            link_el = item.find("link")
            if link_el is not None and link_el.get("href"):
                link = link_el.get("href", "")
            else:
                link_el = item.find("atom:link", ns)
                if link_el is not None:
                    link = link_el.get("href", "")

        # 提取 GUID
        guid = _text("guid", "atom:id")

        return {
            "title": _text("title", "atom:title"),
            "description": _text("description", "atom:summary")
            or _text("content:encoded", "atom:content"),
            "link": link,
            "pub_date": _text("pubDate", "atom:published")
            or _text("atom:updated"),
            "guid": guid,
            "source_name": _text("source") or "RSS",
        }

    async def collect(
        self,
        keyword: str,
        limit: int,
        seen_ids: Optional[Set[str]] = None,
        syndication: Optional[SyndicationProvider] = None,
        on_progress: Optional[Callable[[int], None]] = None,
    ) -> AsyncGenerator[List[RawPost], None]:
        """通过 RSS 源采集数据

        从预配置的 RSS 源列表中搜索包含关键词的条目。
        检测条目中的 Twitter 链接，有则通过 SyndicationProvider 补全，
        无则将 RSS 条目本身转换为 RawPost。每 500 条 yield 一批。

        Args:
            keyword: 搜索关键词
            limit: 采集条数上限
            seen_ids: 已采集的 ID 集合（用于去重）
            syndication: SyndicationProvider 实例（用于补全推文详情）
            on_progress: 进度回调函数，参数为已采集条数

        Yields:
            List[RawPost]: 每次 yield 一批数据（最多 500 条）
        """
        if seen_ids is None:
            seen_ids = set()

        batch_buffer: List[RawPost] = []
        total_collected = 0

        for template in RSS_FEED_TEMPLATES:
            if total_collected >= limit:
                break

            feed_url = template.format(keyword=keyword)
            logger.info("正在获取 RSS 源: %s", feed_url)

            # 请求间随机延迟
            await random_delay(SEARCH_DELAY_MIN, SEARCH_DELAY_MAX)

            # 获取 RSS XML
            xml_text = await self._fetch_feed_xml(feed_url)
            if xml_text is None:
                logger.warning("RSS 源不可用，跳过: %s", feed_url)
                continue

            # 解析 XML 条目
            items = self._parse_xml_items(xml_text)
            if not items:
                logger.info("RSS 源无条目: %s", feed_url)
                continue

            for item in items:
                if total_collected >= limit:
                    break

                entry_dict = self._extract_entry_dict(item)
                link = entry_dict.get("link", "")

                # 检测 Twitter 链接
                tweet_id = extract_tweet_id(link) if link else None

                raw_post: Optional[RawPost] = None

                if tweet_id and syndication:
                    # 有 Twitter 链接且有 SyndicationProvider，补全推文详情
                    raw_post = await syndication.fetch_tweet(tweet_id)
                elif tweet_id:
                    # 有 Twitter 链接但无 SyndicationProvider，用 RSS 数据构造
                    entry_dict["source_name"] = entry_dict.get("source_name", "RSS")
                    raw_post = self.parse_rss_entry(entry_dict)
                else:
                    # 无 Twitter 链接，直接用 RSS 条目
                    raw_post = self.parse_rss_entry(entry_dict)

                if raw_post is None:
                    continue

                # 去重检查
                if raw_post.external_id in seen_ids:
                    continue
                seen_ids.add(raw_post.external_id)

                batch_buffer.append(raw_post)
                total_collected += 1

                # 批次满时 yield
                if len(batch_buffer) >= BATCH_SIZE:
                    yield batch_buffer[:BATCH_SIZE]
                    batch_buffer = batch_buffer[BATCH_SIZE:]
                    if on_progress:
                        on_progress(total_collected)
                    logger.info("RSS 采集进度: %d 条", total_collected)

        # yield 剩余数据
        if batch_buffer:
            yield batch_buffer
            if on_progress:
                on_progress(total_collected)

        logger.info("RSS 采集完成: 共 %d 条", total_collected)

    async def close(self) -> None:
        """释放 aiohttp 会话资源

        仅关闭内部创建的会话，外部传入的会话不做处理。
        """
        if self._session and not self._external_session:
            await self._session.close()
            self._session = None


def _parse_pub_date(date_str: str) -> datetime:
    """解析 RSS 发布时间字符串

    支持 RFC 2822 格式（RSS 2.0）和 ISO 8601 格式（Atom）。

    Args:
        date_str: 时间字符串

    Returns:
        解析后的 datetime 对象，解析失败返回当前 UTC 时间
    """
    if not date_str:
        return datetime.now(timezone.utc)

    # 尝试 RFC 2822 格式（如 "Mon, 01 Jan 2024 12:00:00 GMT"）
    try:
        return parsedate_to_datetime(date_str)
    except (ValueError, TypeError):
        pass

    # 尝试 ISO 8601 格式
    try:
        return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    except (ValueError, TypeError, AttributeError):
        pass

    return datetime.now(timezone.utc)
