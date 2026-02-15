"""
YouTube 批量采集器属性测试

使用 Hypothesis 库对 YouTubeBatchCollector 进行基于属性的测试。
通过模拟 yt-dlp 响应验证采集逻辑的正确性，不实际访问外部服务。

属性 1: 采集数量上限约束
属性 2: 数据字段完整性

验证需求: 2.2, 2.4
"""

import asyncio
from datetime import datetime, timezone
from typing import List
from unittest.mock import MagicMock, patch

import pytest
from hypothesis import given, settings, strategies as st, HealthCheck

from backend.app.collectors.youtube_batch_collector import (
    BATCH_SIZE,
    YouTubeBatchCollector,
)
from backend.app.models.data_models import DataSource, RawPost


# --- 辅助函数 ---


def _make_search_entry(index: int) -> dict:
    """创建模拟的 yt-dlp 搜索结果条目"""
    return {
        "id": f"video_{index}",
        "title": f"测试视频标题 {index}",
        "uploader": f"频道_{index}",
        "channel": f"频道_{index}",
        "view_count": index * 100,
        "duration": 120 + index,
        "url": f"https://www.youtube.com/watch?v=video_{index}",
    }


def _make_video_detail(video_id: str, index: int = 0) -> dict:
    """创建模拟的 yt-dlp 视频详情"""
    return {
        "id": video_id,
        "title": f"详细标题 {video_id}",
        "description": f"这是视频 {video_id} 的详细描述内容",
        "uploader": f"频道_{index}",
        "channel": f"频道_{index}",
        "view_count": index * 1000,
        "like_count": index * 50,
        "comment_count": index * 10,
        "upload_date": "20240101",
        "subtitles": {},
        "automatic_captions": {},
        "comments": [
            {"text": f"评论 {i}", "author": f"用户_{i}"}
            for i in range(3)
        ],
    }


def _create_mock_ytdlp(entries: list, details: dict):
    """创建模拟的 yt-dlp 模块

    Args:
        entries: 搜索结果条目列表
        details: video_id -> 详情字典的映射
    """
    mock_module = MagicMock()

    class MockYDL:
        def __init__(self, opts):
            self._opts = opts

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def extract_info(self, url, download=False):
            if url.startswith("ytsearch"):
                return {"entries": entries}
            # 从 URL 中提取 video_id
            vid = url.split("v=")[-1] if "v=" in url else url
            return details.get(vid, _make_video_detail(vid))

    mock_module.YoutubeDL = MockYDL
    return mock_module


def _run_async(coro):
    """在新的事件循环中运行异步协程"""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _collect_all(collector, keyword, limit, **kwargs) -> List[RawPost]:
    """收集所有批次的数据到一个列表"""
    result: List[RawPost] = []
    async for batch in collector.collect(keyword=keyword, limit=limit, **kwargs):
        result.extend(batch)
    return result


# --- 属性 1: 采集数量上限约束 ---


class TestCollectionLimitConstraint:
    """采集数量上限约束属性测试

    **验证: 需求 2.4, 6.1**

    对于任意条数限制值，采集器返回的数据总条数不超过指定的限制值。
    """

    @settings(
        max_examples=100,
        suppress_health_check=[HealthCheck.too_slow],
        deadline=None,
    )
    @given(limit=st.integers(min_value=1, max_value=800))
    def test_total_posts_never_exceed_limit(self, limit: int):
        """采集到的帖子总数不应超过指定的限制值

        **Validates: Requirements 2.4**
        """
        # 创建比 limit 多的搜索结果，确保采集器需要截断
        available = limit + 200
        entries = [_make_search_entry(i) for i in range(available)]
        details = {
            f"video_{i}": _make_video_detail(f"video_{i}", i)
            for i in range(available)
        }
        mock_ytdlp = _create_mock_ytdlp(entries, details)

        collector = YouTubeBatchCollector()

        async def run():
            with patch(
                "backend.app.collectors.youtube_batch_collector.async_sleep",
                return_value=None,
            ), patch.dict(
                "sys.modules", {"yt_dlp": mock_ytdlp}
            ):
                return await _collect_all(collector, keyword="test", limit=limit)

        all_posts = _run_async(run())

        assert len(all_posts) <= limit, (
            f"采集数量 {len(all_posts)} 超过限制 {limit}"
        )


# --- 属性 2: 数据字段完整性 ---


class TestDataFieldCompleteness:
    """数据字段完整性属性测试

    **验证: 需求 2.2**

    对于任意 yt-dlp 返回的数据，每条记录必须包含
    非空的 content、source 和 external_id 字段。
    """

    @settings(
        max_examples=100,
        suppress_health_check=[HealthCheck.too_slow],
        deadline=None,
    )
    @given(num_items=st.integers(min_value=1, max_value=50))
    def test_all_posts_have_required_fields(self, num_items: int):
        """每条采集到的帖子应包含所有必需字段

        **Validates: Requirements 2.2**
        """
        entries = [_make_search_entry(i) for i in range(num_items)]
        details = {
            f"video_{i}": _make_video_detail(f"video_{i}", i)
            for i in range(num_items)
        }
        mock_ytdlp = _create_mock_ytdlp(entries, details)

        collector = YouTubeBatchCollector()

        async def run():
            with patch(
                "backend.app.collectors.youtube_batch_collector.async_sleep",
                return_value=None,
            ), patch.dict(
                "sys.modules", {"yt_dlp": mock_ytdlp}
            ):
                return await _collect_all(collector, keyword="test", limit=num_items)

        all_posts = _run_async(run())

        assert len(all_posts) == num_items, (
            f"期望 {num_items} 条，实际 {len(all_posts)} 条"
        )

        for post in all_posts:
            # 数据源必须是 YOUTUBE
            assert post.source == DataSource.YOUTUBE, "数据源应为 YOUTUBE"
            # external_id 不能为空
            assert post.external_id and len(post.external_id) > 0, (
                "external_id 不能为空"
            )
            # content 不能为空
            assert post.content and len(post.content) > 0, (
                "content 不能为空"
            )
            # author 不能为空
            assert post.author and len(post.author) > 0, (
                "author 不能为空"
            )
            # url 不能为 None
            assert post.url is not None, "url 不能为 None"
            # timestamp 必须是 datetime
            assert isinstance(post.timestamp, datetime), (
                "timestamp 必须是 datetime"
            )
            # likes 和 comments 必须是整数
            assert isinstance(post.likes, int), "likes 必须是整数"
            assert isinstance(post.comments, int), "comments 必须是整数"
