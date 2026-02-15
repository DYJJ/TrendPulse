"""
BlueskyProvider 单元测试

使用固定 JSON 样本测试解析、分页逻辑和重试机制。
新策略：searchActors + getAuthorFeed。

需求: 3.2, 3.5
"""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from backend.app.collectors.zero_cost.bluesky_provider import (
    BlueskyProvider,
    BLUESKY_SEARCH_ACTORS_URL,
    BLUESKY_GET_AUTHOR_FEED_URL,
)
from backend.app.models.data_models import DataSource


# === 固定 JSON 样本 ===

SAMPLE_BLUESKY_POST = {
    "uri": "at://did:plc:abc123/app.bsky.feed.post/rkey001",
    "author": {
        "handle": "testuser.bsky.social",
        "displayName": "Test User",
    },
    "record": {
        "text": "这是一条 Bluesky 测试帖子 #test",
        "createdAt": "2025-01-15T10:30:00Z",
    },
    "likeCount": 42,
    "repostCount": 10,
    "replyCount": 5,
}

SAMPLE_BLUESKY_POST_2 = {
    "uri": "at://did:plc:def456/app.bsky.feed.post/rkey002",
    "author": {
        "handle": "anotheruser.bsky.social",
        "displayName": "Another User",
    },
    "record": {
        "text": "第二条 Bluesky 帖子",
        "createdAt": "2025-01-16T12:00:00Z",
    },
    "likeCount": 8,
    "repostCount": 3,
    "replyCount": 1,
}


# === 测试: 使用固定 JSON 样本测试解析 ===


class TestParseBlueskyPost:
    """测试 parse_bluesky_post 静态方法的解析逻辑"""

    def test_parse_valid_post(self):
        """有效的 Bluesky 帖子应正确解析为 RawPost"""
        result = BlueskyProvider.parse_bluesky_post(SAMPLE_BLUESKY_POST)

        assert result is not None
        assert result.id == "bsky_rkey001"
        assert result.source == DataSource.TWITTER
        assert result.external_id == "at://did:plc:abc123/app.bsky.feed.post/rkey001"
        assert result.content == "这是一条 Bluesky 测试帖子 #test"
        assert result.author == "testuser.bsky.social"
        assert result.url == "https://bsky.app/profile/testuser.bsky.social/post/rkey001"
        assert isinstance(result.timestamp, datetime)
        assert result.likes == 42
        assert result.shares == 10
        assert result.comments == 5

    def test_parse_missing_content_returns_none(self):
        """缺少 text 字段应返回 None"""
        post = {**SAMPLE_BLUESKY_POST, "record": {"text": "", "createdAt": "2025-01-15T10:30:00Z"}}
        assert BlueskyProvider.parse_bluesky_post(post) is None

    def test_parse_missing_author_returns_none(self):
        """缺少作者 handle 应返回 None"""
        post = {**SAMPLE_BLUESKY_POST, "author": {"handle": "", "displayName": ""}}
        assert BlueskyProvider.parse_bluesky_post(post) is None

    def test_parse_missing_uri_returns_none(self):
        """缺少 URI 应返回 None"""
        post = {**SAMPLE_BLUESKY_POST, "uri": ""}
        assert BlueskyProvider.parse_bluesky_post(post) is None

    def test_parse_invalid_date_uses_utc_now(self):
        """无效日期格式应回退到当前 UTC 时间"""
        post = {**SAMPLE_BLUESKY_POST, "record": {"text": "内容", "createdAt": "invalid"}}
        result = BlueskyProvider.parse_bluesky_post(post)
        assert result is not None
        assert isinstance(result.timestamp, datetime)

    def test_parse_zero_interaction_counts(self):
        """互动数据为 None 时应默认为 0"""
        post = {
            **SAMPLE_BLUESKY_POST,
            "likeCount": None,
            "repostCount": None,
            "replyCount": None,
        }
        result = BlueskyProvider.parse_bluesky_post(post)
        assert result is not None
        assert result.likes == 0
        assert result.shares == 0
        assert result.comments == 0


