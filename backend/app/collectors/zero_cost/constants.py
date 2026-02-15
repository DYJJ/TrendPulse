"""
零成本采集方案的配置常量

定义批次大小、延迟范围、并发数、重试参数和 User-Agent 池。
"""

# 批次大小：每批 yield 的数据条数
BATCH_SIZE = 500

# 搜索引擎请求延迟范围（秒）
SEARCH_DELAY_MIN = 2.0
SEARCH_DELAY_MAX = 5.0

# Syndication API 最大并发数
SYNDICATION_MAX_CONCURRENCY = 30

# Bluesky API 请求延迟范围（秒）
BLUESKY_DELAY_MIN = 1.0
BLUESKY_DELAY_MAX = 3.0

# 最大重试次数
MAX_RETRIES = 3

# 指数退避基础延迟（秒）
RETRY_BASE_DELAY = 1.0

# User-Agent 池
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]
