# TrendPulse 技术文档

## 1. 数据采集策略

### 1.1 整体架构

采集层采用 **批量调度器 + 平台采集器** 的插件式架构：

- `BatchScheduler` 作为协调器，为每个数据源创建对应的采集器并发执行
- 每个平台采集器独立实现，采集任务通过 `asyncio.gather` 并发执行
- 单个数据源失败不影响其他数据源，支持部分成功
- 采集结果通过数据管道（`DataPipeline`）进行清洗、去重、过滤后入库

### 1.2 Reddit 采集 — Arctic Shift API

使用 Arctic Shift 公开 API 进行批量采集，无需 Reddit 官方 API 密钥。

- 搜索端点：`https://arctic-shift.photon-reddit.com/api/posts/search`
- 支持按关键词、Subreddit、时间范围搜索
- 自动扩展 Subreddit 列表（根据关键词匹配相关社区）
- 支持 title 搜索和 selftext 搜索两种模式
- 每 500 条 yield 一批，支持流式入库

### 1.3 YouTube 采集 — yt-dlp 流式采集

使用 yt-dlp 工具进行搜索和元数据提取，无需 YouTube Data API Key。

- 通过 `ytsearch` 协议搜索视频
- 自动生成搜索变体（添加时间后缀、语言后缀等）扩大覆盖面
- 快速模式：仅提取元数据，不下载视频内容
- 每 200 条 yield 一批，支持流式入库

### 1.4 X(Twitter) 采集 — 零成本方案

这是本项目的核心技术亮点。由于 Twitter/X 官方 API 收费高昂（Basic 套餐 $100/月），我们设计了一套完全免费的采集方案，通过组合多个公开端点实现大规模数据采集。

#### 采集流程

```
搜索引擎 (DuckDuckGo/Google/Bing)
    │
    ├── 提取种子用户名 + 推文 ID
    │
    ▼
Syndication API (timeline-profile)
    │
    ├── 获取用户时间线推文 ID 列表
    │
    ▼
Syndication API (tweet-result)
    │
    ├── 批量获取推文详情（内容、作者、互动数据）
    ├── 提取 @mentions 中的新用户名
    │
    ▼
雪球扩展（重复上述步骤）
    │
    ├── 新用户 → 时间线 → 推文详情 → 更多新用户
    ├── 直到达到配额或无新用户
    │
    ▼
Bluesky Provider（补充采集）
    │
    ├── AT Protocol 公开 API 搜索
    │
    ▼
RSS Provider（补充采集）
    │
    └── 预配置 RSS 源聚合
```

#### 四个 Provider 的职责

| Provider | 数据源 | 作用 | 优先级 |
|----------|--------|------|--------|
| SearchEngineProvider | DuckDuckGo/Google/Bing + Syndication API | 主力采集，雪球式用户发现 | 1（最高） |
| BlueskyProvider | Bluesky AT Protocol API | 补充采集，覆盖跨平台内容 | 2 |
| RSSProvider | 预配置 RSS 源 | 补充采集，覆盖新闻类内容 | 3 |
| SyndicationProvider | Twitter Syndication API | 底层服务，被其他 Provider 调用 | - |

#### 雪球式用户发现算法

这是零成本方案的核心创新点。传统搜索引擎只能获取少量结果（通常 10-20 条），但通过雪球扩展可以指数级扩大采集范围：

1. 搜索引擎搜索 `site:x.com {keyword}`，提取种子用户名
2. 通过 `syndication.twitter.com/srv/timeline-profile` 获取每个用户的最近推文 ID
3. 通过 `cdn.syndication.twimg.com/tweet-result` 批量获取推文详情
4. 从推文内容中提取 `@mentions` 发现新用户
5. 对新用户重复步骤 2-4（雪球扩展）
6. 直到达到配额上限或无新用户可发现

性能优化：
- 用户时间线并发获取（`asyncio.gather`），而非串行
- 按需获取：当已有推文 ID 足够覆盖配额时，停止获取更多用户时间线
- 推文详情批量并发获取（30 并发），请求间仅 50-150ms 微延迟
- 搜索引擎自动降级（DuckDuckGo → Google → Bing）

#### Syndication API 端点

| 端点 | 用途 | 认证 |
|------|------|------|
| `cdn.syndication.twimg.com/tweet-result?id={id}` | 获取单条推文详情 | 无需 |
| `syndication.twitter.com/srv/timeline-profile/screen-name/{user}` | 获取用户时间线推文 ID | 无需 |

这些是 Twitter 官方用于嵌入式推文的公开端点，不需要任何认证，也没有严格的速率限制。

#### Bluesky 采集