# === 测试: 采集逻辑（searchActors + getAuthorFeed） ===


class TestCollectPagination:
    """测试 collect 方法的采集逻辑

    新策略：先 searchActors 找用户，再 getAuthorFeed 获取帖子
    """

    @pytest.mark.asyncio
    async def test_single_page_no_cursor(self):
        """单页 feed 无 cursor 时应只获取一页"""
        provider = BlueskyProvider(session=AsyncMock())

        actors_resp = {"actors": [{"handle": "testuser.bsky.social"}]}
        feed_resp = {"feed": [{"post": SAMPLE_BLUESKY_POST}], "cursor": None}

        with patch.object(provider, "_search_actors", new_callable=AsyncMock, return_value=["testuser.bsky.social"]):
            with patch.object(provider, "_get_author_feed", new_callable=AsyncMock, return_value=feed_resp):
                with patch("backend.app.collectors.zero_cost.bluesky_provider.random_delay", new_callable=AsyncMock):
                    batches = []
                    async for batch in provider.collect("test", limit=10):
                        batches.append(batch)

        assert len(batches) == 1
        assert len(batches[0]) == 1
        assert batches[0][0].author == "testuser.bsky.social"

    @pytest.mark.asyncio
    async def test_multi_page_with_cursor(self):
        """有 cursor 时应自动翻页获取更多结果"""
        provider = BlueskyProvider(session=AsyncMock())

        feed_page1 = {"feed": [{"post": SAMPLE_BLUESKY_POST}], "cursor": "page2"}
        feed_page2 = {"feed": [{"post": SAMPLE_BLUESKY_POST_2}], "cursor": None}

        mock_feed = AsyncMock(side_effect=[feed_page1, feed_page2])

        with patch.object(provider, "_search_actors", new_callable=AsyncMock, return_value=["testuser.bsky.social"]):
            with patch.object(provider, "_get_author_feed", mock_feed):
                with patch("backend.app.collectors.zero_cost.bluesky_provider.random_delay", new_callable=AsyncMock):
                    batches = []
                    async for batch in provider.collect("test", limit=10):
                        batches.append(batch)

        assert len(batches) == 1
        assert len(batches[0]) == 2
        assert mock_feed.call_count == 2

    @pytest.mark.asyncio
    async def test_stops_at_limit(self):
        """达到 limit 上限时应停止采集"""
        provider = BlueskyProvider(session=AsyncMock())

        feed_resp = {
            "feed": [{"post": SAMPLE_BLUESKY_POST}, {"post": SAMPLE_BLUESKY_POST_2}],
            "cursor": "more",
        }

        with patch.object(provider, "_search_actors", new_callable=AsyncMock, return_value=["testuser.bsky.social"]):
            with patch.object(provider, "_get_author_feed", new_callable=AsyncMock, return_value=feed_resp):
                with patch("backend.app.collectors.zero_cost.bluesky_provider.random_delay", new_callable=AsyncMock):
                    batches = []
                    async for batch in provider.collect("test", limit=1):
                        batches.append(batch)

        total = sum(len(b) for b in batches)
        assert total == 1

    @pytest.mark.asyncio
    async def test_empty_posts_stops_pagination(self):
        """feed 为空时应停止"""
        provider = BlueskyProvider(session=AsyncMock())

        feed_resp = {"feed": [], "cursor": "should_not_use"}

        with patch.object(provider, "_search_actors", new_callable=AsyncMock, return_value=["testuser.bsky.social"]):
            with patch.object(provider, "_get_author_feed", new_callable=AsyncMock, return_value=feed_resp):
                with patch("backend.app.collectors.zero_cost.bluesky_provider.random_delay", new_callable=AsyncMock):
                    batches = []
                    async for batch in provider.collect("test", limit=10):
                        batches.append(batch)

        assert len(batches) == 0

    @pytest.mark.asyncio
    async def test_seen_ids_dedup(self):
        """seen_ids 中已有的帖子应被过滤"""
        provider = BlueskyProvider(session=AsyncMock())

        feed_resp = {
            "feed": [{"post": SAMPLE_BLUESKY_POST}, {"post": SAMPLE_BLUESKY_POST_2}],
            "cursor": None,
        }
        seen = {SAMPLE_BLUESKY_POST["uri"]}

        with patch.object(provider, "_search_actors", new_callable=AsyncMock, return_value=["testuser.bsky.social"]):
            with patch.object(provider, "_get_author_feed", new_callable=AsyncMock, return_value=feed_resp):
                with patch("backend.app.collectors.zero_cost.bluesky_provider.random_delay", new_callable=AsyncMock):
                    batches = []
                    async for batch in provider.collect("test", limit=10, seen_ids=seen):
                        batches.append(batch)

        assert len(batches) == 1
        assert len(batches[0]) == 1
        assert batches[0][0].author == "anotheruser.bsky.social"


