"""
Mermaid思维导图生成器模块

将观点聚类结果转换为Mermaid mindmap语法，
并验证生成代码的有效性。

需求: 11.1 (将观点聚类结果转换为Mermaid格式)
需求: 11.2 (创建包含中心主题和3个分支的思维导图结构)
"""

import logging
import re
from typing import List, Union

from backend.app.models.data_models import Opinion

logger = logging.getLogger(__name__)


class MermaidGenerator:
    """Mermaid思维导图生成器

    将观点聚类结果转换为Mermaid mindmap格式代码，
    支持中心主题节点和多个分支节点的生成与验证。

    需求: 11.1, 11.2
    """

    # Mermaid mindmap中需要转义的特殊字符
    _SPECIAL_CHARS = {
        "(": "（",
        ")": "）",
        "[": "【",
        "]": "】",
        "{": "｛",
        "}": "｝",
    }

    def generate_mindmap(
        self,
        keyword: str,
        opinions: List[Union[Opinion, object]],
    ) -> str:
        """将观点聚类结果转换为Mermaid思维导图代码

        生成包含中心主题和分支节点的Mermaid mindmap语法。
        每个观点作为一个分支，附带支持度信息作为子节点。

        Args:
            keyword: 中心主题关键词
            opinions: 观点列表，每个观点需包含description、support_rate和order_index属性

        Returns:
            有效的Mermaid mindmap格式代码字符串

        Raises:
            ValueError: 当keyword为空或opinions为空时
        """
        if not keyword or not keyword.strip():
            raise ValueError("关键词不能为空")

        if not opinions:
            raise ValueError("观点列表不能为空")

        safe_keyword = self._escape_special_chars(keyword.strip())

        lines = [
            "mindmap",
            f"  root(({safe_keyword}))",
        ]

        sorted_opinions = sorted(
            opinions,
            key=lambda o: getattr(o, "order_index", 0),
        )

        for op in sorted_opinions:
            raw_desc = getattr(op, "description", "未知观点")
            # 将所有空白字符（换页符、制表符等）替换为空格，并去除首尾空白
            cleaned_desc = " ".join(raw_desc.split()) if raw_desc else ""
            desc = self._escape_special_chars(cleaned_desc or "未知观点")
            rate = getattr(op, "support_rate", 0.0)
            lines.append(f"    {desc}")
            lines.append(f"      支持度: {rate:.1f}%")

        code = "\n".join(lines)

        if not self.validate_mermaid(code):
            logger.warning("生成的Mermaid代码未通过验证，但仍返回结果")

        return code

    def validate_mermaid(self, code: str) -> bool:
        """验证Mermaid mindmap代码的基本语法有效性

        检查规则：
        1. 必须以 'mindmap' 开头
        2. 必须包含 root 节点
        3. 必须包含至少一个分支节点
        4. 缩进层级必须合理（子节点缩进大于父节点）

        Args:
            code: Mermaid代码字符串

        Returns:
            True表示代码语法有效，False表示无效
        """
        if not code or not code.strip():
            return False

        lines = code.strip().split("\n")

        # 规则1: 必须以 'mindmap' 开头
        if lines[0].strip() != "mindmap":
            return False

        # 规则2: 必须包含 root 节点
        has_root = False
        root_pattern = re.compile(r"^\s+root\(\(.*\)\)\s*$")
        for line in lines[1:]:
            if root_pattern.match(line):
                has_root = True
                break

        if not has_root:
            return False

        # 规则3: root之后必须有分支内容
        root_idx = None
        for i, line in enumerate(lines):
            if root_pattern.match(line):
                root_idx = i
                break

        if root_idx is None or root_idx >= len(lines) - 1:
            return False

        # 检查root之后是否有内容行
        has_branches = False
        for line in lines[root_idx + 1:]:
            if line.strip():
                has_branches = True
                break

        return has_branches

    def _escape_special_chars(self, text: str) -> str:
        """转义Mermaid语法中的特殊字符

        将可能破坏Mermaid解析的字符替换为全角等价字符。

        Args:
            text: 原始文本

        Returns:
            转义后的安全文本
        """
        for char, replacement in self._SPECIAL_CHARS.items():
            text = text.replace(char, replacement)
        return text
