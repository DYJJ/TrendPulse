"""
输入参数验证模块

提供采集任务参数的验证功能，确保用户输入符合系统要求。

需求: 6.1, 6.2, 6.3, 6.4, 6.5
"""

from datetime import datetime
from typing import List, Optional

from backend.app.models.data_models import ValidationResult

# 系统支持的语言代码
SUPPORTED_LANGUAGES = {"en", "zh"}

# 采集条数限制范围
MIN_LIMIT = 1
MAX_LIMIT = 200000


def validate_collection_params(
    keyword: str,
    language: str,
    limit: int,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    subreddits: Optional[List[str]] = None,
) -> ValidationResult:
    """验证采集任务的输入参数

    对关键词、语言代码、条数限制、时间范围和 subreddit 列表进行校验，
    任一参数无效时返回包含描述性错误信息的验证结果。

    Args:
        keyword: 搜索关键词，不能为空
        language: 语言代码，仅支持 "en" 或 "zh"
        limit: 每个数据源的采集条数限制，范围 1-200000
        start_date: 起始日期（可选）
        end_date: 结束日期（可选）
        subreddits: 指定的 subreddit 列表（可选）

    Returns:
        ValidationResult: 验证结果，is_valid=True 表示通过，
                          否则 error 字段包含错误描述
    """
    # 验证关键词：不能为空或仅包含空白字符
    if not isinstance(keyword, str) or not keyword.strip():
        return ValidationResult(
            is_valid=False,
            error="关键词不能为空",
        )

    # 验证语言代码：仅支持 en 和 zh
    if language not in SUPPORTED_LANGUAGES:
        return ValidationResult(
            is_valid=False,
            error=f"不支持的语言代码: '{language}'，仅支持 {sorted(SUPPORTED_LANGUAGES)}",
        )

    # 验证条数限制：必须为整数且在 1-200000 范围内
    if not isinstance(limit, int) or isinstance(limit, bool):
        return ValidationResult(
            is_valid=False,
            error="条数限制必须为整数",
        )

    if limit < MIN_LIMIT or limit > MAX_LIMIT:
        return ValidationResult(
            is_valid=False,
            error=f"条数限制必须在 {MIN_LIMIT} 到 {MAX_LIMIT} 之间，当前值: {limit}",
        )

    # 验证时间范围：如果同时提供了起始和结束日期，起始日期必须早于结束日期
    if start_date is not None and end_date is not None:
        if start_date >= end_date:
            return ValidationResult(
                is_valid=False,
                error="起始日期必须早于结束日期",
            )

    # 验证 subreddits：如果提供了列表，不能为空列表且每项不能为空字符串
    if subreddits is not None:
        if not isinstance(subreddits, list):
            return ValidationResult(
                is_valid=False,
                error="subreddits 必须为列表类型",
            )
        if len(subreddits) == 0:
            return ValidationResult(
                is_valid=False,
                error="subreddits 列表不能为空",
            )
        for sub in subreddits:
            if not isinstance(sub, str) or not sub.strip():
                return ValidationResult(
                    is_valid=False,
                    error="subreddit 名称不能为空",
                )

    return ValidationResult(is_valid=True)
