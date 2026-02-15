"""
输入参数验证属性测试

使用Hypothesis库对 validate_collection_params 进行基于属性的测试，
验证对于任意输入参数组合，验证函数都能正确区分有效和无效输入。

属性 1: 输入参数验证
验证需求: 1.1, 1.5
"""

from hypothesis import given, strategies as st, settings

from backend.app.utils.validators import (
    validate_collection_params,
    SUPPORTED_LANGUAGES,
    MIN_LIMIT,
    MAX_LIMIT,
)


# Feature: trendpulse-sentiment-analysis, Property 1: 输入参数验证
class TestInputValidationProperty:
    """输入参数验证属性测试

    **验证: 需求 1.1, 1.5**

    对于任意输入参数（关键词、语言、条数限制），验证函数应该正确识别
    有效和无效输入，对于有效输入返回成功，对于无效输入返回描述性错误信息。
    """

    @settings(max_examples=100)
    @given(
        keyword=st.text(min_size=1, max_size=200).filter(lambda s: s.strip()),
        language=st.sampled_from(sorted(SUPPORTED_LANGUAGES)),
        limit=st.integers(min_value=MIN_LIMIT, max_value=MAX_LIMIT),
    )
    def test_valid_params_always_pass(self, keyword: str, language: str, limit: int):
        """有效参数组合应始终通过验证

        **Validates: Requirements 1.1**
        """
        result = validate_collection_params(keyword, language, limit)
        assert result.is_valid is True
        assert result.error is None

    @settings(max_examples=100)
    @given(
        language=st.sampled_from(sorted(SUPPORTED_LANGUAGES)),
        limit=st.integers(min_value=MIN_LIMIT, max_value=MAX_LIMIT),
    )
    def test_empty_keyword_always_fails(self, language: str, limit: int):
        """空关键词应始终验证失败并返回描述性错误

        **Validates: Requirements 1.1, 1.5**
        """
        result = validate_collection_params("", language, limit)
        assert result.is_valid is False
        assert result.error is not None
        assert len(result.error) > 0

    @settings(max_examples=100)
    @given(
        keyword=st.text(min_size=1, max_size=200).filter(lambda s: s.strip()),
        language=st.text(min_size=1, max_size=10).filter(
            lambda s: s not in SUPPORTED_LANGUAGES
        ),
        limit=st.integers(min_value=MIN_LIMIT, max_value=MAX_LIMIT),
    )
    def test_invalid_language_always_fails(self, keyword: str, language: str, limit: int):
        """不支持的语言代码应始终验证失败并返回描述性错误

        **Validates: Requirements 1.1, 1.5**
        """
        result = validate_collection_params(keyword, language, limit)
        assert result.is_valid is False
        assert result.error is not None
        assert len(result.error) > 0

    @settings(max_examples=100)
    @given(
        keyword=st.text(min_size=1, max_size=200).filter(lambda s: s.strip()),
        language=st.sampled_from(sorted(SUPPORTED_LANGUAGES)),
        limit=st.one_of(
            st.integers(max_value=MIN_LIMIT - 1),
            st.integers(min_value=MAX_LIMIT + 1),
        ),
    )
    def test_out_of_range_limit_always_fails(self, keyword: str, language: str, limit: int):
        """超出范围的条数限制应始终验证失败并返回描述性错误

        **Validates: Requirements 1.1, 1.5**
        """
        result = validate_collection_params(keyword, language, limit)
        assert result.is_valid is False
        assert result.error is not None
        assert len(result.error) > 0

    @settings(max_examples=100)
    @given(
        keyword=st.text(max_size=200),
        language=st.text(max_size=10),
        limit=st.integers(min_value=-10000, max_value=10000),
    )
    def test_validation_never_raises(self, keyword: str, language: str, limit: int):
        """验证函数对任意输入都不应抛出异常

        **Validates: Requirements 1.5**
        """
        result = validate_collection_params(keyword, language, limit)
        assert isinstance(result.is_valid, bool)
        if not result.is_valid:
            assert result.error is not None
            assert len(result.error) > 0
