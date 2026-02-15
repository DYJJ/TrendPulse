"""
BlueskyProvider 解析函数的属性测试

使用 Hypothesis 验证 parse_bluesky_post 的正确性属性：
- Property 4: RawPost 字段完整性不变量（Bluesky 部分）
- Property 8: Bluesky URL 格式正确性
"""

import re
from datetime import datetime, timezone

from hypothesis import given, strategies as st, settings

from backend.app.collectors.zero_cost.bluesky_provider import BlueskyProvider
from backend.app.models.data_models import DataSource


# === 辅助策略 ===

# Bluesky 句柄（字母数字点横线，1-30 位，类似域名格式）
handle_strategy = st.from_regex(
    r"[a-z][a-z0-9\-]{0,14}\.[a-z]{2,6}", fullmatch=True
)

# rkey（字母数字，Bluesky 帖子标识符）
rkey_strategy = st.from_regex(r"[a-z0-9]{5,15}", fullmatch=True)

# DID（去中心化标识符）
did_strategy = st.from_regex(r"did:plc:[a-z0-9]{20,30}", fullmatch=True)

# 非空文本内容
content_strategy = st.text(min_size=1, max_size=500).filter(lambda s: s.strip())

# 非负整数（互动数据）
count_strategy = st.integers(min_value=0, max_value=10_000_000)

# 有效的 createdAt 时间字符串（ISO 格式）
timestamp_strategy = st.datetimes(
    min_value=datetime(2023, 1, 1),
    max_value=datetime(2026, 12, 31),
    timezones=st.just(timezone.utc),
).map(lambda dt: dt.isoformat())


def valid_bluesky_post(
    handle: str,
    did: str,
    rkey: str,
    content: str,
    created_at: str,
    like_count: int,
    repost_count: int,
    reply_count: int,
) -> dict:
    """构造有效的 Bluesky API 帖子响应字典"""
    uri = f"at://{did}/app.bsky.feed.post/{rkey}"
    return {
        "uri": uri,
        "cid": "bafyreig" + rkey,
        "author": {
            "did": did,
            "handle": handle,
            "displayName": handle.split(".")[0],
        },
        "record": {
            "text": content,
            "createdAt": created_at,
            "$type": "app.bsky.feed.post",
        },
        "likeCount": like_count,
        "repostCount": repost_count,
        "replyCount": reply_count,
    }


# === Property 4: RawPost 字段完整性不变量（Bluesky 部分） ===
# Validates: Requirements 3.3, 6.2, 6.3


@settings(max_examples=200)
@given(
    handle=handle_strategy,
    did=did_strategy,
    rkey=rkey_strategy,
    content=content_strategy,
    created_at=timestamp_strategy,
    like_count=count_strategy,
    repost_count=count_strategy,
    reply_count=count_strategy,
)
def test_property4_bluesky_rawpost_field_integrity(
    handle: str,
    did: str,
    rkey: str,
    content: str,
    created_at: str,
    like_count: int,
    repost_count: int,
    reply_count: int,
):
    """Property 4: 对于有效的 Bluesky 帖子数据，解析后的 RawPost 应满足字段完整性不变量

    - source 字段应为 DataSource.TWITTER
    - id 字段应匹配 bsky_{rkey} 格式
    - timestamp 应为有效的 datetime 实例
    - content、author、url、external_id 应为非空字符串

    **Validates: Requirements 3.3, 6.2, 6.3**
    """
    post = valid_bluesky_post(
        handle, did, rkey, content, created_at,
        like_count, repost_count, reply_count,
    )

    result = BlueskyProvider.parse_bluesky_post(post)

    assert result is not None, "有效数据应成功解析为 RawPost"

    # source 字段为 DataSource.TWITTER
    assert result.source == DataSource.TWITTER, (
        f"source 应为 TWITTER，实际: {result.source}"
    )

    # id 字段匹配 bsky_{rkey} 格式
    assert result.id == f"bsky_{rkey}", (
        f"id 应为 bsky_{rkey}，实际: {result.id}"
    )

    # external_id 为非空字符串（AT URI）
    expected_uri = f"at://{did}/app.bsky.feed.post/{rkey}"
    assert result.external_id == expected_uri, (
        f"external_id 应为 {expected_uri}，实际: {result.external_id}"
    )

    # timestamp 为有效的 datetime 实例
    assert isinstance(result.timestamp, datetime), (
        f"timestamp 应为 datetime 实例，实际: {type(result.timestamp)}"
    )

    # content 为非空字符串
    assert isinstance(result.content, str) and len(result.content) > 0, (
        "content 应为非空字符串"
    )

    # author 为非空字符串
    assert isinstance(result.author, str) and len(result.author) > 0, (
        "author 应为非空字符串"
    )

    # url 为非空字符串
    assert isinstance(result.url, str) and len(result.url) > 0, (
        "url 应为非空字符串"
    )


# === Property 8: Bluesky URL 格式正确性 ===
# Validates: Requirements 6.5

# Bluesky Web URL 格式正则
_BLUESKY_URL_PATTERN = re.compile(
    r"^https://bsky\.app/profile/[^/]+/post/[^/]+$"
)


@settings(max_examples=200)
@given(
    handle=handle_strategy,
    did=did_strategy,
    rkey=rkey_strategy,
    content=content_strategy,
    created_at=timestamp_strategy,
    like_count=count_strategy,
    repost_count=count_strategy,
    reply_count=count_strategy,
)
def test_property8_bluesky_url_format(
    handle: str,
    did: str,
    rkey: str,
    content: str,
    created_at: str,
    like_count: int,
    repost_count: int,
    reply_count: int,
):
    """Property 8: 解析后的 RawPost url 字段应匹配 Bluesky Web URL 格式

    URL 格式：https://bsky.app/profile/{handle}/post/{rkey}

    **Validates: Requirements 6.5**
    """
    post = valid_bluesky_post(
        handle, did, rkey, content, created_at,
        like_count, repost_count, reply_count,
    )

    result = BlueskyProvider.parse_bluesky_post(post)

    assert result is not None, "有效数据应成功解析为 RawPost"

    # URL 应匹配 Bluesky Web URL 格式
    assert _BLUESKY_URL_PATTERN.match(result.url), (
        f"url 应匹配 https://bsky.app/profile/{{handle}}/post/{{rkey}} 格式，"
        f"实际: {result.url}"
    )

    # URL 应包含正确的 handle 和 rkey
    expected_url = f"https://bsky.app/profile/{handle}/post/{rkey}"
    assert result.url == expected_url, (
        f"url 应为 {expected_url}，实际: {result.url}"
    )
