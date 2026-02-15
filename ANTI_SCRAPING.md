# TrendPulse 反爬策略文档

## 概述

TrendPulse 需要从 Reddit、YouTube、X(Twitter) 三个平台采集舆情数据。这些平台均有不同程度的反爬机制，包括速率限制、IP 封禁、登录墙、JavaScript 渲染等。本文档详细说明系统采用的反爬策略和技术实现。

## 整体架构

系统采用**多级降级 + 多策略组合**的反爬体系：

```
请求层: User-Agent 轮换 + Header 伪造 + 代理支持
频率层: 随机延迟 + 指数退避 + 批次拆分
认证层: 账号池轮询 + Cookie 登录态注入
渲染层: Playwright 无头浏览器（JavaScript 渲染兜底）
调度层: 多数据源并发 + 断点续采 + 进度追踪
```

每个平台都有独立的降级链，单一方案失败时自动切换到下一级。

---

## 1. User-Agent 轮换与 Header 伪造

### 1.1 User-Agent 随机化

每次创建 HTTP 会话或浏览器上下文时，设置自定义 User-Agent，避免使用默认的 Python/aiohttp 标识：

| 平台 | User-Agent 策略 |
|------|----------------|
| Reddit | 初始化时传入 `TrendPulse/1.0`，通过 `aiohttp.ClientSession(headers={"User-Agent": ...})` 全局设置 |
| X(Twitter) twscrape | twscrape 内部自动管理 User-Agent，模拟真实浏览器 |
| X(Twitter) Playwright | 固定使用 Chrome 120 macOS UA：`Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0` |
| YouTube | yt-dlp 内部自动管理 User-Agent |

代码示例（Reddit 会话初始化）：

```python
self._session = aiohttp.ClientSession(
    timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
    headers={"User-Agent": self._user_agent},  # 默认 "TrendPulse/1.0"
)
```

### 1.2 HTTP Header 伪造

Playwright 浏览器上下文创建时注入完整的浏览器指纹信息：

```python
context = await self._browser.new_context(
    user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) ...",
    viewport={"width": 1920, "height": 1080},
    extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
)
```

关键伪造字段：
- `User-Agent`：模拟 Chrome 120 + macOS
- `viewport`：1920×1080 标准桌面分辨率
- `Accept-Language`：英文优先，符合目标平台用户特征


---

## 2. 代理支持

系统支持为每个平台独立配置 HTTP/SOCKS5 代理，用于绕过 IP 封禁和地域限制。

### 2.1 代理配置方式

| 平台 | 环境变量 | 说明 |
|------|---------|------|
| Reddit | `HTTP_PROXY` / `HTTPS_PROXY` | aiohttp 通过 `proxy` 参数传递 |
| X(Twitter) | `TWITTER_PROXY` | 优先读取，未设置时回退到 `HTTPS_PROXY` / `HTTP_PROXY` |
| YouTube | 系统代理 | yt-dlp 自动读取系统代理环境变量 |

### 2.2 代理传递机制

Reddit 采集器在每次 HTTP 请求中显式传递代理：

```python
async with session.get(url, params=params, proxy=self._proxy) as resp:
    ...
```

twscrape 在添加账号时绑定代理：

```python
await self._pool.add_account(
    username=acc["username"],
    password=acc["password"],
    email=acc["email"],
    email_password=acc["email_password"],
    proxy=self._proxy,  # 代理绑定到账号级别
)
```


---

## 3. 速率限制与退避策略

### 3.1 请求间随机延迟

各平台在分页请求之间插入延迟，避免触发速率限制：

| 平台 | 延迟策略 | 具体值 |
|------|---------|--------|
| Reddit PullPush | 固定延迟 | 每页请求间 `1.0s` |
| Reddit .json | 固定延迟 | 每页请求间 `1.0s`（`REDDIT_JSON_DELAY`） |
| X(Twitter) Playwright | 随机延迟 | 每次滚动后 `random.uniform(2.0, 4.0)s` |
| X(Twitter) 批量 | 可配置延迟 | `TWITTER_BATCH_DELAY` 环境变量，默认 `2.0s` |
| YouTube yt-dlp | 无额外延迟 | yt-dlp 内部自带速率控制 |

