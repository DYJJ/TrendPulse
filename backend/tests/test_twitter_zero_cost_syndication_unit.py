"""
SyndicationProvider 单元测试

使用固定 JSON 样本测试解析、404 错误处理和批量获取的并发控制。

需求: 2.1, 2.4
"""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from backend.app.collectors.zero_cost.syndication_provider import (
    SyndicationProvider,
    SYNDICATION_BASE_URL,
)
from backend.app.models.data_models import DataSource


# === 固定 JSON 样本 ===

SAMPLE_SYNDICATION_RESPONSE = {
    "text": "这是一条测试推文内容 #test",
    "user": {
        "screen_name": "test_user",
        "name": "Test User",
    },
    "created_at": "2025-01-15T10:30:00+00:00",
    "favorite_count": 42,
    "retweet_count": 10,
    "reply_count": 5,
}

SAMPLE_TWEET_ID = "1234567890"


# === 辅助函数 ===


def _make_mock_response(status: int, json_data: dict = None):
    """创建模拟的 aiohttp 响应对象"""
    resp = AsyncMock()
    resp.status = status
    if json_data is not None:
        resp.json = AsyncMock(return_value=json_data)
    # 支持 async context manager
    resp.__aenter__ = AsyncMock(return_value=resp)
    resp.__aexit__ = AsyncMock(return_value=False)
    return resp


def _make_mock_session(responses):
    """创建模拟的 aiohttp.ClientSession

    Args:
        responses: 响应列表，按调用顺序返回
    """
    session = AsyncMock()
    session.closed = False
    session.get = MagicMock(side_effect=responses)
    session.close = AsyncMock()
    return session


# === 测试: 使用固定 JSON 样本测试解析 ===


class TestParseSyndicationResponse:
    """测试 parse_syndication_response 静态方法的解析逻辑"""

    def test_parse_valid_response(self):
        """有效的 Syndication 响应应正确解析为 RawPost"""
        result = SyndicationProvider.parse_syndication_response(
            SAMPLE_SYNDICATION_RESPONSE, SAMPLE_TWEET_ID
        )

        assert result is not None
        assert result.id == f"tw_{SAMPLE_TWEET_ID}"
        assert result.source == DataSource.TWITTER
        assert result.external_id == SAMPLE_TWEET_ID
        assert result.content == "这是一条测试推文内容 #test"
        assert result.author == "test_user"
        assert result.url == f"https://x.com/test_user/status/{SAMPLE_TWEET_ID}"
        assert isinstance(result.timestamp, datetime)
        assert result.likes == 42
        assert result.shares == 10
        assert result.comments == 5

    def test_parse_with_twitter_date_format(self):
        """Twitter 原始日期格式应正确解析"""
        data = {
            **SAMPLE_SYNDICATION_RESPONSE,
            "created_at": "Wed Jan 15 10:30:00 +0000 2025",
        }
        result = SyndicationProvider.parse_syndication_response(data, SAMPLE_TWEET_ID)

        assert result is not None
        assert isinstance(result.timestamp, datetime)

    def test_parse_with_invalid_date_uses_utc_now(self):
        """无效日期格式应回退到当前 UTC 时间"""
        data = {**SAMPLE_SYNDICATION_RESPONSE, "created_at": "invalid-date"}
        result = SyndicationProvider.parse_syndication_response(data, SAMPLE_TWEET_ID)

        assert result is not None
        assert isinstance(result.timestamp, datetime)

    def test_parse_missing_content_returns_none(self):
        """缺少 text 字段应返回 None"""
        data = {**SAMPLE_SYNDICATION_RESPONSE, "text": ""}
        assert SyndicationProvider.parse_syndication_response(data, SAMPLE_TWEET_ID) is None

    def test_parse_missing_author_returns_none(self):
        """缺少作者信息应返回 None"""
        data = {
            **SAMPLE_SYNDICATION_RESPONSE,
            "user": {"screen_name": "", "name": ""},
        }
        assert SyndicationProvider.parse_syndication_response(data, SAMPLE_TWEET_ID) is None

    def test_parse_uses_name_when_screen_name_missing(self):
        """screen_name 为空时应使用 name 字段"""
        data = {
            **SAMPLE_SYNDICATION_RESPONSE,
            "user": {"screen_name": "", "name": "FallbackName"},
        }
        # name 非空，应成功解析
        result = SyndicationProvider.parse_syndication_response(data, SAMPLE_TWEET_ID)
        assert result is not None
        assert result.author == "FallbackName"


