"""
数据库初始化脚本

运行此脚本以创建所有数据库表。
用法: python init_db.py
"""

import sys
import os

# 将项目根目录添加到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

from backend.app.database import engine, Base
from backend.app.models.db_models import (  # noqa: F401 - 确保模型被导入
    CollectionTaskDB,
    RawPostDB,
    AnalysisResultDB,
    OpinionDB,
    SubscriptionDB,
    AlertDB,
)


def init_database() -> None:
    """创建所有数据库表"""
    Base.metadata.create_all(bind=engine)
    print("数据库表创建成功！")


if __name__ == "__main__":
    init_database()