### 3.2 HTTP 429 指数退避

当 Reddit .json 端点返回 429 状态码时，自动执行指数退避重试：

```python
for attempt in range(MAX_RETRIES):  # MAX_RETRIES = 3
    async with session.get(url, params=params, proxy=self._proxy) as resp:
        if resp.status == 429:
            wait = REDDIT_JSON_BACKOFF_BASE * (attempt + 1)  # 5s, 10s, 15s
            await async_sleep(wait)
            continue
        resp.raise_for_status()
        return await resp.json()
```

退避时间序列：`5s → 10s → 15s`（基数 `REDDIT_JSON_BACKOFF_BASE = 5.0`）

### 3.3 通用重试机制

PullPush API 请求使用通用重试逻辑，非 429 错误也会重试：

```python
for attempt in range(MAX_RETRIES):  # 最多 3 次
    try:
        async with session.get(url, params=params, proxy=self._proxy) as response:
            response.raise_for_status()
            return await response.json()
    except Exception as e:
        if attempt < MAX_RETRIES - 1:
            await async_sleep((attempt + 1) * 1.0)  # 1s, 2s
        else:
            raise
```


---

## 4. Reddit 反爬策略

Reddit 采用三级降级链，每一级失败后自动切换到下一级。

### 4.1 降级链

```
Level 1: PullPush API（Pushshift 替代，免认证，历史数据丰富）
    ↓ 数据过时或请求失败
Level 2: Reddit .json 端点（免认证，实时数据，无需 API Key）
    ↓ 请求失败或被封
Level 3: Playwright 爬虫（无头浏览器渲染，最终兜底）
```

### 4.2 PullPush 数据新鲜度探测

在使用 PullPush 之前，先发送一个 `size=1` 的探测请求，检查最新数据的时间戳。如果最新帖子超过 30 天（`PULLPUSH_STALENESS_THRESHOLD_DAYS`），说明 PullPush 数据过时，直接跳过进入下一级：

```python
pullpush_usable = await self._check_pullpush_freshness(keyword, subreddit)
# 内部逻辑：请求 size=1，检查 created_utc 距今天数
# 超过 30 天 → 返回 False → 跳过 PullPush
```

### 4.3 多排序模式扩量采集

Reddit .json 端点单次搜索约返回 250 条结果。系统通过轮流使用 4 种排序方式扩大数据量：

```python
REDDIT_JSON_SORT_MODES = ["new", "relevance", "hot", "top"]
```

每种排序方式独立分页采集，使用内存 `seen_ids` 集合全局去重，避免重复数据。当某种排序方式返回的数据全部重复时，自动切换到下一种。

### 4.4 游标分页与去重

- PullPush：使用 `created_utc` 作为游标（`before` 参数），按时间倒序翻页
- Reddit .json：使用 Reddit 原生 `after` 游标分页
- 两者均维护 `seen_ids: set` 进行内存去重，防止分页边界重复数据

### 4.5 Playwright 兜底

当 API 方案全部失败时，调用 `RedditCollector`（Playwright 爬虫）作为最终兜底。爬虫模式上限 1000 条，超出部分自动截断并记录警告日志。


---

## 5. X(Twitter) 反爬策略

X 平台反爬最为严格，系统采用两级降级方案。

### 5.1 降级链

```
Level 1: twscrape 账号池（模拟内部 API，无需官方付费权限）
    ↓ 账号全部失败或被封
Level 2: Playwright + Cookie 登录态注入（无头浏览器兜底）
```

### 5.2 twscrape 账号池管理

通过 `AccountPoolManager` 从环境变量解析多账号配置：

```
# 环境变量格式（分号分隔多账号）
TWITTER_ACCOUNTS=user1:pass1:email1:epass1;user2:pass2:email2:epass2
```

解析逻辑：
```python
for entry in env_value.split(";"):
    parts = entry.split(":")
    if len(parts) != 4:
        continue  # 格式错误，跳过
    accounts.append({
        "username": parts[0], "password": parts[1],
        "email": parts[2], "email_password": parts[3],
    })
```

