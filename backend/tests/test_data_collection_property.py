"""
数据采集属性测试

使用Hypothesis库对数据采集层进行基于属性的测试。
通过模拟采集器和模拟HTML页面验证采集逻辑的正确性，不实际访问外部网站。

属性 2: 数据源采集完整性
属性 3: 采集数量限制
属性 4: 网页采集错误处理

验证需求: 2.3, 2.4, 2.5, 3.2, 3.5, 4.2, 4.4, 4.5
"""

import asyncio
import uuid
from datetime import datetime, timezone
from typing import List, Optional

import pytest
from hypothesis import given, settings, strategies as st

from backend.app.collectors.base import BaseCollector, CollectionEngine, CollectionResult
from backend.app.models.data_models import DataSource, RawPost


# --- 辅助：模拟采集器 ---


class MockCollector(BaseCollector):
    """模拟采集器，返回预设数量的帖子，用于测试引擎逻辑"""

    def __init__(
        self,
        source: DataSource,
        posts_to_return: Optional[List[RawPost]] = None,
        error: Optional[Exception] = None,
    ) -> None:
        self.source = source
        self._posts = posts_to_return
        self._error = error

    async def collect(
        self, keyword: str, limit: int, language: str = "en"
    ) -> List[RawPost]:
        if self._error:
            raise self._error
        if self._posts is not None:
            return self._posts[:limit]
        # 默认生成指定数量的帖子
        return [
            _make_post(self.source, i) for i in range(limit)
        ]

    async def close(self) -> None:
        pass


def _make_post(source: DataSource, index: int = 0) -> RawPost:
    """创建一个包含所有必需字段的模拟帖子"""
    return RawPost(
        id=str(uuid.uuid4()),
        source=source,
        external_id=f"ext_{index}",
        title=f"测试标题 {index}",
        content=f"测试内容 {index}",
        author=f"作者_{index}",
        url=f"https://example.com/{index}",
        timestamp=datetime.now(timezone.utc),
        likes=index * 10,
        comments=index * 5,
        shares=index * 2,
    )


# --- 策略定义 ---

source_strategy = st.sampled_from(list(DataSource))
limit_strategy = st.integers(min_value=1, max_value=100)
keyword_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N")),
    min_size=1,
    max_size=50,
).filter(lambda t: t.strip())
language_strategy = st.sampled_from(["en", "zh"])


# --- 属性 2: 数据源采集完整性 ---
# Feature: trendpulse-sentiment-analysis, Property 2: 数据源采集完整性


class TestDataSourceCompleteness:
    """数据源采集完整性属性测试

    **验证: 需求 2.3, 3.2, 4.2**

    对于任意数据源和模拟的采集结果，采集器应该提取所有必需字段
    （标题/内容、作者、时间戳、互动数据），提取后的数据对象不应有缺失的必需字段。
    """

    @settings(max_examples=100)
    @given(
        source=source_strategy,
        num_posts=st.integers(min_value=1, max_value=20),
    )
    def test_collected_posts_have_all_required_fields(
        self, source: DataSource, num_posts: int
    ):
        """采集到的帖子应包含所有必需字段

        **Validates: Requirements 2.3, 3.2, 4.2**
        """
        posts = [_make_post(source, i) for i in range(num_posts)]
        collector = MockCollector(source=source, posts_to_return=posts)
        engine = CollectionEngine()
        engine.register_collector(source, collector)

        result: CollectionResult = asyncio.get_event_loop().run_until_complete(
            engine.collect(
                keyword="test",
                language="en",
                limit=num_posts,
                sources=[source],
            )
        )

        # 验证每个帖子的必需字段完整性
        for post in result.posts:
            assert post.id is not None and len(post.id) > 0, "帖子ID不能为空"
            assert post.source == source, "数据源应匹配"
            assert post.content is not None and len(post.content) > 0, "内容不能为空"
            assert post.author is not None and len(post.author) > 0, "作者不能为空"
            assert post.url is not None, "URL不能为None"
            assert isinstance(post.timestamp, datetime), "时间戳必须是datetime类型"
            assert isinstance(post.likes, int), "点赞数必须是整数"
            assert isinstance(post.comments, int), "评论数必须是整数"
            assert isinstance(post.shares, int), "分享数必须是整数"

    @settings(max_examples=100)
    @given(source=source_strategy)
    def test_engine_result_tracks_source_counts(self, source: DataSource):
        """引擎结果应正确记录各数据源的采集数量

        **Validates: Requirements 2.3, 3.2, 4.2**
        """
        posts = [_make_post(source, i) for i in range(5)]
        collector = MockCollector(source=source, posts_to_return=posts)
        engine = CollectionEngine()
        engine.register_collector(source, collector)

        result = asyncio.get_event_loop().run_until_complete(
            engine.collect(keyword="test", language="en", limit=5, sources=[source])
        )

        assert source.value in result.source_counts
        assert result.source_counts[source.value] == len(result.posts)