# === 测试: 重试机制 ===


class TestRetryMechanism:
    """测试 _api_get 的指数退避重试机制

    需求 3.5: 指数退避重试（最多 3 次），重试失败后抛出异常
    """

    @pytest.mark.asyncio
    async def test_retry_on_429_then_success(self):
        """429 限流后重试成功应返回正常结果"""
        resp_429 = AsyncMock()
        resp_429.status = 429
        resp_429.__aenter__ = AsyncMock(return_value=resp_429)
        resp_429.__aexit__ = AsyncMock(return_value=False)

        resp_ok = AsyncMock()
        resp_ok.status = 200
        resp_ok.json = AsyncMock(return_value={"actors": [{"handle": "test.bsky.social"}]})
        resp_ok.__aenter__ = AsyncMock(return_value=resp_ok)
        resp_ok.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.closed = False
        mock_session.get = MagicMock(side_effect=[resp_429, resp_ok])

        provider = BlueskyProvider(session=mock_session)

        with patch("backend.app.collectors.zero_cost.bluesky_provider.asyncio.sleep", new_callable=AsyncMock):
            result = await provider._api_get(BLUESKY_SEARCH_ACTORS_URL, {"q": "test", "limit": 5})

        assert result["actors"][0]["handle"] == "test.bsky.social"

    @pytest.mark.asyncio
    async def test_retry_exhausted_raises_runtime_error(self):
        """重试耗尽后应抛出 RuntimeError"""
        resp_500 = AsyncMock()
        resp_500.status = 500
        resp_500.__aenter__ = AsyncMock(return_value=resp_500)
        resp_500.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.closed = False
        mock_session.get = MagicMock(side_effect=[resp_500, resp_500, resp_500])

        provider = BlueskyProvider(session=mock_session)

        with patch("backend.app.collectors.zero_cost.bluesky_provider.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(RuntimeError, match="重试"):
                await provider._api_get(BLUESKY_SEARCH_ACTORS_URL, {"q": "test", "limit": 5})

    @pytest.mark.asyncio
    async def test_retry_on_timeout(self):
        """超时后应重试，最终失败抛出 RuntimeError"""
        mock_session = AsyncMock()
        mock_session.closed = False
        mock_session.get = MagicMock(side_effect=asyncio.TimeoutError())

        provider = BlueskyProvider(session=mock_session)

        with patch("backend.app.collectors.zero_cost.bluesky_provider.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(RuntimeError, match="超时"):
                await provider._api_get(BLUESKY_SEARCH_ACTORS_URL, {"q": "test", "limit": 5})

    @pytest.mark.asyncio
    async def test_no_actors_returns_empty(self):
        """searchActors 无结果时 collect 应返回空"""
        provider = BlueskyProvider(session=AsyncMock())

        with patch.object(provider, "_search_actors", new_callable=AsyncMock, return_value=[]):
            with patch("backend.app.collectors.zero_cost.bluesky_provider.random_delay", new_callable=AsyncMock):
                batches = []
                async for batch in provider.collect("test", limit=10):
                    batches.append(batch)

        assert len(batches) == 0
