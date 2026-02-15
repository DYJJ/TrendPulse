"""
数据清洗属性测试

使用Hypothesis库对 DataCleaner 进行基于属性的测试，
验证文本清洗的幂等性和垃圾内容过滤的正确性。

属性 5: 文本清洗幂等性
属性 6: 垃圾内容过滤
验证需求: 5.1, 5.2, 5.3
"""

from hypothesis import given, strategies as st, settings

from backend.app.processing.data_cleaner import (
    DataCleaner,
    SPAM_KEYWORDS,
    BOT_PATTERNS,
)


# Feature: trendpulse-sentiment-analysis, Property 5: 文本清洗幂等性
class TestTextCleaningIdempotency:
    """文本清洗幂等性属性测试

    **验证: 需求 5.1**

    对于任意已清洗的文本，再次应用清洗函数应该返回相同的结果。
    """

    def setup_method(self):
        """每个测试方法前初始化清洗器"""
        self.cleaner = DataCleaner()

    @settings(max_examples=100)
    @given(text=st.text(max_size=500))
    def test_clean_text_is_idempotent(self, text: str):
        """对任意文本，清洗两次的结果应与清洗一次相同

        **Validates: Requirements 5.1**
        """
        once = self.cleaner.clean_text(text)
        twice = self.cleaner.clean_text(once)
        assert once == twice

    @settings(max_examples=100)
    @given(
        text=st.from_regex(
            r"<[a-z]+>[^<]*</[a-z]+>",
            fullmatch=True,
        )
    )
    def test_html_tags_removed_after_cleaning(self, text: str):
        """包含HTML标签的文本清洗后不应再含有HTML标签

        **Validates: Requirements 5.1**
        """
        result = self.cleaner.clean_text(text)
        assert "<" not in result or ">" not in result

    @settings(max_examples=100)
    @given(text=st.text(max_size=500))
    def test_no_leading_trailing_whitespace(self, text: str):
        """清洗后的文本不应有首尾空白

        **Validates: Requirements 5.1**
        """
        result = self.cleaner.clean_text(text)
        assert result == result.strip()


# Feature: trendpulse-sentiment-analysis, Property 6: 垃圾内容过滤
class TestSpamFilteringProperty:
    """垃圾内容过滤属性测试

    **验证: 需求 5.2, 5.3**

    对于包含广告关键词或机器人特征的文本，过滤器应正确识别并标记。
    """

    def setup_method(self):
        """每个测试方法前初始化清洗器"""
        self.cleaner = DataCleaner()

    @settings(max_examples=100)
    @given(
        keyword=st.sampled_from(SPAM_KEYWORDS),
        prefix=st.text(min_size=0, max_size=50),
        suffix=st.text(min_size=0, max_size=50),
    )
    def test_spam_keyword_always_detected(self, keyword: str, prefix: str, suffix: str):
        """包含任意垃圾关键词的文本应被识别为垃圾内容

        **Validates: Requirements 5.2**
        """
        content = f"{prefix} {keyword} {suffix}"
        assert self.cleaner.filter_spam(content) is True

    @settings(max_examples=100)
    @given(
        content=st.text(
            alphabet=st.characters(categories=("Lu",)),
            min_size=21,
            max_size=100,
        )
    )
    def test_excessive_uppercase_detected_as_spam(self, content: str):
        """超过50%大写字母且长度>20的文本应被识别为垃圾内容

        **Validates: Requirements 5.2**
        """
        # 全大写字母文本，长度>20，大写比例100%
        assert self.cleaner.filter_spam(content) is True

    @settings(max_examples=100)
    @given(
        author=st.sampled_from([
            "AutoModBot",
            "news_bot",
            "helper-bot",
            "reminder[bot]",
        ]),
        content=st.text(min_size=1, max_size=200),
    )
    def test_bot_author_always_detected(self, author: str, content: str):
        """作者名称以bot结尾的帖子应被识别为机器人内容

        **Validates: Requirements 5.3**
        """
        post = {"content": content, "author": author}
        assert self.cleaner.detect_bot_content(post) is True

    @settings(max_examples=100)
    @given(
        pattern_idx=st.integers(min_value=0, max_value=len(BOT_PATTERNS) - 1),
        suffix=st.text(min_size=0, max_size=100),
    )
    def test_bot_pattern_in_content_always_detected(self, pattern_idx: int, suffix: str):
        """内容匹配机器人特征模式的帖子应被识别为机器人内容

        **Validates: Requirements 5.3**
        """
        # 使用已知的机器人内容前缀来构造匹配内容
        bot_prefixes = [
            "I am a bot",
            "beep boop",
            "this action was performed automatically",
            "此操作由机器人自动执行",
        ]
        content = f"{bot_prefixes[pattern_idx]} {suffix}"
        post = {"content": content, "author": "some_user"}
        assert self.cleaner.detect_bot_content(post) is True
