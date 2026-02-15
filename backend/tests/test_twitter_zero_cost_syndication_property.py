"""
SyndicationProvider 解析函数的属性测试

使用 Hypothesis 验证 parse_syndication_response 的正确性属性：
- Property 4: RawPost 字段完整性不变量（Syndication 部分）
- Property 5: 无效数据过滤（Syndication 部分）
"""

from datetime import datetime, timezone

from hypothesis import given, strategies as st, settings

from backend.app.collectors.zero_cost.syndication_provider import SyndicationProvider
from backend.app.models.data_models import DataSource


# === 辅助策略 ===

# 推文 ID（纯数字字符串，1-20 位）
tweet_id_strategy = st.from_regex(r"[1-9][0-9]{0,19}", fullmatch=True)

# 用户名（字母数字下划线，1-15 位）
screen_name_strategy = st.from_regex(r"[A-Za-z_][A-Za-z0-9_]{0,14}", fullmatch=True)

# 非空文本内容
content_strategy = st.text(min_size=1, max_size=500).filter(lambda s: s.strip())

# 非负整数（互动数据）
count_strategy = st.integers(min_value=0, max_value=10_000_000)

# 有效的 created_at 时间字符串（ISO 格式）
timestamp_strategy = st.datetimes(
    min_value=datetime(2006, 1, 1),
    max_value=datetime(2026, 12, 31),
    timezones=st.just(timezone.utc),
).map(lambda dt: dt.isoformat())


def valid_syndication_data(
    content: str,
    screen_name: str,
    created_at: str,
    favorite_count: int,
    retweet_count: int,
    reply_count: int,
) -> dict:
    """构造有效的 Syndication API 响应字典"""
    return {
        "text": content,
        "user": {
            "screen_name": screen_name,
            "name": screen_name,
        },
        "created_at": created_at,
        "favorite_count": favorite_count,
        "retweet_count": retweet_count,
        "reply_count": reply_count,
    }


# === Property 4: RawPost 字段完整性不变量（Syndication 部分） ===
# Validates: Requirements 2.3, 2.6, 6.2, 6.3


@settings(max_examples=200)
@given(
    tweet_id=tweet_id_strategy,
    content=content_strategy,
    screen_name=screen_name_strategy,
    created_at=timestamp_strategy,
    favorite_count=count_strategy,
    retweet_count=count_strategy,
    reply_count=count_strategy,
)
def test_property4_syndication_rawpost_field_integrity(
    tweet_id: str,
    content: str,
    screen_name: str,
    created_at: str,
    favorite_count: int,
    retweet_count: int,
    reply_count: int,
):
    """Property 4: 对于有效的 Syndication 响应，解析后的 RawPost 应满足字段完整性不变量

    - source 字段应为 DataSource.TWITTER
    - id 字段应匹配 tw_{tweet_id} 格式
    - timestamp 应为有效的 datetime 实例
    - content、author、url、external_id 应为非空字符串

    **Validates: Requirements 2.3, 2.6, 6.2, 6.3**
    """
    data = valid_syndication_data(
        content, screen_name, created_at,
        favorite_count, retweet_count, reply_count,
    )

    result = SyndicationProvider.parse_syndication_response(data, tweet_id)

    assert result is not None, "有效数据应成功解析为 RawPost"

    # source 字段为 DataSource.TWITTER
    assert result.source == DataSource.TWITTER, (
        f"source 应为 TWITTER，实际: {result.source}"
    )

    # id 字段匹配 tw_{tweet_id} 格式
    assert result.id == f"tw_{tweet_id}", (
        f"id 应为 tw_{tweet_id}，实际: {result.id}"
    )

    # external_id 为非空字符串
    assert result.external_id == tweet_id, (
        f"external_id 应为 {tweet_id}，实际: {result.external_id}"
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

    # url 为非空字符串且包含推文 ID
    assert isinstance(result.url, str) and len(result.url) > 0, (
        "url 应为非空字符串"
    )
    assert tweet_id in result.url, (
        f"url 应包含推文 ID {tweet_id}，实际: {result.url}"
    )


# === Property 5: 无效数据过滤（Syndication 部分） ===
# Validates: Requirements 6.4


@settings(max_examples=200)
@given(
    tweet_id=tweet_id_strategy,
    screen_name=screen_name_strategy,
    created_at=timestamp_strategy,
)
def test_property5_syndication_missing_content_returns_none(
    tweet_id: str,
    screen_name: str,
    created_at: str,
):
    """Property 5: 缺少 content 字段时，解析函数应返回 None

    **Validates: Requirements 6.4**
    """
    # content 为空字符串
    data_empty = {
        "text": "",
        "user": {"screen_name": screen_name},
        "created_at": created_at,
    }
    assert SyndicationProvider.parse_syndication_response(data_empty, tweet_id) is None

    # content 字段缺失
    data_missing = {
        "user": {"screen_name": screen_name},
        "created_at": created_at,
    }
    assert SyndicationProvider.parse_syndication_response(data_missing, tweet_id) is None


@settings(max_examples=200)
@given(
    tweet_id=tweet_id_strategy,
    content=content_strategy,
    created_at=timestamp_strategy,
)
def test_property5_syndication_missing_author_returns_none(
    tweet_id: str,
    content: str,
    created_at: str,
):
    """Property 5: 缺少 author 字段时，解析函数应返回 None

    **Validates: Requirements 6.4**
    """
    # author 为空字符串
    data_empty_author = {
        "text": content,
        "user": {"screen_name": "", "name": ""},
        "created_at": created_at,
    }
    assert SyndicationProvider.parse_syndication_response(data_empty_author, tweet_id) is None

    # user 字段缺失
    data_no_user = {
        "text": content,
        "created_at": created_at,
    }
    assert SyndicationProvider.parse_syndication_response(data_no_user, tweet_id) is None
