"""
输入参数验证器测试

验证 validate_collection_params 函数对关键词、语言和条数限制的校验逻辑。
"""

from backend.app.utils.validators import validate_collection_params


class TestValidateCollectionParams:
    """采集参数验证测试"""

    def test_valid_params_en(self):
        """有效参数（英文）应通过验证"""
        result = validate_collection_params("AI", "en", 100)
        assert result.is_valid is True
        assert result.error is None

    def test_valid_params_zh(self):
        """有效参数（中文）应通过验证"""
        result = validate_collection_params("人工智能", "zh", 50)
        assert result.is_valid is True

    def test_empty_keyword(self):
        """空关键词应验证失败"""
        result = validate_collection_params("", "en", 10)
        assert result.is_valid is False
        assert "关键词" in result.error

    def test_whitespace_keyword(self):
        """仅空白字符的关键词应验证失败"""
        result = validate_collection_params("   ", "en", 10)
        assert result.is_valid is False

    def test_invalid_language(self):
        """不支持的语言代码应验证失败"""
        result = validate_collection_params("test", "fr", 10)
        assert result.is_valid is False
        assert "语言" in result.error

    def test_limit_below_min(self):
        """条数限制低于最小值应验证失败"""
        result = validate_collection_params("test", "en", 0)
        assert result.is_valid is False
        assert "条数限制" in result.error

    def test_limit_above_max(self):
        """条数限制超过最大值应验证失败"""
        result = validate_collection_params("test", "en", 200001)
        assert result.is_valid is False

    def test_limit_boundary_min(self):
        """条数限制等于最小值应通过"""
        result = validate_collection_params("test", "en", 1)
        assert result.is_valid is True

    def test_limit_boundary_max(self):
        """条数限制等于最大值应通过"""
        result = validate_collection_params("test", "en", 200000)
        assert result.is_valid is True

    def test_valid_date_range(self):
        """有效的时间范围应通过验证"""
        from datetime import datetime
        start = datetime(2024, 1, 1)
        end = datetime(2024, 6, 1)
        result = validate_collection_params("test", "en", 100, start_date=start, end_date=end)
        assert result.is_valid is True

    def test_invalid_date_range(self):
        """起始日期晚于结束日期应验证失败"""
        from datetime import datetime
        start = datetime(2024, 6, 1)
        end = datetime(2024, 1, 1)
        result = validate_collection_params("test", "en", 100, start_date=start, end_date=end)
        assert result.is_valid is False
        assert "起始日期" in result.error

    def test_equal_dates_fail(self):
        """起始日期等于结束日期应验证失败"""
        from datetime import datetime
        d = datetime(2024, 6, 1)
        result = validate_collection_params("test", "en", 100, start_date=d, end_date=d)
        assert result.is_valid is False

    def test_valid_subreddits(self):
        """有效的 subreddits 列表应通过验证"""
        result = validate_collection_params("test", "en", 100, subreddits=["python", "news"])
        assert result.is_valid is True

    def test_empty_subreddits_list(self):
        """空的 subreddits 列表应验证失败"""
        result = validate_collection_params("test", "en", 100, subreddits=[])
        assert result.is_valid is False

    def test_subreddit_empty_name(self):
        """subreddit 名称为空应验证失败"""
        result = validate_collection_params("test", "en", 100, subreddits=["python", ""])
        assert result.is_valid is False
