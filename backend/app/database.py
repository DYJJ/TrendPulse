"""
数据库配置和初始化模块

提供SQLAlchemy引擎、会话和Base类的配置。
使用 PostgreSQL 数据库，通过 DATABASE_URL 环境变量配置连接。
配置连接池（pool_size=10, max_overflow=20）以支持大规模并发读写。
"""

import logging

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from sqlalchemy.engine import Engine
from typing import Generator

from backend.app.config import get_config

logger = logging.getLogger(__name__)

Base = declarative_base()


def create_db_engine(database_url: str | None = None) -> Engine:
    """创建 PostgreSQL 数据库引擎

    配置连接池（pool_size=10, max_overflow=20），启用 pool_pre_ping
    自动检测断开的连接。

    Args:
        database_url: 数据库连接 URL，为 None 时从配置读取

    Returns:
        Engine: SQLAlchemy 数据库引擎
    """
    if database_url is None:
        database_url = get_config().database_url

    logger.info("使用 PostgreSQL 数据库引擎，启用连接池")
    return create_engine(
        database_url,
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True,
    )


# 使用配置中的 DATABASE_URL 创建默认引擎和会话
engine = create_db_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    """获取数据库会话的依赖注入函数"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()



def bulk_insert(session: Session, posts: list, batch_size: int = 500) -> int:
    """批量插入帖子数据到数据库

    每批 batch_size 条，遇到唯一约束冲突（相同 source + external_id）时
    跳过重复记录，继续插入其余数据。
    使用 savepoint（嵌套事务）确保单条冲突不影响整批数据。

    Args:
        session: 数据库会话
        posts: 待插入的 RawPostDB 实例列表
        batch_size: 每批插入条数，默认 500

    Returns:
        int: 实际成功插入的记录数
    """
    inserted_count = 0

    for i in range(0, len(posts), batch_size):
        batch = posts[i:i + batch_size]
        for post in batch:
            # 使用 savepoint，冲突时只回滚当前记录
            nested = session.begin_nested()
            try:
                session.add(post)
                session.flush()  # 显式 flush 以触发 PostgreSQL 唯一约束检查
                nested.commit()
                inserted_count += 1
            except Exception:
                nested.rollback()

    session.commit()
    logger.info("批量插入完成: 总计 %d 条，成功插入 %d 条", len(posts), inserted_count)
    return inserted_count
