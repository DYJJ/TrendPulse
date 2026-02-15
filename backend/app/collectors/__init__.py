"""
数据采集层

提供多平台数据采集功能，包括：
- CollectionEngine: 采集引擎，协调多数据源并发采集
- BaseCollector: 采集器抽象基类
- RedditCollector: Reddit数据采集器
- RedditBatchCollector: Reddit大规模批量采集器
- YouTubeCollector: YouTube数据采集器
- YouTubeBatchCollector: YouTube大规模批量采集器
- TwitterCollector: X(Twitter)数据采集器
- TwitterBatchCollector: X(Twitter)大规模批量采集器
- TwscrapeProvider: twscrape 采集提供者
- NitterProvider: Nitter 镜像站采集提供者
- PlaywrightProvider: Playwright 爬虫采集提供者
- AccountPoolManager: twscrape 账号池管理器
- CookieManager: 登录态 Cookie 管理器
"""

from backend.app.collectors.base import (
    BaseCollector,
    CollectionEngine,
    CollectionResult,
)
from backend.app.collectors.reddit_collector import RedditCollector
from backend.app.collectors.reddit_batch_collector import RedditBatchCollector
from backend.app.collectors.youtube_collector import YouTubeCollector
from backend.app.collectors.youtube_batch_collector import YouTubeBatchCollector
from backend.app.collectors.twitter_collector import TwitterCollector
from backend.app.collectors.twitter_batch_collector import TwitterBatchCollector
from backend.app.collectors.twitter_config import AccountPoolManager, CookieManager
from backend.app.collectors.twitter_twscrape_provider import TwscrapeProvider
from backend.app.collectors.twitter_nitter_provider import NitterProvider
from backend.app.collectors.twitter_playwright_provider import PlaywrightProvider

__all__ = [
    "BaseCollector",
    "CollectionEngine",
    "CollectionResult",
    "RedditCollector",
    "RedditBatchCollector",
    "YouTubeCollector",
    "YouTubeBatchCollector",
    "TwitterCollector",
    "TwitterBatchCollector",
    "TwscrapeProvider",
    "NitterProvider",
    "PlaywrightProvider",
    "AccountPoolManager",
    "CookieManager",
]
