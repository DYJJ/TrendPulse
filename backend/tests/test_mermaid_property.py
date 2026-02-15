"""
思维导图Mermaid格式属性测试

属性 19: Mermaid格式有效性
验证需求: 11.1, 11.2

使用Hypothesis库验证MermaidGenerator在各种输入下
生成的代码始终满足语法有效性和结构完整性。
"""

import re

from hypothesis import given, settings, strategies as st

from backend.app.analysis.mermaid_generator import MermaidGenerator
from backend.app.models.data_models import Opinion


# 生成合法的Opinion对象策略
opinion_strategy = st.builds(
    Opinion,
    description=st.text(
        min_size=1,
        max_size=100,
        alphabet=st.characters(
            blacklist_categories=("Cs",),
            blacklist_characters="\n\r\x00",
        ),
    ),
    support_rate=st.floats(min_value=0.0, max_value=100.0, allow_nan=False),
    order_index=st.integers(min_value=0, max_value=10),
)

# 生成恰好3个观点的列表策略（需求11.2要求3个分支）
three_opinions_strategy = st.lists(opinion_strategy, min_size=3, max_size=3)

# 关键词策略：非空、无换行
keyword_strategy = st.text(
    min_size=1,
    max_size=50,
    alphabet=st.characters(
        blacklist_categories=("Cs",),
        blacklist_characters="\n\r\x00",
    ),
).filter(lambda s: s.strip() != "")


generator = MermaidGenerator()


# Feature: trendpulse-sentiment-analysis, Property 19: Mermaid格式有效性
# **Validates: Requirements 11.1, 11.2**
@settings(max_examples=100)
@given(keyword=keyword_strategy, opinions=three_opinions_strategy)
def test_mermaid_format_validity(keyword: str, opinions: list):
    """
    属性19: 对于任意观点聚类结果，生成的Mermaid代码应该是语法有效的，
    并且包含中心主题节点和3个分支节点。

    验证:
    1. 代码以 'mindmap' 开头
    2. 包含 root 节点（中心主题）
    3. 包含3个分支节点（对应3个观点）
    4. 通过 validate_mermaid 验证
    """
    code = generator.generate_mindmap(keyword, opinions)

    # 验证基本语法：以 mindmap 开头
    lines = code.strip().split("\n")
    assert lines[0].strip() == "mindmap", "Mermaid代码必须以 'mindmap' 开头"

    # 验证包含 root 节点
    root_pattern = re.compile(r"^\s+root\(\(.*\)\)\s*$")
    root_lines = [l for l in lines if root_pattern.match(l)]
    assert len(root_lines) == 1, "必须包含恰好1个root节点"

    # 验证包含3个分支节点（每个观点生成一个分支行 + 一个支持度行）
    root_idx = next(i for i, l in enumerate(lines) if root_pattern.match(l))
    branch_lines = [
        l for l in lines[root_idx + 1:]
        if l.strip() and not l.strip().startswith("支持度:")
    ]
    assert len(branch_lines) == 3, f"应有3个分支节点，实际有{len(branch_lines)}个"

    # 验证通过内置验证器
    assert generator.validate_mermaid(code), "生成的Mermaid代码必须通过validate_mermaid验证"