初始化时自动登录所有账号，并检查登录结果。如果所有账号均失败，抛出详细诊断信息：

```
常见失败原因：
1. 账号需要先在浏览器中手动登录一次完成安全验证
2. 账号开启了两步验证(2FA)，twscrape 不支持
3. 账号被锁定或需要手机验证
4. 密码中包含特殊字符导致解析错误
```

重试安全机制：每次初始化前先删除旧账号记录再重新添加，避免 `already exists` 错误和 `error_msg` 导致 `login_all` 跳过已失败账号。

### 5.3 Playwright Cookie 登录态注入

当 twscrape 不可用时，使用 Playwright 无头浏览器 + Cookie 注入方案：

```python
# 从 JSON 文件加载 Cookie
cookies = self._cookie_manager.load_cookies()
# 验证必须包含 auth_token 和 ct0 两个关键字段
if cookies and self._cookie_manager.validate_cookies(cookies):
    await context.add_cookies(cookies)
```

Cookie 验证规则：
- 必须包含 `auth_token`（X 平台登录凭证）
- 必须包含 `ct0`（CSRF Token）
- 两者缺一不可，否则降级为无登录态模式

### 5.4 滚动加载与去重

Playwright 模式通过模拟页面滚动加载更多推文：

```python
while count < effective_limit and scroll_attempts < MAX_SCROLL_ATTEMPTS:
    elements = await page.query_selector_all('article[data-testid="tweet"]')
    # 解析并去重...
    await page.evaluate("window.scrollBy(0, 800)")
    await asyncio.sleep(random.uniform(2.0, 4.0))  # 随机延迟模拟人类行为
```

- 最大滚动尝试次数：10 次（`MAX_SCROLL_ATTEMPTS`）
- 连续无新数据时自动停止
- 单次采集上限：500 条（`MAX_PLAYWRIGHT_LIMIT`）


---

## 6. YouTube 反爬策略

### 6.1 降级链

```
Level 1: yt-dlp Python API（主方案，速度快，数据丰富）
    ↓ yt-dlp 不可用或异常
Level 2: Playwright 爬虫（无头浏览器兜底，上限 500 条）
```

### 6.2 搜索变体生成

当采集量超过 100 条（`CONCURRENT_SEARCH_THRESHOLD`）时，自动生成关键词变体并发搜索，扩大数据覆盖面：

```python
@staticmethod
def _generate_search_variants(keyword: str) -> list:
    variants = [keyword]
    suffixes = ["latest", "2024 2025 2026"]
    for suffix in suffixes:
        variants.append(f"{keyword} {suffix}")
    return variants[:CONCURRENT_SEARCH_WORKERS]  # 最多 3 个变体
```

### 6.3 并发搜索与去重

使用线程池并发执行多个搜索变体，每路多搜 30% 补偿去重损耗：

```python
per_variant = max(int(limit / len(variants) * 1.3), CONCURRENT_SEARCH_THRESHOLD)

with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
    futures = {
        loop.run_in_executor(pool, do_search, v, per_variant): v
        for v in variants
    }
```

搜索完成后按 `video_id` 全局去重，保持原始顺序。

### 6.4 快速模式 vs 详情模式

| 模式 | 说明 | 速度 | 数据丰富度 |
|------|------|------|-----------|
| 快速模式（默认） | 仅使用搜索结果元数据，无额外网络请求 | 极快（数百条/秒） | 基本信息 |
| 详情模式 | 逐个视频提取详情（评论/字幕） | 较慢 | 完整信息 |

快速模式适合舆情分析场景，详情模式适合深度内容分析。


---

## 7. 批次调度与断点续采

### 7.1 任务自动拆分

当采集量超过 1000 条（`SPLIT_THRESHOLD`）时，`BatchScheduler` 自动将任务拆分为多个批次：

```python
@staticmethod
def split_task(limit: int, sources: List[str]) -> List[Dict]:
    for source in sources:
        if limit <= SPLIT_THRESHOLD:
            batches.append({"source": source, "offset": 0, "batch_limit": limit})
        else:
            # 按 1000 条一批拆分
            while remaining > 0:
                batch_limit = min(SPLIT_THRESHOLD, remaining)
                batches.append({...})
```