# === 测试: 404 错误处理 ===


class TestFetchTweet404:
    """测试 fetch_tweet 对 404 响应的处理

    需求: 2.4 - 推文不存在时应跳过并返回 None
    """

    @pytest.mark.asyncio
    async def test_fetch_tweet_404_returns_none(self):
        """推文不存在（404）时应返回 None"""
        mock_resp = _make_mock_response(status=404)
        mock_session = _make_mock_session([mock_resp])

        provider = SyndicationProvider(session=mock_session)
        result = await provider.fetch_tweet("9999999999")

        assert result is None

    @pytest.mark.asyncio
    async def test_fetch_tweet_success(self):
        """正常响应应返回解析后的 RawPost"""
        mock_resp = _make_mock_response(status=200, json_data=SAMPLE_SYNDICATION_RESPONSE)
        mock_session = _make_mock_session([mock_resp])

        provider = SyndicationProvider(session=mock_session)
        result = await provider.fetch_tweet(SAMPLE_TWEET_ID)

        assert result is not None
        assert result.external_id == SAMPLE_TWEET_ID
        assert result.source == DataSource.TWITTER

    @pytest.mark.asyncio
    async def test_fetch_tweet_non_200_non_404_returns_none(self):
        """非 200/404 状态码应返回 None"""
        mock_resp = _make_mock_response(status=500)
        mock_session = _make_mock_session([mock_resp])

        provider = SyndicationProvider(session=mock_session)
        result = await provider.fetch_tweet(SAMPLE_TWEET_ID)

        assert result is None


# === 测试: 批量获取的并发控制 ===


class TestFetchTweetsBatch:
    """测试 fetch_tweets_batch 的批量获取和并发控制

    需求: 2.1, 2.4
    """

    @pytest.mark.asyncio
    async def test_batch_empty_list_returns_empty(self):
        """空 ID 列表应返回空列表"""
        provider = SyndicationProvider(session=AsyncMock())
        result = await provider.fetch_tweets_batch([])
        assert result == []

    @pytest.mark.asyncio
    async def test_batch_filters_failed_tweets(self):
        """批量获取应过滤掉失败的推文（404 等）"""
        # 第一条成功，第二条 404
        resp_ok = _make_mock_response(status=200, json_data=SAMPLE_SYNDICATION_RESPONSE)
        resp_404 = _make_mock_response(status=404)

        mock_session = _make_mock_session([resp_ok, resp_404])

        provider = SyndicationProvider(session=mock_session)

        # patch random_delay 避免实际等待
        with patch(
            "backend.app.collectors.zero_cost.syndication_provider.random_delay",
            new_callable=AsyncMock,
        ):
            result = await provider.fetch_tweets_batch(
                [SAMPLE_TWEET_ID, "9999999999"], max_concurrency=2
            )

        # 只有成功的那条
        assert len(result) == 1
        assert result[0].external_id == SAMPLE_TWEET_ID

    @pytest.mark.asyncio
    async def test_batch_concurrency_limited(self):
        """并发数应受 max_concurrency 参数限制"""
        concurrent_count = 0
        max_observed = 0

        original_fetch = SyndicationProvider.fetch_tweet

        async def tracked_fetch(self_inner, tweet_id):
            nonlocal concurrent_count, max_observed
            concurrent_count += 1
            max_observed = max(max_observed, concurrent_count)
            await asyncio.sleep(0.05)  # 模拟网络延迟
            concurrent_count -= 1
            return MagicMock(spec=True)  # 返回非 None 值

        provider = SyndicationProvider(session=AsyncMock())

        with patch.object(SyndicationProvider, "fetch_tweet", tracked_fetch):
            with patch(
                "backend.app.collectors.zero_cost.syndication_provider.random_delay",
                new_callable=AsyncMock,
            ):
                tweet_ids = [str(i) for i in range(20)]
                await provider.fetch_tweets_batch(tweet_ids, max_concurrency=3)

        # 最大并发数不应超过设定值
        assert max_observed <= 3
