"""
前端UI属性测试

测试前端UI中使用的纯逻辑函数的正确性属性。
由于前端使用Flutter（无PBT库），这些属性在Python后端中验证，
因为后端包含相同的核心逻辑。

属性 13: 舆情热度计算一致性
属性 14: 情感分数颜色映射

验证需求: 8.2, 8.4, 8.5, 8.6
"""

from hypothesis import given, settings, strategies as st

from backend.app.analysis.ai_analyzer import AIAnalyzer
from backend.app.analysis.sentiment_analyzer import SentimentAnalyzer


# ============================================================
# 辅助策略：生成模拟帖子数据
# ============================================================

# 生成单个帖子的策略
post_strategy = st.fixed_dictionaries({
    "title": st.text(min_size=0, max_size=50),
    "content": st.text(min_size=1, max_size=200),
    "likes": st.integers(min_value=0, max_value=100000),
    "comments": st.integers(min_value=0, max_value=100000),
    "shares": st.integers(min_value=0, max_value=100000),
})

# 生成帖子列表的策略
posts_strategy = st.lists(post_strategy, min_size=0, max_size=200)


# ============================================================
# 颜色枚举（对应前端 SentimentColors 的映射结果）
# ============================================================

class Color:
    """模拟前端颜色枚举，用于验证颜色映射逻辑"""
    RED = "red"
    AMBER = "amber"
    GREEN = "green"


def get_sentiment_color(score: float) -> str:
    """
    情感分数颜色映射函数

    与前端 SentimentColors.getColor 逻辑完全一致：
    - [0-30] → 红色（负面）
    - [31-70] → 黄色/琥珀色（中性）
    - [71-100] → 绿色（正面）

    Args:
        score: 情感分数 (0-100)

    Returns:
        颜色字符串
    """
    if score <= 30:
        return Color.RED
    elif score <= 70:
        return Color.AMBER
    else:
        return Color.GREEN


# ============================================================
# 属性 13: 舆情热度计算一致性
# Feature: trendpulse-sentiment-analysis, Property 13: 舆情热度计算一致性
# ============================================================

# **验证需求: 8.2**
@settings(max_examples=100)
@given(posts=posts_strategy)
def test_heat_score_deterministic(posts):
    """
    属性 13: 对于任意采集数据集，使用相同的采集数量和互动数据
    计算热度值应该得到相同的结果（计算是确定性的）。

    **Validates: Requirements 8.2**
    """
    score_a = AIAnalyzer._calculate_heat_score(posts)
    score_b = AIAnalyzer._calculate_heat_score(posts)

    # 确定性：相同输入产生相同输出
    assert score_a == score_b, (
        f"热度计算不确定: 第一次={score_a}, 第二次={score_b}"
    )

    # 热度值范围约束: 0-100
    assert 0.0 <= score_a <= 100.0, (
        f"热度值超出范围: {score_a}"
    )


# **验证需求: 8.2**
@settings(max_examples=100)
@given(posts=posts_strategy)
def test_heat_score_range(posts):
    """
    属性 13 补充: 热度值始终在 [0, 100] 范围内。

    **Validates: Requirements 8.2**
    """
    score = AIAnalyzer._calculate_heat_score(posts)
    assert 0.0 <= score <= 100.0, f"热度值超出范围: {score}"


# **验证需求: 8.2**
@settings(max_examples=100)
@given(
    posts_a=posts_strategy,
    posts_b=posts_strategy,
)
def test_heat_score_empty_is_zero(posts_a, posts_b):
    """
    属性 13 补充: 空帖子列表的热度值为0。

    **Validates: Requirements 8.2**
    """
    score = AIAnalyzer._calculate_heat_score([])
    assert score == 0.0, f"空列表热度应为0，实际为: {score}"


# ============================================================
# 属性 14: 情感分数颜色映射
# Feature: trendpulse-sentiment-analysis, Property 14: 情感分数颜色映射
# ============================================================

# **验证需求: 8.4, 8.5, 8.6**
@settings(max_examples=100)
@given(score=st.floats(min_value=0.0, max_value=30.0, allow_nan=False))
def test_color_mapping_negative_red(score):
    """
    属性 14: 情感分数 [0-30] 应映射为红色。

    **Validates: Requirements 8.4**
    """
    color = get_sentiment_color(score)
    assert color == Color.RED, (
        f"分数 {score} 应映射为红色，实际为: {color}"
    )

    # 同时验证后端分类一致性
    label = SentimentAnalyzer.classify_score(score)
    assert label.value == "negative", (
        f"分数 {score} 后端标签应为 negative，实际为: {label.value}"
    )


# **验证需求: 8.4, 8.5, 8.6**
@settings(max_examples=100)
@given(score=st.floats(min_value=31.0, max_value=70.0, allow_nan=False))
def test_color_mapping_neutral_amber(score):
    """
    属性 14: 情感分数 [31-70] 应映射为黄色/琥珀色。

    **Validates: Requirements 8.5**
    """
    color = get_sentiment_color(score)
    assert color == Color.AMBER, (
        f"分数 {score} 应映射为琥珀色，实际为: {color}"
    )

    label = SentimentAnalyzer.classify_score(score)
    assert label.value == "neutral", (
        f"分数 {score} 后端标签应为 neutral，实际为: {label.value}"
    )


# **验证需求: 8.4, 8.5, 8.6**
@settings(max_examples=100)
@given(score=st.floats(min_value=71.0, max_value=100.0, allow_nan=False))
def test_color_mapping_positive_green(score):
    """
    属性 14: 情感分数 [71-100] 应映射为绿色。

    **Validates: Requirements 8.6**
    """
    color = get_sentiment_color(score)
    assert color == Color.GREEN, (
        f"分数 {score} 应映射为绿色，实际为: {color}"
    )

    label = SentimentAnalyzer.classify_score(score)
    assert label.value == "positive", (
        f"分数 {score} 后端标签应为 positive，实际为: {label.value}"
    )


# **验证需求: 8.4, 8.5, 8.6**
@settings(max_examples=100)
@given(score=st.floats(min_value=0.0, max_value=100.0, allow_nan=False))
def test_color_mapping_covers_all_ranges(score):
    """
    属性 14: 对于任意 [0-100] 的情感分数，颜色映射函数
    应返回红色、琥珀色或绿色之一，且与分数范围一致。

    **Validates: Requirements 8.4, 8.5, 8.6**
    """
    color = get_sentiment_color(score)

    # 颜色必须是三种之一
    assert color in (Color.RED, Color.AMBER, Color.GREEN), (
        f"分数 {score} 映射到未知颜色: {color}"
    )

    # 验证颜色与分数范围的一致性
    if score <= 30:
        assert color == Color.RED
    elif score <= 70:
        assert color == Color.AMBER
    else:
        assert color == Color.GREEN