# --- 属性 3: 采集数量限制 ---
# Feature: trendpulse-sentiment-analysis, Property 3: 采集数量限制


class TestCollectionLimitEnforcement:
    """采集数量限制属性测试

    **验证: 需求 2.4, 4.4**

    对于任意数据源和条数限制值（1-1000），采集器返回的数据条数应该不超过指定的限制值。
    """

    @settings(max_examples=100)
    @given(
        source=source_strategy,
        limit=limit_strategy,
        available=st.integers(min_value=0, max_value=200),
    )
    def test_returned_posts_never_exceed_limit(
        self, source: DataSource, limit: int, available: int
    ):
        """返回的帖子数量不应超过指定的限制值

        **Validates: Requirements 2.4, 4.4**
        """
        # 创建比limit更多的可用帖子
        all_posts = [_make_post(source, i) for i in range(available)]
        collector = MockCollector(source=source, posts_to_return=all_posts)
        engine = CollectionEngine()
        engine.register_collector(source, collector)

        result = asyncio.get_event_loop().run_until_complete(
            engine.collect(keyword="test", language="en", limit=limit, sources=[source])
        )

        assert len(result.posts) <= limit, (
            f"帖子数量 {len(result.posts)} 超过限制 {limit}"
        )

    @settings(max_examples=100)
    @given(
        limit=limit_strategy,
        sources=st.lists(source_strategy, min_size=1, max_size=3, unique=True),
    )
    def test_multi_source_total_respects_per_source_limit(
        self, limit: int, sources: List[DataSource]
    ):
        """多数据源采集时，每个数据源的帖子数量不应超过限制

        **Validates: Requirements 2.4, 4.4**
        """
        engine = CollectionEngine()
        for src in sources:
            # 每个采集器提供超过limit的帖子
            posts = [_make_post(src, i) for i in range(limit + 50)]
            engine.register_collector(src, MockCollector(source=src, posts_to_return=posts))

        result = asyncio.get_event_loop().run_until_complete(
            engine.collect(keyword="test", language="en", limit=limit, sources=sources)
        )

        # 每个数据源的帖子数量不应超过limit
        for src in sources:
            src_posts = [p for p in result.posts if p.source == src]
            assert len(src_posts) <= limit, (
                f"{src.value} 帖子数量 {len(src_posts)} 超过限制 {limit}"
            )


# --- 属性 4: 网页采集错误处理 ---
# Feature: trendpulse-sentiment-analysis, Property 4: 网页采集错误处理


class TestScrapingErrorHandling:
    """网页采集错误处理属性测试

    **验证: 需求 2.5, 3.5, 4.5**

    对于任意数据源，当网页访问失败或反爬机制触发时，采集器应该捕获错误、
    记录错误信息，并返回错误状态或部分数据（如果有）。
    """

    @settings(max_examples=100)
    @given(
        source=source_strategy,
        error_msg=st.text(min_size=1, max_size=100).filter(lambda s: s.strip()),
    )
    def test_single_source_failure_returns_error_info(
        self, source: DataSource, error_msg: str
    ):
        """单个数据源失败时，引擎应记录错误信息而不崩溃

        **Validates: Requirements 2.5, 3.5, 4.5**
        """
        collector = MockCollector(
            source=source, error=RuntimeError(error_msg)
        )
        engine = CollectionEngine()
        engine.register_collector(source, collector)

        result = asyncio.get_event_loop().run_until_complete(
            engine.collect(keyword="test", language="en", limit=10, sources=[source])
        )

        # 不应抛出异常，而是在结果中记录错误
        assert source.value in result.errors
        assert len(result.errors[source.value]) > 0
        assert result.source_counts.get(source.value, 0) == 0

    @settings(max_examples=100)
    @given(
        failing_source=source_strategy,
        working_source=source_strategy,
        limit=st.integers(min_value=1, max_value=20),
    )
    def test_partial_failure_preserves_successful_data(
        self, failing_source: DataSource, working_source: DataSource, limit: int
    ):
        """部分数据源失败时，成功的数据源数据应被保留

        **Validates: Requirements 2.5, 3.5, 4.5**
        """
        # 如果两个源相同，跳过（无法同时注册成功和失败的采集器）
        if failing_source == working_source:
            return

        engine = CollectionEngine()
        # 注册一个会失败的采集器
        engine.register_collector(
            failing_source,
            MockCollector(source=failing_source, error=ConnectionError("网络错误")),
        )
        # 注册一个正常工作的采集器
        working_posts = [_make_post(working_source, i) for i in range(limit)]
        engine.register_collector(
            working_source,
            MockCollector(source=working_source, posts_to_return=working_posts),
        )

        result = asyncio.get_event_loop().run_until_complete(
            engine.collect(
                keyword="test",
                language="en",
                limit=limit,
                sources=[failing_source, working_source],
            )
        )

        # 失败的数据源应有错误记录
        assert failing_source.value in result.errors
        # 成功的数据源数据应被保留
        successful_posts = [p for p in result.posts if p.source == working_source]
        assert len(successful_posts) > 0
        assert len(successful_posts) <= limit

    @settings(max_examples=100)
    @given(
        sources=st.lists(source_strategy, min_size=1, max_size=3, unique=True),
    )
    def test_all_sources_failure_returns_empty_with_errors(
        self, sources: List[DataSource]
    ):
        """所有数据源都失败时，应返回空结果和错误信息

        **Validates: Requirements 2.5, 3.5, 4.5**
        """
        engine = CollectionEngine()
        for src in sources:
            engine.register_collector(
                src,
                MockCollector(source=src, error=TimeoutError("请求超时")),
            )

        result = asyncio.get_event_loop().run_until_complete(
            engine.collect(keyword="test", language="en", limit=10, sources=sources)
        )

        assert len(result.posts) == 0
        for src in sources:
            assert src.value in result.errors


