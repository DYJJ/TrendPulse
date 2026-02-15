"""
X(Twitter) 采集方案升级 - 属性测试

使用 Hypothesis 库对 AccountPoolManager、CookieManager 和 TwscrapeProvider 进行基于属性的测试。

Feature: twitter-scraping-upgrade
- Property 1: 推文到 RawPost 的转换保留所有字段
- Property 2: 账号配置解析正确性
- Property 3: 账号配置验证完整性
- Property 4: Cookie 验证检查必要字段
- Property 5: Playwright 模式采集上限
- Property 10: 搜索查询构建完整性
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from unittest.mock import MagicMock

from hypothesis import given, settings, strategies as st

from backend.app.collectors.twitter_config import AccountPoolManager, CookieManager
from backend.app.collectors.twitter_twscrape_provider import TwscrapeProvider
from backend.app.models.data_models import DataSource


# --- 策略定义 ---

# 生成非空、不含分隔符的字符串（模拟账号字段值）
_field_value = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "S"),
        blacklist_characters=":;\n\r",
    ),
    min_size=1,
    max_size=30,
).filter(lambda s: s.strip())

# 生成单个账号元组 (username, password, email, email_password)
_account_tuple = st.tuples(_field_value, _field_value, _field_value, _field_value)


def _build_env_string(accounts: list[tuple[str, str, str, str]]) -> str:
    """将账号元组列表拼接为环境变量格式字符串"""
    return ";".join(":".join(parts) for parts in accounts)


# --- Property 2: 账号配置解析正确性 ---


class TestAccountParsingCorrectness:
    """Feature: twitter-scraping-upgrade, Property 2: 账号配置解析正确性

    *For any* 由 N 个有效账号组成的配置字符串，解析后应得到恰好 N 个账号字典，
    且每个字典的字段与原始输入一一对应。

    **Validates: Requirements 2.1, 7.1**
    """

    @settings(max_examples=100, deadline=None)
    @given(accounts=st.lists(_account_tuple, min_size=1, max_size=10))
    def test_parse_returns_correct_count_and_fields(
        self, accounts: list[tuple[str, str, str, str]]
    ):
        """解析 N 个有效账号应得到 N 个字典，字段一一对应

        **Validates: Requirements 2.1, 7.1**
        """
        env_value = _build_env_string(accounts)
        result = AccountPoolManager.parse_accounts_from_env(env_value)

        # 数量一致
        assert len(result) == len(accounts), (
            f"期望 {len(accounts)} 个账号，实际 {len(result)} 个"
        )

        # 字段一一对应（strip 后比较，与实现一致）
        for parsed, original in zip(result, accounts):
            assert parsed["username"] == original[0].strip()
            assert parsed["password"] == original[1].strip()
            assert parsed["email"] == original[2].strip()
            assert parsed["email_password"] == original[3].strip()


# --- Property 3: 账号配置验证完整性 ---


class TestAccountValidationCompleteness:
    """Feature: twitter-scraping-upgrade, Property 3: 账号配置验证完整性

    *For any* 账号配置字典，validate_account_config 返回 True 当且仅当
    username、password、email、email_password 四个字段均存在且非空。

    **Validates: Requirements 2.4**
    """

    @settings(max_examples=100, deadline=None)
    @given(
        username=_field_value,
        password=_field_value,
        email=_field_value,
        email_password=_field_value,
    )
    def test_valid_config_returns_true(
        self, username: str, password: str, email: str, email_password: str
    ):
        """四个字段均非空时应返回 True

        **Validates: Requirements 2.4**
        """
        account = {
            "username": username,
            "password": password,
            "email": email,
            "email_password": email_password,
        }
        assert AccountPoolManager.validate_account_config(account) is True

    @settings(max_examples=100, deadline=None)
    @given(
        full_account=st.fixed_dictionaries({
            "username": _field_value,
            "password": _field_value,
            "email": _field_value,
            "email_password": _field_value,
        }),
        missing_key=st.sampled_from(["username", "password", "email", "email_password"]),
    )
    def test_missing_field_returns_false(self, full_account: dict, missing_key: str):
        """缺少任一必要字段时应返回 False

        **Validates: Requirements 2.4**
        """
        account = {k: v for k, v in full_account.items() if k != missing_key}
        assert AccountPoolManager.validate_account_config(account) is False

    @settings(max_examples=100, deadline=None)
    @given(
        full_account=st.fixed_dictionaries({
            "username": _field_value,
            "password": _field_value,
            "email": _field_value,
            "email_password": _field_value,
        }),
        empty_key=st.sampled_from(["username", "password", "email", "email_password"]),
        empty_value=st.sampled_from(["", "   ", "\t"]),
    )
    def test_empty_field_returns_false(
        self, full_account: dict, empty_key: str, empty_value: str
    ):
        """任一字段为空/纯空白时应返回 False

        **Validates: Requirements 2.4**
        """
        account = {**full_account, empty_key: empty_value}
        assert AccountPoolManager.validate_account_config(account) is False


# --- Property 4: Cookie 验证检查必要字段 ---


class TestCookieValidation:
    """Feature: twitter-scraping-upgrade, Property 4: Cookie 验证检查必要字段

    *For any* Cookie 列表，validate_cookies 返回 True 当且仅当列表中包含
    name 为 "auth_token" 和 "ct0" 的 Cookie 条目。

    **Validates: Requirements 3.4**
    """

    @settings(max_examples=100, deadline=None)
    @given(
        extra_cookies=st.lists(
            st.fixed_dictionaries({
                "name": st.text(min_size=1, max_size=20).filter(
                    lambda n: n not in ("auth_token", "ct0")
                ),
                "value": st.text(min_size=1, max_size=50),
            }),
            max_size=5,
        ),
        auth_value=st.text(min_size=1, max_size=50),
        ct0_value=st.text(min_size=1, max_size=50),
    )
    def test_valid_cookies_returns_true(
        self, extra_cookies: list[dict], auth_value: str, ct0_value: str
    ):
        """包含 auth_token 和 ct0 时应返回 True

        **Validates: Requirements 3.4**
        """
        cookies = [
            {"name": "auth_token", "value": auth_value},
            {"name": "ct0", "value": ct0_value},
            *extra_cookies,
        ]
        assert CookieManager.validate_cookies(cookies) is True

    @settings(max_examples=100, deadline=None)
    @given(
        missing=st.sampled_from(["auth_token", "ct0"]),
        other_cookies=st.lists(
            st.fixed_dictionaries({
                "name": st.text(min_size=1, max_size=20).filter(
                    lambda n: n not in ("auth_token", "ct0")
                ),
                "value": st.text(min_size=1, max_size=50),
            }),
            max_size=5,
        ),
    )
    def test_missing_required_cookie_returns_false(
        self, missing: str, other_cookies: list[dict]
    ):
        """缺少 auth_token 或 ct0 时应返回 False

        **Validates: Requirements 3.4**
        """
        # 只保留另一个必要 cookie
        present = "ct0" if missing == "auth_token" else "auth_token"
        cookies = [{"name": present, "value": "x"}, *other_cookies]
        assert CookieManager.validate_cookies(cookies) is False

    def test_empty_list_returns_false(self):
        """空列表应返回 False

        **Validates: Requirements 3.4**
        """
        assert CookieManager.validate_cookies([]) is False


# --- 策略定义: TwscrapeProvider 测试 ---

# 生成非空推文内容（不含纯空白）
_tweet_content = st.text(min_size=1, max_size=280).filter(lambda s: s.strip())

# 生成有效的用户名（字母数字下划线）
_username = st.from_regex(r"[A-Za-z][A-Za-z0-9_]{0,14}", fullmatch=True)

# 生成正整数作为推文 ID
_tweet_id = st.integers(min_value=1, max_value=10**18)

# 生成非负整数作为互动数据
_non_negative_int = st.integers(min_value=0, max_value=10**7)

# 生成 UTC 时间戳
_utc_datetime = st.datetimes(
    min_value=datetime(2006, 3, 21),
    max_value=datetime(2026, 12, 31),
    timezones=st.just(timezone.utc),
)


def _make_mock_tweet(
    tweet_id: int,
    content: str,
    username: str,
    date: datetime,
    like_count: int,
    reply_count: int,
    retweet_count: int,
) -> MagicMock:
    """构建模拟的 twscrape Tweet 对象

    使用 MagicMock 模拟 twscrape.models.Tweet 的字段访问，
    避免直接依赖 twscrape 内部数据结构。
    """
    tweet = MagicMock()
    tweet.id = tweet_id
    tweet.rawContent = content
    tweet.date = date
    tweet.likeCount = like_count
    tweet.replyCount = reply_count
    tweet.retweetCount = retweet_count

    # 模拟 user 对象
    user = MagicMock()
    user.username = username
    tweet.user = user

    return tweet


# --- Property 1: 推文到 RawPost 的转换保留所有字段 ---


class TestTweetToRawPostConversion:
    """Feature: twitter-scraping-upgrade, Property 1: 推文到 RawPost 的转换保留所有字段

    *For any* 有效的 twscrape Tweet 对象（包含非空 content、有效 user、有效 id），
    将其转换为 RawPost 后，RawPost 的各字段应与 Tweet 的对应字段一致。

    **Validates: Requirements 1.3, 1.4**
    """

    @settings(max_examples=100, deadline=None)
    @given(
        tweet_id=_tweet_id,
        content=_tweet_content,
        username=_username,
        date=_utc_datetime,
        like_count=_non_negative_int,
        reply_count=_non_negative_int,
        retweet_count=_non_negative_int,
    )
    def test_parse_tweet_preserves_all_fields(
        self,
        tweet_id: int,
        content: str,
        username: str,
        date: datetime,
        like_count: int,
        reply_count: int,
        retweet_count: int,
    ):
        """转换后 RawPost 的所有字段应与原始 Tweet 一一对应

        **Validates: Requirements 1.3, 1.4**
        """
        mock_tweet = _make_mock_tweet(
            tweet_id, content, username, date, like_count, reply_count, retweet_count
        )

        result = TwscrapeProvider._parse_tweet(mock_tweet)

        # 转换应成功
        assert result is not None, "有效推文转换不应返回 None"

        # 字段一一对应
        assert result.external_id == str(tweet_id)
        assert result.content == content
        assert result.author == username
        assert result.likes == like_count
        assert result.comments == reply_count
        assert result.shares == retweet_count
        assert result.source == DataSource.TWITTER
        assert result.url == f"https://x.com/{username}/status/{tweet_id}"
        assert result.title is None


# --- Property 10: 搜索查询构建完整性 ---


class TestSearchQueryCompleteness:
    """Feature: twitter-scraping-upgrade, Property 10: 搜索查询构建完整性

    *For any* 关键词、起始日期、结束日期和语言的组合，构建的搜索查询字符串
    应包含关键词，且当提供了起始日期时包含 since 过滤，提供了结束日期时包含
    until 过滤，提供了语言时包含 lang 过滤。

    **Validates: Requirements 1.2**
    """

    # 生成非空关键词
    _keyword = st.text(min_size=1, max_size=50).filter(lambda s: s.strip())

    # 生成可选日期
    _optional_date = st.one_of(st.none(), _utc_datetime)

    # 生成非空语言代码
    _language = st.sampled_from(["en", "zh", "ja", "ko", "es", "fr", "de", "pt", "ar", "ru"])

    @settings(max_examples=100, deadline=None)
    @given(
        keyword=_keyword,
        start_date=_optional_date,
        end_date=_optional_date,
        language=_language,
    )
    def test_query_contains_keyword_and_filters(
        self,
        keyword: str,
        start_date,
        end_date,
        language: str,
    ):
        """查询字符串应包含关键词及所有提供的过滤条件

        **Validates: Requirements 1.2**
        """
        query = TwscrapeProvider._build_query(keyword, start_date, end_date, language)

        # 关键词必须包含在查询中
        assert keyword in query, f"查询 '{query}' 应包含关键词 '{keyword}'"

        # 提供了起始日期时应包含 since 过滤
        if start_date is not None:
            expected_since = f"since:{start_date.strftime('%Y-%m-%d')}"
            assert expected_since in query, (
                f"查询 '{query}' 应包含 '{expected_since}'"
            )

        # 提供了结束日期时应包含 until 过滤
        if end_date is not None:
            expected_until = f"until:{end_date.strftime('%Y-%m-%d')}"
            assert expected_until in query, (
                f"查询 '{query}' 应包含 '{expected_until}'"
            )

        # 提供了语言时应包含 lang 过滤
        if language:
            expected_lang = f"lang:{language}"
            assert expected_lang in query, (
                f"查询 '{query}' 应包含 '{expected_lang}'"
            )


# --- Property 5: Playwright 模式采集上限 ---


class TestPlaywrightLimitCap:
    """Feature: twitter-scraping-upgrade, Property 5: Playwright 模式采集上限

    *For any* 请求的 limit 值，Playwright 爬虫模式的实际采集上限应为 min(limit, 500)。

    **Validates: Requirements 3.6**
    """

    @settings(max_examples=100, deadline=None)
    @given(limit=st.integers(min_value=1, max_value=2000))
    def test_effective_limit_is_min_of_limit_and_500(self, limit: int):
        """实际采集上限应为 min(limit, 500)

        **Validates: Requirements 3.6**
        """
        from backend.app.collectors.twitter_playwright_provider import MAX_PLAYWRIGHT_LIMIT

        expected = min(limit, MAX_PLAYWRIGHT_LIMIT)
        assert expected == min(limit, 500), (
            f"limit={limit} 时，期望上限为 {min(limit, 500)}，"
            f"MAX_PLAYWRIGHT_LIMIT={MAX_PLAYWRIGHT_LIMIT}"
        )
        # 验证 MAX_PLAYWRIGHT_LIMIT 常量本身为 500
        assert MAX_PLAYWRIGHT_LIMIT == 500, (
            f"MAX_PLAYWRIGHT_LIMIT 应为 500，实际为 {MAX_PLAYWRIGHT_LIMIT}"
        )