- 使用 `public.api.bsky.app/xrpc/app.bsky.feed.searchPosts` 公开 API
- 支持 cursor 分页，自动翻页
- 指数退避重试（429 限流时自动等待）
- 无需认证，完全免费

### 1.5 数据管道

所有采集器的数据经过统一的数据管道处理：

1. **数据清洗**: 去除 HTML 标签、特殊字符、过短内容
2. **去重**: 基于 external_id 去重，避免重复入库
3. **垃圾过滤**: 检测并过滤垃圾信息（重复字符、纯链接等）
4. **乱码检测**: 过滤编码异常的内容
5. **批量入库**: 使用 savepoint（嵌套事务），单条冲突不影响整批数据

## 2. 反爬策略

### 2.1 User-Agent 轮换

维护 5 种主流浏览器标识的 User-Agent 池，每次请求随机选择：

```python
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 ...",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) ...",
    "Mozilla/5.0 (X11; Linux x86_64) ...",
    # ...
]
```

### 2.2 请求延迟策略

不同场景使用不同的延迟策略：

| 场景 | 延迟范围 | 说明 |
|------|----------|------|
| 搜索引擎请求 | 2.0-5.0s | 避免触发验证码 |
| Syndication 推文获取 | 0.05-0.15s | 公开端点，限制宽松 |
| Bluesky API | 1.0-3.0s | 公开 API，适度延迟 |

### 2.3 搜索引擎降级

当搜索引擎返回验证码或限流时，自动切换到下一个引擎：

```
DuckDuckGo（首选，无验证码）
    ↓ 失败
Google（备选，可能触发验证码）
    ↓ 失败
Bing（最后备选）
    ↓ 全部失败
尝试将关键词作为用户名直接查询时间线
```

### 2.4 代理支持

支持 HTTP/SOCKS5 代理，通过环境变量 `TWITTER_PROXY` 配置。国内环境访问 Twitter/X 必须配置代理。

### 2.5 重试与容错

- Syndication API: 最多 3 次重试，指数退避（1s → 2s → 4s）
- 429 限流: 自动等待后重试
- 超时: 15 秒超时，超时后跳过该条
- TweetTombstone（已删除/被封号推文）: 静默跳过，不计入错误

## 3. AI Prompt 设计

### 3.1 设计原则

- 使用中文 Prompt，因为系统面向中文用户
- 要求 LLM 返回严格的 JSON 格式，便于程序解析
- 每个 Prompt 明确指定输出格式和约束条件
- 设置较低的 temperature（0.3），保证输出稳定性

### 3.2 情感分析 Prompt

```
系统提示词:
你是一个专业的情感分析助手。请分析以下文本的情感倾向，
返回一个0到100之间的整数分数。
0表示极度负面，50表示中性，100表示极度正面。
只返回JSON格式: {"score": <数字>}
```

解析策略：
1. 优先尝试 JSON 解析提取 `score` 字段
2. JSON 解析失败时，使用正则 `\b(\d+(?:\.\d+)?)\b` 提取 0-100 范围内的数字
3. 所有方式失败时返回中性分数 50.0
4. 最终结果通过 `_clamp_score` 限制在 [0, 100] 范围

### 3.3 观点聚类 Prompt

```
系统提示词:
你是一个专业的舆情分析助手。请从以下文本中提取恰好3个主要争议点/观点。
每个观点需要包含简短描述和支持度百分比（所有支持度之和应为100）。
只返回JSON格式:
{"opinions": [
  {"description": "观点描述", "support_rate": 数字},
  {"description": "观点描述", "support_rate": 数字},
  {"description": "观点描述", "support_rate": 数字}
]}
```

后处理逻辑：
- 如果 LLM 返回的观点数量不等于 3，自动调整（截断或补充默认观点）
- 支持度归一化：确保所有观点的 `support_rate` 之和为 100
- JSON 解析失败时使用正则备选方案提取

### 3.4 摘要生成 Prompt

```
系统提示词:
你是一个专业的舆情分析助手。请将以下社交媒体内容总结为一段易读的摘要。
摘要长度必须在200到500字之间。
摘要应涵盖主要观点、情感倾向和关键争议点。
只返回JSON格式: {"summary": "摘要内容"}
```

长度调整策略：
- 过长：截断到最近的句子边界（中英文句号、感叹号、问号）
- 过短：追加预定义的补充说明句子，直到达到 200 字最低要求

## 4. Token 成本控制

### 4.1 Token 计数

使用 `tiktoken` 库进行精确 Token 计数。如果 tiktoken 不可用，使用估算方式：
- 英文：约 4 字符/token
- 中文：约 2 字符/token

### 4.2 分段处理策略

当输入文本超过 4000 Token 时，自动启用分段处理：

