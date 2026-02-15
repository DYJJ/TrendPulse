"""
SearchEngineProvider 单元测试

mock _fetch_with_curl_cffi 和 SyndicationProvider 方法，
测试降级切换逻辑、用户名提取、timeline-profile 集成和批次 yield 行为。

需求: 1.5, 1.6, 1.7
"""

from unittest.mock import AsyncMock, patch

import pytest

from backend.app.collectors.zero_cost.search_engine_provider import SearchEngineProvider
from backend.app.collectors.zero_cost.syndication_provider import SyndicationProvider
from backend.app.models.data_models import DataSource, RawPost
from datetime import datetime, timezone


# === 辅助函数 ===


def _make_html_with_tweet_urls(tweet_ids: list[str], user: str = "testuser") -> str:
    """生成包含推文链接的 HTML 片段"""
    links = "\n".join(
        f'<a href="https://x.com/{user}/status/{tid}">推文 {tid}</a>'
        for tid in tweet_ids
    )
    return f"<html><body>{links}</body></html>"


def _make_ddg_html_with_usernames(usernames: list[str]) -> str:
    """生成 DuckDuckGo 格式的 HTML，包含 uddg 重定向链接"""
    from urllib.parse import quote
    links = "\n".join(
        f'<a href="//duckduckgo.com/l/?uddg={quote(f"https://x.com/{u}")}&amp;rut=abc">结果</a>'
        for u in usernames
    )
    return f"<html><body>{links}</body></html>"


CAPTCHA_HTML = """
<html><body>
<div>We detected unusual traffic from your computer. Please verify you are human.</div>
<div class="captcha">reCAPTCHA</div>
</body></html>
"""

EMPTY_HTML = "<html><body><p>No results found</p></body></html>"


def _make_raw_post(tweet_id: str) -> RawPost:
    """创建测试用 RawPost"""
    return RawPost(
        id=f"tw_{tweet_id}",
        source=DataSource.TWITTER,
        external_id=tweet_id,
        title=None,
        content=f"推文内容 {tweet_id}",
        author="testuser",
        url=f"https://x.com/testuser/status/{tweet_id}",
        timestamp=datetime.now(timezone.utc),
        likes=10,
        comments=2,
        shares=5,
    )


# === 测试: 降级切换逻辑 ===


class TestSearchEngineFallback:
    """测试搜索引擎降级切换

    需求 1.5: 验证码/限流时自动切换到下一个搜索引擎
    需求 1.6: 所有引擎不可用时抛出异常并列出失败原因
    """

    @pytest.mark.asyncio
    async def test_fallback_from_ddg_captcha_to_google(self):
        """DuckDuckGo 返回验证码时应降级到 Google"""
        tweet_ids = ["111111111"]
        google_html = _make_html_with_tweet_urls(tweet_ids)

        mock_syndication = AsyncMock(spec=SyndicationProvider)
        mock_syndication.fetch_user_timeline = AsyncMock(return_value=[])
        mock_syndication.fetch_tweets_batch = AsyncMock(
            return_value=[_make_raw_post("111111111")]
        )
        mock_syndication.fetch_tweets_batch_with_mentions = AsyncMock(
            return_value=([_make_raw_post("111111111")], set())
        )
        mock_syndication.close = AsyncMock()

        provider = SearchEngineProvider(syndication=mock_syndication)

        # DuckDuckGo 返回验证码 HTML，Google 返回正常结果
        async def mock_fetch(url, params=None):
            if "duckduckgo" in url:
                return (200, CAPTCHA_HTML)
            if "google" in url:
                return (200, google_html)
            return (200, EMPTY_HTML)

        with patch.object(provider, "_fetch_with_curl_cffi", side_effect=mock_fetch):
            batches = []
            async for batch in provider.collect("test", limit=10):
                batches.append(batch)

        assert len(batches) == 1
        assert batches[0][0].external_id == "111111111"

    @pytest.mark.asyncio
    async def test_fallback_ddg_rate_limited_to_google(self):
        """DuckDuckGo 返回 429 限流时应降级到 Google"""
        tweet_ids = ["222222222"]
        google_html = _make_html_with_tweet_urls(tweet_ids)

        mock_syndication = AsyncMock(spec=SyndicationProvider)
        mock_syndication.fetch_user_timeline = AsyncMock(return_value=[])
        mock_syndication.fetch_tweets_batch = AsyncMock(
            return_value=[_make_raw_post("222222222")]
        )
        mock_syndication.fetch_tweets_batch_with_mentions = AsyncMock(
            return_value=([_make_raw_post("222222222")], set())
        )
        mock_syndication.close = AsyncMock()

        provider = SearchEngineProvider(syndication=mock_syndication)

        async def mock_fetch(url, params=None):
            if "duckduckgo" in url:
                return (429, "Rate limited")
            if "google" in url:
                return (200, google_html)
            return (200, EMPTY_HTML)

        with patch.object(provider, "_fetch_with_curl_cffi", side_effect=mock_fetch):
            batches = []
            async for batch in provider.collect("test", limit=10):
                batches.append(batch)

        assert len(batches) == 1
        assert batches[0][0].external_id == "222222222"

    @pytest.mark.asyncio
    async def test_all_engines_fail_raises_runtime_error(self):
        """所有搜索引擎均不可用且 timeline-profile 也无结果时应抛出 RuntimeError

        需求 1.6: 错误信息中应列出各引擎的失败原因
        """
        mock_syndication = AsyncMock(spec=SyndicationProvider)
        mock_syndication.close = AsyncMock()
        mock_syndication.fetch_user_timeline = AsyncMock(return_value=[])

        provider = SearchEngineProvider(syndication=mock_syndication)

        async def mock_fetch(url, params=None):
            return (200, CAPTCHA_HTML)

        with patch.object(provider, "_fetch_with_curl_cffi", side_effect=mock_fetch):
            with pytest.raises(RuntimeError, match="所有搜索引擎均不可用"):
                async for _ in provider.collect("test", limit=10):
                    pass


