"""
RSSProvider 单元测试

使用固定 RSS XML 样本测试解析、Twitter 链接提取和源不可用跳过逻辑。

需求: 4.2, 4.3, 4.5
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from backend.app.collectors.zero_cost.rss_provider import RSSProvider
from backend.app.models.data_models import DataSource


# === 固定 RSS XML 样本 ===

SAMPLE_RSS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Test Feed</title>
    <item>
      <title>推文转载：AI 技术突破</title>
      <description>这是一条关于 AI 技术突破的推文内容</description>
      <link>https://x.com/testuser/status/1234567890</link>
      <pubDate>Mon, 20 Jan 2025 10:00:00 GMT</pubDate>
      <guid>item-001</guid>
      <source>Tech News</source>
    </item>
    <item>
      <title>普通新闻：市场分析</title>
      <description>这是一条普通新闻，不包含 Twitter 链接</description>
      <link>https://example.com/news/market-analysis</link>
      <pubDate>Tue, 21 Jan 2025 08:30:00 GMT</pubDate>
      <guid>item-002</guid>
      <source>Finance Daily</source>
    </item>
  </channel>
</rss>"""

SAMPLE_RSS_XML_EMPTY = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Empty Feed</title>
  </channel>
</rss>"""

SAMPLE_INVALID_XML = """<not valid xml at all!!!"""


# === 测试: 使用固定 RSS XML 样本测试解析 ===


class TestParseRssEntry:
    """测试 parse_rss_entry 静态方法的解析逻辑"""

    def test_parse_valid_entry(self):
        """有效的 RSS 条目应正确解析为 RawPost"""
        entry = {
            "title": "测试标题",
            "description": "这是测试内容",
            "link": "https://example.com/article",
            "pub_date": "Mon, 20 Jan 2025 10:00:00 GMT",
            "guid": "test-guid-001",
            "source_name": "Test Source",
        }
        result = RSSProvider.parse_rss_entry(entry)

        assert result is not None
        assert result.source == DataSource.TWITTER
        assert result.content == "这是测试内容"
        assert result.author == "Test Source"
        assert result.url == "https://example.com/article"
        assert result.external_id == "test-guid-001"
        assert result.id == "rss_test-guid-001"
        assert isinstance(result.timestamp, datetime)

    def test_parse_missing_content_returns_none(self):
        """缺少 description 字段应返回 None"""
        entry = {
            "title": "标题",
            "description": "",
            "link": "https://example.com",
            "source_name": "Source",
        }
        assert RSSProvider.parse_rss_entry(entry) is None

    def test_parse_missing_author_returns_none(self):
        """source_name 为空应返回 None"""
        entry = {
            "title": "标题",
            "description": "有内容",
            "link": "https://example.com",
            "source_name": "",
        }
        assert RSSProvider.parse_rss_entry(entry) is None

    def test_parse_uses_hash_when_no_guid(self):
        """无 guid 时应使用链接哈希作为 external_id"""
        entry = {
            "title": "标题",
            "description": "内容",
            "link": "https://example.com/unique",
            "source_name": "RSS",
        }
        result = RSSProvider.parse_rss_entry(entry)
        assert result is not None
        # 无 guid 时 external_id 应为链接的 md5 前 16 位
        assert len(result.external_id) == 16
        assert result.id.startswith("rss_")

    def test_parse_default_source_name(self):
        """未提供 source_name 时应默认为 'RSS'"""
        entry = {
            "title": "标题",
            "description": "内容",
            "link": "https://example.com",
        }
        result = RSSProvider.parse_rss_entry(entry)
        assert result is not None
        assert result.author == "RSS"


# === 测试: XML 解析与条目提取 ===


class TestParseXmlItems:
    """测试 _parse_xml_items 和 _extract_entry_dict"""

    def test_parse_rss20_items(self):
        """标准 RSS 2.0 XML 应正确解析出条目"""
        items = RSSProvider._parse_xml_items(SAMPLE_RSS_XML)
        assert len(items) == 2

    def test_parse_empty_feed(self):
        """空 RSS 源应返回空列表"""
        items = RSSProvider._parse_xml_items(SAMPLE_RSS_XML_EMPTY)
        assert items == []

    def test_parse_invalid_xml(self):
        """无效 XML 应返回空列表而非抛出异常"""
        items = RSSProvider._parse_xml_items(SAMPLE_INVALID_XML)
        assert items == []

    def test_extract_entry_dict_fields(self):
        """_extract_entry_dict 应正确提取条目字段"""
        items = RSSProvider._parse_xml_items(SAMPLE_RSS_XML)
        entry_dict = RSSProvider._extract_entry_dict(items[0])

        assert entry_dict["title"] == "推文转载：AI 技术突破"
        assert entry_dict["description"] == "这是一条关于 AI 技术突破的推文内容"
        assert entry_dict["link"] == "https://x.com/testuser/status/1234567890"
        assert entry_dict["guid"] == "item-001"
        assert entry_dict["source_name"] == "Tech News"


# === 测试: Twitter 链接提取 ===


class TestTwitterLinkExtraction:
    """测试 collect 方法中的 Twitter 链接检测与 SyndicationProvider 补全

    需求 4.3: 检测条目中的 Twitter 链接，有则通过 SyndicationProvider 补全
    """

    @pytest.mark.asyncio
    async def test_twitter_link_triggers_syndication(self):
        """包含 Twitter 链接的条目应调用 SyndicationProvider 补全"""
        provider = RSSProvider(session=AsyncMock())
        mock_syndication = AsyncMock()
        # syndication 返回一个 mock RawPost
        mock_raw_post = MagicMock()
        mock_raw_post.external_id = "1234567890"
        mock_syndication.fetch_tweet = AsyncMock(return_value=mock_raw_post)

        with patch.object(provider, "_fetch_feed_xml", new_callable=AsyncMock, return_value=SAMPLE_RSS_XML):
            with patch("backend.app.collectors.zero_cost.rss_provider.random_delay", new_callable=AsyncMock):
                batches = []
                async for batch in provider.collect(
                    "AI", limit=10, syndication=mock_syndication
                ):
                    batches.append(batch)

        # 第一条包含 x.com 链接，应调用 syndication
        mock_syndication.fetch_tweet.assert_called_with("1234567890")

    @pytest.mark.asyncio
    async def test_non_twitter_link_uses_rss_entry(self):
        """不包含 Twitter 链接的条目应直接用 RSS 数据构造 RawPost"""
        # 只包含非 Twitter 链接的 XML
        xml_no_twitter = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <item>
      <title>普通新闻</title>
      <description>普通新闻内容</description>
      <link>https://example.com/news</link>
      <pubDate>Mon, 20 Jan 2025 10:00:00 GMT</pubDate>
      <source>News Source</source>
    </item>
  </channel>
</rss>"""
        provider = RSSProvider(session=AsyncMock())

        with patch.object(provider, "_fetch_feed_xml", new_callable=AsyncMock, return_value=xml_no_twitter):
            with patch("backend.app.collectors.zero_cost.rss_provider.random_delay", new_callable=AsyncMock):
                batches = []
                async for batch in provider.collect("news", limit=10):
                    batches.append(batch)

        assert len(batches) == 1
        assert batches[0][0].content == "普通新闻内容"
        assert batches[0][0].source == DataSource.TWITTER


