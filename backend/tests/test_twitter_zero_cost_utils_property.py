"""
零成本采集方案工具函数的属性测试

使用 Hypothesis 验证 extract_tweet_id 和 build_search_query 的正确性属性。
"""

from hypothesis import given, strategies as st, settings

from backend.app.collectors.zero_cost.utils import extract_tweet_id, build_search_query


# === 辅助策略 ===

# 生成合法的推文 ID（纯数字字符串，1-20 位）
tweet_id_strategy = st.from_regex(r"[1-9][0-9]{0,19}", fullmatch=True)

# 生成合法的用户名（字母数字下划线，1-15 位）
username_strategy = st.from_regex(r"[A-Za-z_][A-Za-z0-9_]{0,14}", fullmatch=True)

# 域名选择
domain_strategy = st.sampled_from(["x.com", "twitter.com"])

# 可选的 www 前缀
www_prefix_strategy = st.sampled_from(["", "www."])

# 协议选择
protocol_strategy = st.sampled_from(["https://", "http://"])

# 非空关键词策略（至少包含一个非空白字符）
keyword_strategy = st.text(min_size=1, max_size=100).filter(lambda s: s.strip())


# === Property 1: 推文 URL 解析正确性 ===
# Validates: Requirements 1.3


@settings(max_examples=200)
@given(
    protocol=protocol_strategy,
    www=www_prefix_strategy,
    domain=domain_strategy,
    username=username_strategy,
    tid=tweet_id_strategy,
)
def test_property1_valid_tweet_url_extracts_correct_id(
    protocol: str, www: str, domain: str, username: str, tid: str
):
    """Property 1: 对于任何符合格式的推文 URL，extract_tweet_id 应返回正确的推文 ID

    Validates: Requirements 1.3
    """
    url = f"{protocol}{www}{domain}/{username}/status/{tid}"
    result = extract_tweet_id(url)
    assert result == tid, f"期望 {tid}，实际得到 {result}，URL: {url}"


@settings(max_examples=200)
@given(
    data=st.one_of(
        # 无 /status/ 路径的 URL
        st.tuples(domain_strategy, username_strategy).map(
            lambda t: f"https://{t[0]}/{t[1]}"
        ),
        # 完全不相关的 URL
        st.just("https://example.com/some/path"),
        st.just("https://github.com/user/repo"),
        # 空字符串
        st.just(""),
        # 非 URL 文本
        st.text(max_size=50).filter(lambda s: "status/" not in s and "x.com" not in s and "twitter.com" not in s),
    )
)
def test_property1_invalid_url_returns_none(data: str):
    """Property 1: 对于不符合推文 URL 格式的字符串，extract_tweet_id 应返回 None

    Validates: Requirements 1.3
    """
    result = extract_tweet_id(data)
    assert result is None, f"期望 None，实际得到 {result}，输入: {data}"


# === Property 2: 搜索查询构造正确性 ===
# Validates: Requirements 1.1


@settings(max_examples=200)
@given(keyword=keyword_strategy)
def test_property2_search_query_contains_site_prefix_and_keyword(keyword: str):
    """Property 2: 对于任何非空关键词，构造的查询应包含 site:x.com 前缀和原始关键词

    Validates: Requirements 1.1
    """
    query = build_search_query(keyword)
    assert query.startswith("site:x.com "), f"查询应以 'site:x.com ' 开头，实际: {query}"
    assert keyword in query, f"查询应包含关键词 '{keyword}'，实际: {query}"
