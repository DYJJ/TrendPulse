"""
数据清洗模块

提供原始数据的清洗和过滤功能，包括：
- 文本清洗（移除HTML标签、特殊字符、多余空白）
- 垃圾内容检测（广告、推广内容）
- 机器人内容检测

需求: 5.1 (移除HTML标签、特殊字符和多余空白)
需求: 5.2 (过滤广告内容)
需求: 5.3 (标记或过滤机器人生成内容)
"""

import logging
import re
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# 广告/垃圾内容关键词列表
SPAM_KEYWORDS: List[str] = [
    "buy now",
    "click here",
    "free gift",
    "limited offer",
    "act now",
    "subscribe and win",
    "earn money fast",
    "make money online",
    "discount code",
    "promo code",
    "use code",
    "check out my",
    "follow my",
    "link in bio",
    "立即购买",
    "免费领取",
    "限时优惠",
    "点击链接",
    "加微信",
    "扫码关注",
    "优惠券",
    "折扣码",
]

# 机器人内容特征的正则模式
BOT_PATTERNS: List[str] = [
    r"^(I am a bot|我是机器人)",
    r"beep\s+boop",
    r"this action was performed automatically",
    r"此操作由机器人自动执行",
]



class DataCleaner:
    """数据清洗器

    负责清洗和过滤从各数据源采集的原始数据。
    支持HTML标签移除、特殊字符清理、乱码修复、垃圾内容检测和机器人内容检测。

    需求: 5.1, 5.2, 5.3
    """

    # 常见 mojibake（编码错误）替换映射
    _MOJIBAKE_MAP: dict[str, str] = {
        "\xc3\xa2\xe2\x82\xac\xe2\x84\xa2": "'",
        "\xc3\xa2\xe2\x82\xac\xc5\x93": '"',
        "\xc3\xa2\xe2\x82\xac\xc2\x9d": '"',
        "\xc3\xa2\xe2\x82\xac\xe2\x80\x9c": "\u2014",
        "\xc3\xa2\xe2\x82\xac\xe2\x80\x9d": "\u2013",
        "\xc3\xa2\xe2\x82\xac\xc2\xa6": "\u2026",
        "\xc3\x83\xc2\xa9": "\u00e9",
        "\xc3\x83\xc2\xa8": "\u00e8",
        "\xc3\x83\xc2\xbc": "\u00fc",
        "\xc3\x83\xc2\xb6": "\u00f6",
        "\xc3\x83\xc2\xa4": "\u00e4",
        "\xc3\x83\xc2\xb1": "\u00f1",
        "\xc3\x82": "",
    }

    # 乱码检测：高密度替换字符（U+FFFD）或连续非法序列
    _GARBLED_THRESHOLD = 0.3  # 文本中超过 30% 为不可识别字符则视为乱码

    def __init__(
        self,
        spam_keywords: Optional[List[str]] = None,
        bot_patterns: Optional[List[str]] = None,
    ) -> None:
        """初始化数据清洗器

        Args:
            spam_keywords: 自定义垃圾内容关键词列表，为None时使用默认列表
            bot_patterns: 自定义机器人特征正则模式列表，为None时使用默认列表
        """
        self._spam_keywords = [
            kw.lower() for kw in (spam_keywords or SPAM_KEYWORDS)
        ]
        self._bot_patterns = [
            re.compile(p, re.IGNORECASE)
            for p in (bot_patterns or BOT_PATTERNS)
        ]
        # 预编译HTML标签正则
        self._html_tag_re = re.compile(r"<[^>]+>")
        # HTML实体（常见的）
        self._html_entity_re = re.compile(r"&(?:#\d+|#x[\da-fA-F]+|\w+);")
        # 连续空白字符
        self._whitespace_re = re.compile(r"\s+")
        # 乱码特征正则：连续的替换字符或私用区字符
        self._garbled_char_re = re.compile(
            r"[\ufffd\ufffe\uffff\ud800-\udfff]"
            r"|[\ue000-\uf8ff]"
        )

    def fix_mojibake(self, text: str) -> str:
        """修复常见的 mojibake（编码错误导致的乱码）

        尝试两种策略：
        1. 字符串替换映射修复已知的双重 mojibake 模式
        2. 尝试 latin1->utf-8 反向解码修复（最常见的单层 mojibake）

        Args:
            text: 可能包含 mojibake 的文本

        Returns:
            修复后的文本
        """
        if not text:
            return ""

        result = text

        # 策略1：已知双重 mojibake 模式替换
        for bad, good in self._MOJIBAKE_MAP.items():
            if bad in result:
                result = result.replace(bad, good)

        # 策略2：尝试 latin1->utf-8 反向解码
        # 当 UTF-8 文本被错误地用 latin1 解码时，会出现 U+0080-U+00FF 范围的字符
        # 将其重新编码为 latin1 字节再用 utf-8 解码即可还原
        try:
            if any("\x80" <= c <= "\xff" for c in result):
                decoded = result.encode("latin1").decode("utf-8")
                # 解码成功即说明原文是 mojibake，直接采用
                result = decoded
        except (UnicodeDecodeError, UnicodeEncodeError):
            # 编码失败说明不是简单的 latin1 mojibake，保持原样
            pass

        return result

    def is_garbled(self, text: str) -> bool:
        """检测文本是否为乱码

        当文本中不可识别字符（U+FFFD 替换字符、私用区字符等）
        占比超过阈值时，判定为乱码。

        Args:
            text: 待检测文本

        Returns:
            True 表示是乱码，False 表示正常
        """
        if not text or not text.strip():
            return False
        return self._garbled_ratio(text) > self._GARBLED_THRESHOLD

    def _garbled_ratio(self, text: str) -> float:
        """计算文本中乱码字符的占比

        Args:
            text: 待检测文本

        Returns:
            乱码字符占比 (0.0-1.0)
        """
        if not text:
            return 0.0
        garbled_count = len(self._garbled_char_re.findall(text))
        return garbled_count / len(text)

    def clean_text(self, text: str) -> str:
        """清洗文本内容

        依次执行以下清洗步骤：
        1. 修复 mojibake 乱码
        2. 移除HTML标签
        3. 解码HTML实体
        4. 移除URL
        5. 移除特殊控制字符
        6. 标准化空白字符（多个空白合并为单个空格）
        7. 去除首尾空白

        清洗操作是幂等的：对已清洗的文本再次清洗会得到相同结果。

        Args:
            text: 原始文本

        Returns:
            清洗后的文本
        """
        if not text:
            return ""

        # 1. 修复 mojibake 乱码
        result = self.fix_mojibake(text)

        # 2. 移除HTML标签
        result = self._html_tag_re.sub("", result)

        # 3. 移除HTML实体
        result = self._html_entity_re.sub(" ", result)

        # 4. 移除URL
        result = re.sub(r"https?://\S+", "", result)

        # 5. 移除特殊控制字符（保留常见标点和中文字符）
        result = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", result)

        # 6. 移除 Unicode 替换字符和私用区字符
        result = self._garbled_char_re.sub("", result)

        # 7. 标准化空白字符
        result = self._whitespace_re.sub(" ", result)

        # 8. 去除首尾空白
        result = result.strip()

        return result

    def filter_spam(self, content: str) -> bool:
        """检测垃圾/广告内容

        通过关键词匹配和特征检测判断内容是否为垃圾内容。

        检测规则：
        - 包含广告关键词（不区分大小写）
        - 包含过多大写字母（超过50%且长度>20）
        - 包含过多重复字符

        Args:
            content: 文本内容

        Returns:
            True 表示是垃圾内容，False 表示正常内容
        """
        if not content:
            return False

        lower_content = content.lower()

        # 检查广告关键词
        for keyword in self._spam_keywords:
            if keyword in lower_content:
                logger.debug("检测到垃圾内容关键词: '%s'", keyword)
                return True

        # 检查过多大写字母（仅对英文内容有效）
        alpha_chars = [c for c in content if c.isalpha()]
        if len(alpha_chars) > 20:
            upper_ratio = sum(1 for c in alpha_chars if c.isupper()) / len(alpha_chars)
            if upper_ratio > 0.5:
                logger.debug("检测到过多大写字母，比例: %.2f", upper_ratio)
                return True

        # 检查重复字符模式（如 "!!!!!!" 或 "$$$$$"）
        if re.search(r"(.)\1{9,}", content):
            logger.debug("检测到过多重复字符")
            return True

        return False

    def detect_bot_content(self, post: Dict) -> bool:
        """检测机器人生成的内容

        通过正则模式匹配和行为特征判断内容是否由机器人生成。

        检测规则：
        - 内容匹配已知机器人特征模式
        - 作者名称包含 "bot" 后缀
        - 内容完全相同的重复发布（需外部去重，此处检测单条特征）

        Args:
            post: 帖子数据字典，应包含 'content' 和可选的 'author' 字段

        Returns:
            True 表示是机器人内容，False 表示正常内容
        """
        content = post.get("content", "")
        author = post.get("author", "")

        # 检查内容是否匹配机器人特征模式
        for pattern in self._bot_patterns:
            if pattern.search(content):
                logger.debug("检测到机器人内容模式")
                return True

        # 检查作者名称是否包含 bot 标识
        if author and re.search(r"bot$|_bot$|-bot$|\[bot\]$", author.lower()):
            logger.debug("检测到机器人作者: '%s'", author)
            return True

        return False