# === 测试: 源不可用时的跳过逻辑 ===


class TestFeedUnavailableSkip:
    """测试 RSS 源不可用时的降级跳过逻辑

    需求 4.5: RSS 源不可用或解析失败时跳过该源，继续处理其他源
    """

    @pytest.mark.asyncio
    async def test_skip_unavailable_feed(self):
        """源返回 None 时应跳过并继续处理其他源"""
        provider = RSSProvider(session=AsyncMock())

        # 第一个源不可用（返回 None），第二个源正常
        side_effects = [None, SAMPLE_RSS_XML]

        with patch.object(
            provider, "_fetch_feed_xml",
            new_callable=AsyncMock,
            side_effect=side_effects,
        ):
            with patch("backend.app.collectors.zero_cost.rss_provider.random_delay", new_callable=AsyncMock):
                batches = []
                async for batch in provider.collect("test", limit=10):
                    batches.append(batch)

        # 第二个源的数据应被采集到
        total = sum(len(b) for b in batches)
        assert total > 0

    @pytest.mark.asyncio
    async def test_all_feeds_unavailable_returns_empty(self):
        """所有源都不可用时应返回空结果而非抛出异常"""
        provider = RSSProvider(session=AsyncMock())

        with patch.object(
            provider, "_fetch_feed_xml",
            new_callable=AsyncMock,
            return_value=None,
        ):
            with patch("backend.app.collectors.zero_cost.rss_provider.random_delay", new_callable=AsyncMock):
                batches = []
                async for batch in provider.collect("test", limit=10):
                    batches.append(batch)

        assert batches == []

    @pytest.mark.asyncio
    async def test_skip_feed_with_invalid_xml(self):
        """XML 解析失败的源应被跳过"""
        provider = RSSProvider(session=AsyncMock())

        # 第一个源返回无效 XML，第二个源正常
        side_effects = [SAMPLE_INVALID_XML, SAMPLE_RSS_XML]

        with patch.object(
            provider, "_fetch_feed_xml",
            new_callable=AsyncMock,
            side_effect=side_effects,
        ):
            with patch("backend.app.collectors.zero_cost.rss_provider.random_delay", new_callable=AsyncMock):
                batches = []
                async for batch in provider.collect("test", limit=10):
                    batches.append(batch)

        total = sum(len(b) for b in batches)
        assert total > 0