# === 测试: 批次 yield 行为 ===


class TestBatchYield:
    """测试批次 yield 行为

    需求 1.7: 每 500 条 yield 一批
    """

    @pytest.mark.asyncio
    async def test_single_batch_under_500(self):
        """不足 500 条时应一次性 yield 全部"""
        tweet_ids = [str(100000 + i) for i in range(5)]
        html = _make_html_with_tweet_urls(tweet_ids)
        posts = [_make_raw_post(tid) for tid in tweet_ids]

        mock_syndication = AsyncMock(spec=SyndicationProvider)
        mock_syndication.fetch_user_timeline = AsyncMock(return_value=[])
        mock_syndication.fetch_tweets_batch = AsyncMock(return_value=posts)
        mock_syndication.fetch_tweets_batch_with_mentions = AsyncMock(
            return_value=(posts, set())
        )
        mock_syndication.close = AsyncMock()

        provider = SearchEngineProvider(syndication=mock_syndication)

        async def mock_fetch(url, params=None):
            if "duckduckgo" in url:
                return (200, html)
            return (200, EMPTY_HTML)

        with patch.object(provider, "_fetch_with_curl_cffi", side_effect=mock_fetch):
            batches = []
            async for batch in provider.collect("test", limit=100):
                batches.append(batch)

        assert len(batches) == 1
        assert len(batches[0]) == 5

    @pytest.mark.asyncio
    async def test_multiple_batches_over_500(self):
        """超过 500 条时应分多个批次 yield"""
        count = 520
        tweet_ids = [str(200000 + i) for i in range(count)]
        html = _make_html_with_tweet_urls(tweet_ids)
        posts = [_make_raw_post(tid) for tid in tweet_ids]

        mock_syndication = AsyncMock(spec=SyndicationProvider)
        mock_syndication.fetch_user_timeline = AsyncMock(return_value=[])
        mock_syndication.fetch_tweets_batch = AsyncMock(return_value=posts)
        mock_syndication.fetch_tweets_batch_with_mentions = AsyncMock(
            return_value=(posts, set())
        )
        mock_syndication.close = AsyncMock()

        provider = SearchEngineProvider(syndication=mock_syndication)

        async def mock_fetch(url, params=None):
            if "duckduckgo" in url:
                return (200, html)
            return (200, EMPTY_HTML)

        with patch.object(provider, "_fetch_with_curl_cffi", side_effect=mock_fetch):
            batches = []
            async for batch in provider.collect("test", limit=1000):
                batches.append(batch)

        assert len(batches) == 2
        assert len(batches[0]) == 500
        assert len(batches[1]) == 20

    @pytest.mark.asyncio
    async def test_progress_callback_called(self):
        """on_progress 回调应在每个批次 yield 后被调用"""
        tweet_ids = [str(300000 + i) for i in range(3)]
        html = _make_html_with_tweet_urls(tweet_ids)
        posts = [_make_raw_post(tid) for tid in tweet_ids]

        mock_syndication = AsyncMock(spec=SyndicationProvider)
        mock_syndication.fetch_user_timeline = AsyncMock(return_value=[])
        mock_syndication.fetch_tweets_batch = AsyncMock(return_value=posts)
        mock_syndication.fetch_tweets_batch_with_mentions = AsyncMock(
            return_value=(posts, set())
        )
        mock_syndication.close = AsyncMock()

        progress_values = []
        provider = SearchEngineProvider(syndication=mock_syndication)

        async def mock_fetch(url, params=None):
            if "duckduckgo" in url:
                return (200, html)
            return (200, EMPTY_HTML)

        with patch.object(provider, "_fetch_with_curl_cffi", side_effect=mock_fetch):
            async for _ in provider.collect(
                "test", limit=100, on_progress=lambda n: progress_values.append(n)
            ):
                pass

        assert len(progress_values) >= 1
        assert progress_values[-1] == 3

    @pytest.mark.asyncio
    async def test_seen_ids_dedup(self):
        """seen_ids 中已有的推文 ID 应被过滤"""
        tweet_ids = ["444444444", "555555555"]
        html = _make_html_with_tweet_urls(tweet_ids)
        posts = [_make_raw_post("555555555")]

        mock_syndication = AsyncMock(spec=SyndicationProvider)
        mock_syndication.fetch_user_timeline = AsyncMock(return_value=[])
        mock_syndication.fetch_tweets_batch = AsyncMock(return_value=posts)
        mock_syndication.fetch_tweets_batch_with_mentions = AsyncMock(
            return_value=(posts, set())
        )
        mock_syndication.close = AsyncMock()

        provider = SearchEngineProvider(syndication=mock_syndication)

        async def mock_fetch(url, params=None):
            if "duckduckgo" in url:
                return (200, html)
            return (200, EMPTY_HTML)

        with patch.object(provider, "_fetch_with_curl_cffi", side_effect=mock_fetch):
            batches = []
            seen = {"444444444"}
            async for batch in provider.collect("test", limit=10, seen_ids=seen):
                batches.append(batch)

        call_args = mock_syndication.fetch_tweets_batch_with_mentions.call_args
        assert "555555555" in call_args[0][0]
        assert "444444444" not in call_args[0][0]
