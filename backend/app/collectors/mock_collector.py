"""
模拟数据采集器

在未配置任何平台API凭据时，生成大规模仿真社交媒体数据。
支持10万+条数据量，用于演示和测试完整的分析流程。

数据特征：
- 多样化的情感倾向（正面/中性/负面按比例分布）
- 真实的互动数据分布（长尾分布）
- 多语言支持（中文/英文）
- 时间跨度覆盖近30天
"""

import asyncio
import hashlib
import logging
import math
import random
import uuid
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, List, Optional, Tuple

from backend.app.collectors.base import BaseCollector
from backend.app.models.data_models import DataSource, RawPost

logger = logging.getLogger(__name__)

# 每批生成的数据量（控制内存）
GENERATION_BATCH_SIZE = 5000