# --- 辅助测试：解析方法的属性测试 ---


class TestRedditParseInteractionCount:
    """Reddit互动数解析属性测试

    验证 _parse_interaction_count 对各种格式的正确处理。
    """

    @settings(max_examples=100)
    @given(count=st.integers(min_value=0, max_value=999))
    def test_plain_numbers_parsed_correctly(self, count: int):
        """纯数字文本应被正确解析

        **Validates: Requirements 2.3**
        """
        from backend.app.collectors.reddit_collector import RedditCollector

        result = RedditCollector._parse_count(str(count))
        assert result == count

    def test_k_suffix_parsed(self):
        """带k后缀的数字应被正确解析"""
        from backend.app.collectors.reddit_collector import RedditCollector

        assert RedditCollector._parse_count("1.2k") == 1200
        assert RedditCollector._parse_count("5k") == 5000

    def test_empty_returns_zero(self):
        """空文本应返回0"""
        from backend.app.collectors.reddit_collector import RedditCollector

        assert RedditCollector._parse_count("") == 0
        assert RedditCollector._parse_count("   ") == 0


class TestTwitterParseCount:
    """Twitter twscrape 推文解析属性测试"""

    @settings(max_examples=100)
    @given(count=st.integers(min_value=0, max_value=100000))
    def test_plain_numbers_parsed_correctly(self, count: int):
        """twscrape 推文的互动数应被正确解析

        **Validates: Requirements 1.4**
        """
        from unittest.mock import MagicMock
        from backend.app.collectors.twitter_twscrape_provider import TwscrapeProvider

        # 模拟 twscrape Tweet 对象
        tweet = MagicMock()
        tweet.id = 123456
        tweet.rawContent = "测试推文内容"
        tweet.user = MagicMock()
        tweet.user.username = "testuser"
        tweet.date = datetime(2025, 1, 1, tzinfo=timezone.utc)
        tweet.likeCount = count
        tweet.replyCount = 0
        tweet.retweetCount = 0

        result = TwscrapeProvider._parse_tweet(tweet)
        assert result is not None
        assert result.likes == count

    def test_empty_returns_none(self):
        """空内容的推文应返回 None"""
        from unittest.mock import MagicMock
        from backend.app.collectors.twitter_twscrape_provider import TwscrapeProvider

        tweet = MagicMock()
        tweet.id = 123
        tweet.rawContent = ""
        tweet.user = MagicMock()
        tweet.user.username = "test"

        assert TwscrapeProvider._parse_tweet(tweet) is None


class TestYouTubeParseViewCount:
    """YouTube 批量采集器日期解析属性测试"""

    @settings(max_examples=100)
    @given(
        year=st.integers(min_value=2000, max_value=2030),
        month=st.integers(min_value=1, max_value=12),
        day=st.integers(min_value=1, max_value=28),
    )
    def test_views_suffix_parsed_correctly(self, year: int, month: int, day: int):
        """yt-dlp 格式的日期字符串应被正确解析

        **Validates: Requirements 3.2**
        """
        from backend.app.collectors.youtube_batch_collector import YouTubeBatchCollector

        date_str = f"{year:04d}{month:02d}{day:02d}"
        result = YouTubeBatchCollector._parse_upload_date(date_str)
        assert result.year == year
        assert result.month == month
        assert result.day == day

    def test_k_suffix_parsed(self):
        """已知日期字符串应被正确解析"""
        from backend.app.collectors.youtube_batch_collector import YouTubeBatchCollector

        result = YouTubeBatchCollector._parse_upload_date("20250115")
        assert result.year == 2025
        assert result.month == 1
        assert result.day == 15

    def test_empty_returns_zero(self):
        """空字符串应返回当前时间（兜底）"""
        from backend.app.collectors.youtube_batch_collector import YouTubeBatchCollector
        from datetime import datetime, timezone

        result = YouTubeBatchCollector._parse_upload_date("")
        assert result.tzinfo is not None
        assert (datetime.now(timezone.utc) - result).total_seconds() < 5
