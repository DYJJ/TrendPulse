"""
数据管道模块

实现采集数据的完整处理流程：验证 → 去重 → 清洗 → 批量写入。
每批次记录统计信息（total/valid/duplicate/discarded）。

需求: 7.1, 7.2, 7.3
"""

import logging
from dataclasses import dataclass, field
from typing import List, Set, Tuple

from sqlalchemy.orm import Session

from backend.app.database import bulk_insert
from backend.app.models.data_models import RawPost
from backend.app.models.db_models import RawPostDB, generate_uuid
from backend.app.processing.data_cleaner import DataCleaner

logger = logging.getLogger(__name__)



@dataclass
class BatchStats:
    """批次处理统计信息

    Args:
        total: 本批次总数据条数
        valid: 通过验证的有效数据条数
        duplicate: 去重过滤的重复数据条数
        discarded: 因内容为空等原因丢弃的数据条数
        spam: 被标记为垃圾/机器人内容的数据条数
        garbled: 因乱码被丢弃的数据条数
    """

    total: int = 0
    valid: int = 0
    duplicate: int = 0
    discarded: int = 0
    spam: int = 0
    garbled: int = 0




class DataPipeline:
    """数据管道

    负责采集数据的完整处理流程：
    1. 内容非空验证 — 丢弃空内容数据
    2. 基于 (source, external_id) 的去重
    3. 文本清洗（含乱码修复）
    4. 乱码检测 — 清洗后仍为乱码的数据被丢弃
    5. 垃圾内容/机器人检测 — 标记 is_spam
    6. 批量写入数据库

    需求: 7.1, 7.2, 7.3
    """

    def __init__(self, session: Session, cleaner: DataCleaner | None = None) -> None:
        """初始化数据管道

        Args:
            session: 数据库会话
            cleaner: 数据清洗器实例，为 None 时自动创建
        """
        self._session = session
        self._cleaner = cleaner or DataCleaner()
        # 已见过的 (source, external_id) 集合，用于跨批次去重
        self._seen_keys: Set[Tuple[str, str]] = set()

    def process_batch(
        self,
        posts: List[RawPost],
        task_id: str,
    ) -> BatchStats:
        """处理一批采集数据：验证 → 去重 → 清洗 → 脏数据检测 → 批量写入

        处理流程：
        1. 内容非空验证 — 内容为空或仅含空白字符的数据被丢弃
        2. 基于 (source, external_id) 去重 — 跳过已见过的记录
        3. 文本清洗 — 使用 DataCleaner 清洗内容（含乱码修复）
        4. 乱码检测 — 清洗后仍为乱码的数据被丢弃
        5. 垃圾内容/机器人检测 — 标记 is_spam 字段
        6. 批量写入 — 调用 bulk_insert 写入数据库

        Args:
            posts: 原始帖子列表
            task_id: 任务 ID

        Returns:
            BatchStats: 包含 total/valid/duplicate/discarded/spam/garbled 计数
        """
        stats = BatchStats(total=len(posts))
        valid_posts: List[RawPostDB] = []

        for post in posts:
            source_value = (
                post.source.value if hasattr(post.source, "value") else str(post.source)
            )
            key = (source_value, post.external_id)

            # 1. 内容非空验证
            if not post.content or not post.content.strip():
                stats.discarded += 1
                logger.debug(
                    "丢弃空内容数据: source=%s, external_id=%s",
                    source_value,
                    post.external_id,
                )
                continue

            # 2. 去重检查
            if key in self._seen_keys:
                stats.duplicate += 1
                logger.debug(
                    "跳过重复数据: source=%s, external_id=%s",
                    source_value,
                    post.external_id,
                )
                continue

            # 标记为已见
            self._seen_keys.add(key)

            # 3. 文本清洗（含乱码修复）
            cleaned_content = self._cleaner.clean_text(post.content)
            cleaned_title = (
                self._cleaner.clean_text(post.title) if post.title else None
            )

            # 清洗后再次检查内容是否为空
            if not cleaned_content or not cleaned_content.strip():
                stats.discarded += 1
                logger.debug(
                    "清洗后内容为空，丢弃: source=%s, external_id=%s",
                    source_value,
                    post.external_id,
                )
                continue

            # 4. 乱码检测 — 清洗后仍为乱码的数据直接丢弃
            if self._cleaner.is_garbled(cleaned_content):
                stats.garbled += 1
                logger.debug(
                    "检测到乱码内容，丢弃: source=%s, external_id=%s",
                    source_value,
                    post.external_id,
                )
                continue

            # 5. 垃圾内容/机器人检测 — 标记 is_spam
            is_spam = self._cleaner.filter_spam(cleaned_content)
            if not is_spam:
                post_dict = {"content": cleaned_content, "author": post.author}
                is_spam = self._cleaner.detect_bot_content(post_dict)

            if is_spam:
                stats.spam += 1
                logger.debug(
                    "标记为垃圾/机器人内容: source=%s, external_id=%s",
                    source_value,
                    post.external_id,
                )

            # 6. 构造数据库模型（垃圾内容仍入库但标记 is_spam=True）
            db_post = RawPostDB(
                id=generate_uuid(),
                task_id=task_id,
                source=source_value,
                external_id=post.external_id,
                title=cleaned_title,
                content=cleaned_content,
                author=post.author,
                url=post.url,
                timestamp=post.timestamp,
                likes=post.likes,
                comments=post.comments,
                shares=post.shares,
                is_spam=is_spam,
            )
            valid_posts.append(db_post)

        # 7. 批量写入数据库
        if valid_posts:
            inserted = bulk_insert(self._session, valid_posts)
            stats.valid = inserted
            # 数据库层去重可能额外过滤掉一些记录
            db_duplicates = len(valid_posts) - inserted
            stats.duplicate += db_duplicates
        else:
            stats.valid = 0

        logger.info(
            "批次处理完成: total=%d, valid=%d, duplicate=%d, discarded=%d, spam=%d, garbled=%d",
            stats.total,
            stats.valid,
            stats.duplicate,
            stats.discarded,
            stats.spam,
            stats.garbled,
        )

        return stats