1. 按句子边界分割文本（中英文句号、感叹号、问号）
2. 每个片段不超过 4000 Token
3. 单个句子超过限制时，按词/字符强制分割

### 4.3 Map-Reduce 模式

处理大量文本时采用 Map-Reduce 模式：

1. **Map 阶段**: 将文本分成多个批次，分别调用 LLM 分析
2. **Reduce 阶段**: 将各批次的分析结果（摘要）合并，再次调用 LLM 生成最终结果

### 4.4 关键句提取

当需要压缩文本时，使用启发式方法提取关键句：
- 按句子分割文本
- 按句子长度降序排列（较长句子通常信息量更大）
- 按原始顺序选取句子，直到达到目标 Token 数

### 4.5 使用量监控

- 每次 LLM API 调用后记录 Token 使用量（prompt_tokens + completion_tokens）
- 累计使用量超过 `TOKEN_WARNING_THRESHOLD`（默认 100,000）时记录 WARNING 级别日志

## 5. 测试策略

### 5.1 属性测试 (Property-Based Testing)

使用 Hypothesis 框架编写属性测试，验证核心逻辑的通用正确性：

| 属性 | 验证内容 |
|------|----------|
| 推文 URL 解析正确性 | 任意合法推文 URL 都能正确提取 ID |
| 搜索查询构造正确性 | 构造的查询始终包含 `site:x.com` 前缀 |
| 批次大小不变量 | 每批 yield 的数据不超过 BATCH_SIZE |
| RawPost 字段完整性 | 解析成功的推文必须包含所有必填字段 |
| 无效数据过滤 | 缺少必填字段的数据返回 None |
| 去重不变量 | 输出中不存在重复的 external_id |
| 配额一致性 | 采集总数不超过 limit 参数 |
| Bluesky URL 格式正确性 | 生成的 URL 符合 AT Protocol 格式 |

### 5.2 单元测试

每个模块都有对应的单元测试，使用 mock 隔离外部依赖：

- 搜索引擎降级逻辑测试
- Syndication API 解析测试（固定 JSON 样本）
- 批量获取并发控制测试
- Provider 编排顺序测试
- 环境变量配置测试

## 6. 遇到的问题和解决方案

### 6.1 Twitter/X 官方 API 收费过高

**问题**: Twitter/X 官方 API Basic 套餐 $100/月，且有严格的速率限制，不适合学生项目。

**解决方案**: 设计了零成本采集方案，利用 Twitter 官方的 Syndication API（用于嵌入式推文的公开端点）+ 搜索引擎间接获取数据。通过雪球式用户发现算法，从少量种子用户扩展到大量推文，实现了无需任何 API Key 的大规模采集。

### 6.2 搜索引擎结果数量有限

**问题**: DuckDuckGo/Google 搜索 `site:x.com` 通常只返回 10-20 条结果，远不够大规模采集需求。

**解决方案**: 设计了雪球式用户发现算法。搜索引擎仅用于获取种子用户，然后通过 Syndication API 获取用户时间线，从推文中提取 @mentions 发现新用户，层层扩展。实测从 2 个种子用户可以扩展到数百个用户，采集数千条推文。

### 6.3 雪球扩展在小配额时过慢

**问题**: 即使只需要 100 条推文，雪球扩展仍会获取所有发现的用户时间线，导致大量不必要的网络请求。

**解决方案**: 实现了按需获取策略——当已有的推文 ID 数量足够覆盖剩余配额时，立即停止获取更多用户时间线。同时将用户时间线获取从串行改为并发（`asyncio.gather`），大幅减少等待时间。

### 6.4 已删除/被封号推文的处理

**问题**: Syndication API 对已删除或被封号的推文返回 `TweetTombstone` 类型，HTTP 状态码仍为 200，导致大量无效数据和警告日志。

**解决方案**: 在解析前先检查 `__typename` 字段，快速跳过 `TweetTombstone` 类型的响应，日志级别降为 DEBUG，避免刷屏。

### 6.5 LLM 响应格式不稳定

**问题**: LLM 返回的 JSON 格式可能不严格，包含额外文本或格式错误。

**解决方案**:
- 多层解析策略：JSON 解析 → 正则提取 → 默认值
- 情感分数解析失败时返回中性值 50.0
- 观点数量不正确时自动调整（截断或补充）
- 摘要长度不符合要求时自动调整（截断或补充）

### 6.6 Token 成本控制

**问题**: 大量文本直接发送给 LLM 会导致 Token 成本过高。

**解决方案**:
- 使用 tiktoken 精确计算 Token 数量
- 超过 4000 Token 时自动分段处理
- 支持 Map-Reduce 模式处理大批量文本
- 关键句提取减少不必要的 Token 消耗
- 累计使用量超过阈值时记录警告日志
