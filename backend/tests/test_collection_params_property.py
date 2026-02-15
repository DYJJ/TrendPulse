"""
采集参数验证属性测试

使用 Hypothesis 库对扩展后的 validate_collection_params 进行属性测试，
验证 limit 范围（1-200000）、时间范围（start < end）和 subreddits 参数的校验逻辑。

属性 7: 采集参数验证
验证需求: 6.1, 6.4, 6.5
"""

from datetime import datetime, timedelta

from hypothesis import given, strategies as st, settings

from backend.app.utils.validators import (
    validate_collection_params,
    SUPPORTED_LANGUAGES,
    MIN_LIMIT,
    MAX_LIMIT,
)


# 有效关键词策略：非空且包含非空白字符
valid_keyword_st = st.text(min_size=1, max_size=100).filter(lambda s: s.strip())
# 有效语言策略
valid_language_st = st.sampled_from(sorted(SUPPORTED_LANGUAGES))
# 有效 limit 策略
valid_limit_st = st.integers(min_value=MIN_LIMIT, max_value=MAX_LIMIT)
# 有效 subreddit 名称策略
valid_subreddit_st = st.text(min_size=1, max_size=50, alphabet=st.characters(
    whitelist_categories=("L", "N", "P"),
)).filter(lambda s: s.strip())


class TestCollectionParamsProperty:
    """采集参数验证属性测试

    **验证: 需求 6.1, 6.4, 6.5**

    属性 7: 对于任意采集参数，当 limit 在 1-200000 范围内、时间范围有效（start < end）时
    应接受；否则应拒绝并返回错误信息。
    """

    @settings(max_examples=100)
    @given(
        keyword=valid_keyword_st,
        language=valid_language_st,
        limit=valid_limit_st,
    )
    def test_valid_limit_range_accepted(self, keyword: str, language: str, limit: int):
        """limit 在 1-200000 范围内的有效参数应通过验证

        **Validates: Requirements 6.1**
        """
        result = validate_collection_params(keyword, language, limit)
        assert result.is_valid is True
        assert result.error is None

    @settings(max_examples=100)
    @given(
        keyword=valid_keyword_st,
        language=valid_language_st,
        limit=st.one_of(
            st.integers(max_value=MIN_LIMIT - 1),
            st.integers(min_value=MAX_LIMIT + 1, max_value=MAX_LIMIT + 100000),
        ),
    )
    def test_invalid_limit_range_rejected(self, keyword: str, language: str, limit: int):
        """limit 超出 1-200000 范围应被拒绝并返回错误信息

        **Validates: Requirements 6.1, 6.5**
        """
        result = validate_collection_params(keyword, language, limit)
        assert result.is_valid is False
        assert result.error is not None
        assert len(result.error) > 0

    @settings(max_examples=100)
    @given(
        keyword=valid_keyword_st,
        language=valid_language_st,
        limit=valid_limit_st,
        delta=st.timedeltas(min_value=timedelta(hours=1), max_value=timedelta(days=365 * 5)),
    )
    def test_valid_date_range_accepted(self, keyword: str, language: str, limit: int, delta: timedelta):
        """起始日期早于结束日期时应通过验证

        **Validates: Requirements 6.4**
        """
        start_date = datetime(2020, 1, 1)
        end_date = start_date + delta
        result = validate_collection_params(
            keyword, language, limit,
            start_date=start_date, end_date=end_date,
        )
        assert result.is_valid is True

    @settings(max_examples=100)
    @given(
        keyword=valid_keyword_st,
        language=valid_language_st,
        limit=valid_limit_st,
        delta=st.timedeltas(min_value=timedelta(hours=1), max_value=timedelta(days=365 * 5)),
    )
    def test_invalid_date_range_rejected(self, keyword: str, language: str, limit: int, delta: timedelta):
        """起始日期晚于结束日期时应被拒绝并返回错误信息

        **Validates: Requirements 6.4, 6.5**
        """
        end_date = datetime(2020, 1, 1)
        start_date = end_date + delta
        result = validate_collection_params(
            keyword, language, limit,
            start_date=start_date, end_date=end_date,
        )
        assert result.is_valid is False
        assert result.error is not None

    @settings(max_examples=100)
    @given(
        keyword=valid_keyword_st,
        language=valid_language_st,
        limit=valid_limit_st,
    )
    def test_equal_dates_rejected(self, keyword: str, language: str, limit: int):
        """起始日期等于结束日期时应被拒绝

        **Validates: Requirements 6.4, 6.5**
        """
        d = datetime(2024, 6, 15, 12, 0, 0)
        result = validate_collection_params(
            keyword, language, limit,
            start_date=d, end_date=d,
        )
        assert result.is_valid is False
        assert result.error is not None

    @settings(max_examples=100)
    @given(
        keyword=valid_keyword_st,
        language=valid_language_st,
        limit=valid_limit_st,
        subreddits=st.lists(valid_subreddit_st, min_size=1, max_size=10),
    )
    def test_valid_subreddits_accepted(self, keyword: str, language: str, limit: int, subreddits):
        """有效的 subreddits 列表应通过验证

        **Validates: Requirements 6.5**
        """
        result = validate_collection_params(
            keyword, language, limit, subreddits=subreddits,
        )
        assert result.is_valid is True

    @settings(max_examples=100)
    @given(
        keyword=valid_keyword_st,
        language=valid_language_st,
        limit=valid_limit_st,
    )
    def test_empty_subreddits_rejected(self, keyword: str, language: str, limit: int):
        """空的 subreddits 列表应被拒绝

        **Validates: Requirements 6.5**
        """
        result = validate_collection_params(
            keyword, language, limit, subreddits=[],
        )
        assert result.is_valid is False
        assert result.error is not None

    @settings(max_examples=100)
    @given(
        keyword=st.text(max_size=100),
        language=st.text(max_size=10),
        limit=st.integers(min_value=-10000, max_value=300000),
        use_dates=st.booleans(),
        use_subreddits=st.booleans(),
    )
    def test_validation_never_raises(
        self, keyword: str, language: str, limit: int,
        use_dates: bool, use_subreddits: bool,
    ):
        """验证函数对任意输入组合都不应抛出异常

        **Validates: Requirements 6.5**
        """
        start_date = datetime(2024, 1, 1) if use_dates else None
        end_date = datetime(2024, 6, 1) if use_dates else None
        subreddits = ["test"] if use_subreddits else None

        result = validate_collection_params(
            keyword, language, limit,
            start_date=start_date, end_date=end_date,
            subreddits=subreddits,
        )
        assert isinstance(result.is_valid, bool)
        if not result.is_valid:
            assert result.error is not None
            assert len(result.error) > 0
