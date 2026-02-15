"""
测试配置模块

提供测试用的 PostgreSQL 数据库会话和通用 fixture。
使用 trendpulse_test 数据库，每个测试前重建表结构。
"""

import os
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.database import Base
from backend.app.config import reset_config

# 测试数据库 URL
TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql://dengyijie@localhost:5432/trendpulse_test",
)

# 共享测试引擎
TEST_ENGINE = create_engine(TEST_DB_URL, pool_size=5, max_overflow=10, pool_pre_ping=True)


@pytest.fixture(autouse=True)
def setup_test_env(monkeypatch):
    """为测试环境设置必需的环境变量"""
    monkeypatch.setenv("LLM_API_KEY", "test-key-for-testing")
    monkeypatch.setenv("DATABASE_URL", TEST_DB_URL)
    reset_config()
    yield
    reset_config()


@pytest.fixture(autouse=True)
def setup_db():
    """每个测试前重建表，测试后清理"""
    Base.metadata.create_all(bind=TEST_ENGINE)
    yield
    Base.metadata.drop_all(bind=TEST_ENGINE)


@pytest.fixture
def db_session():
    """创建 PostgreSQL 测试数据库会话"""
    Session = sessionmaker(bind=TEST_ENGINE)
    session = Session()
    try:
        yield session
    finally:
        session.close()