### 7.2 多数据源并发

调度器支持 Reddit、YouTube、Twitter 三个数据源同时并发采集，单个数据源失败不影响其他数据源：

```
Task(limit=3000, sources=[reddit, youtube, twitter])
  → Reddit: 1000 + 1000 + 1000（3 个批次）
  → YouTube: 1000 + 1000 + 1000（3 个批次）
  → Twitter: 1000 + 1000 + 1000（3 个批次）
  → 各数据源异步并发执行
```

### 7.3 速率限制

批次间插入可配置的延迟（`rate_limit_delay`），范围 0-3 秒，默认 1 秒：

```python
self._rate_limit_delay = max(0.0, min(rate_limit_delay, MAX_RATE_LIMIT_DELAY))
```

### 7.4 进度追踪与断点续采

- `TaskProgress` 数据类实时追踪每个数据源的采集进度（已采集条数、目标条数、状态）
- `SourceProgress.last_cursor` 记录最后游标位置，支持中断后从断点恢复
- `resume_task()` 方法读取持久化的进度信息，跳过已完成的批次继续采集


---

## 8. 通用容错机制

### 8.1 逐条错误隔离

所有数据解析方法（`_parse_pullpush_item`、`_parse_reddit_json_item`、`_parse_tweet` 等）均使用 try-except 包裹，单条数据解析失败不影响整批数据：

```python
@staticmethod
def _parse_pullpush_item(item: dict) -> Optional[RawPost]:
    try:
        # 解析逻辑...
        return RawPost(...)
    except Exception as e:
        logger.warning("解析 PullPush 数据失败: %s", e)
        return None  # 跳过此条，继续处理下一条
```

### 8.2 优雅降级

所有降级切换均通过 try-except 捕获异常并记录日志，确保用户无感知：

```python
try:
    async for batch in self._collect_pullpush(...):
        yield batch
    return
except Exception as e:
    logger.warning("PullPush API 采集失败: %s，尝试降级到 Reddit JSON", e)

# 自动进入下一级...
```

### 8.3 资源清理

所有采集器均实现 `close()` 方法，确保 HTTP 会话、浏览器实例等资源正确释放：

```python
async def close(self) -> None:
    if self._session and not self._session.closed:
        await self._session.close()
```

---

## 9. 环境变量配置参考

| 环境变量 | 说明 | 示例 |
|---------|------|------|
| `REDDIT_CLIENT_ID` | Reddit API 客户端 ID | `abc123` |
| `REDDIT_CLIENT_SECRET` | Reddit API 客户端密钥 | `secret456` |
| `REDDIT_USER_AGENT` | Reddit 请求 User-Agent | `TrendPulse/1.0` |
| `TWITTER_ACCOUNTS` | twscrape 账号池 | `user:pass:email:epass` |
| `TWITTER_COOKIES_PATH` | Playwright Cookie 文件路径 | `./cookies.json` |
| `TWITTER_PROXY` | Twitter 专用代理 | `http://127.0.0.1:7890` |
| `TWITTER_BATCH_DELAY` | 批量采集批次间延迟 | `2.0` |
| `HTTP_PROXY` / `HTTPS_PROXY` | 通用 HTTP 代理 | `http://127.0.0.1:7890` |
| `YOUTUBE_API_KEY` | YouTube Data API Key | `AIza...` |
| `COLLECTION_BATCH_SIZE` | 每批写入数据库的条数 | `500` |

---

## 10. 总结

TrendPulse 的反爬体系核心设计原则：

1. **多级降级**：每个平台至少 2-3 级降级方案，确保数据可达性
2. **速率控制**：请求间延迟 + 429 退避 + 批次拆分，避免触发平台限制
3. **身份伪装**：User-Agent 定制 + Header 伪造 + Cookie 登录态注入
4. **数据去重**：内存 `seen_ids` 集合 + 多排序模式/多变体搜索扩量
5. **容错隔离**：逐条解析错误隔离 + 单源失败不影响全局 + 断点续采