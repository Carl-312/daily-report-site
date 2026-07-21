# 配置文件详解

项目配置主要来自 `config.yaml` 和 `.env`。

## `config.yaml`

当前示例：

```yaml
sources:
  agihunt: false
  aibase: true
  techcrunch: true
  theverge: true
  syft: false

limits:
  max_articles: 14

summarize:
  prompt_path: prompts/daily.md
  prefer_chinese: true
  compress:
    title_max: 200
    desc_max: 1200

output:
  json_dir: data
  md_dir: content
  site_dir: dist

enrichment:
  enabled: true
  trust_env: true
  min_articles: 0
  strict_hours: 24
  max_total_calls: 30
  max_verify_calls: 0
  max_refill_rounds: 0
  refill_max_results: 8
  verify_search_depth: basic
  max_lead_candidates: 10
  lead_search_rounds: 2
  lead_search_depth: advanced
  lead_max_age_hours: 72
  enrichment_deadline_reserve_seconds: 240
  enable_fuzzy_second_pass: false
  enable_official_fallback: false
  priority_refill_query: "OpenAI Anthropic AI model launch startup funding developer tools"
  priority_refill_queries:
    - "OpenAI Anthropic xAI Google DeepMind frontier model launch research agent"
    - "Qwen DeepSeek Kimi GLM Doubao Hunyuan ERNIE 中国 大模型 发布 开源 评测"
    - "AI coding agent developer tools GitHub Cursor MCP open source model"
    - "AI multimodal image video voice robotics autonomous model"
    - "AI chip GPU compute data center cloud NVIDIA AMD Huawei"
    - "AI funding acquisition regulation safety lawsuit model company"
  official_fallback_query: "OpenAI Anthropic AI model launch startup funding developer tools"
  official_fallback_queries:
    - "official AI model release API research open source"
    - "中国 大模型 官方 发布 API 开源"
  trusted_domains:
    priority_refill_media_whitelist:
      - thenextweb.com
      - venturebeat.com
    secondary_refill_candidate_domains:
      - reuters.com
      - arstechnica.com
    official_fallback_domains:
      - openai.com
      - anthropic.com
```

## 关键字段

### `sources`

控制启用哪些新闻源：

```yaml
sources:
  agihunt: false
  aibase: true
  techcrunch: true
  theverge: true
  syft: false
```

`agihunt` 默认必须保持 `false`。本地或 GitHub 灰度只能通过显式
`--agihunt on` 临时覆盖；正式启用前需要完成多日 shadow 验证，详见
[AGIHunt 运行手册](agihunt.md)。

### `agihunt`

AGIHunt 的非密钥策略配置位于顶层 `agihunt:`。默认策略最多 5 次串行
请求：日报诊断、`models` / `research` / `coding-agents` 三个核心频道和
一个补充频道。`hot` 只在各自频道内排序；跨频道由固定配额决定。

`use_environment_proxy` 默认启用，只读取 `HTTP(S)_PROXY` / `ALL_PROXY` 与
`NO_PROXY` 来路由请求；客户端不会把环境中的 netrc 默认认证用于 AGIHunt。无法
直连时可保持该值为 `true`，需要强制直连时设为 `false`。

```yaml
agihunt:
  request_budget: 5
  use_environment_proxy: true
  include_report: true
  core_channels: [models, research, coding-agents]
  supplemental_channel: products
  max_articles: 20
  per_channel_limit: 6
  cache_ttl_seconds: 600
```

不要把 `AGIHUNT_API_KEY` 写入此处。它只允许存在于运行环境中。

`agihunt.max_articles` 是 AGIHunt 单独的候选上限，默认 20；它不会改动
`limits.max_articles` 对其他来源的 14 条上限。当前四频道配置每频道本地保留前 6 条，
形成 24 条候选缓冲，并在去重后至多保留 20 条；这是本地筛选上限，官方 API 本身每频道
返回 top-100。

### `limits.max_articles`

控制除 AGIHunt 外每个 source 进入摘要与构建流程的文章上限。AGIHunt 使用其自身的
`agihunt.max_articles`，以免为了扩大其候选池而无意增加其他来源的抓取量。

### `summarize.prompt_path`

指定摘要 Prompt 模板文件。

### `output`

- `json_dir`：日报原始 JSON 输出目录
- `md_dir`：日报 Markdown 输出目录
- `site_dir`：站点构建输出目录，默认 `dist`

### `enrichment`

Tavily 是 post-fetch enrichment 层，位于 source 抓取、去重之后，不是 `sources/` 下的新默认 source。

生产默认：

```yaml
enrichment.enabled: true
```

字段含义：

- `enabled`：默认是否启用 Tavily；缺少密钥时会降级并输出 `missing_api_key`，不会阻断已有直接故事。
- `min_articles`：旧版补量兼容字段；当前为 0，主新闻不设最低条数。
- `strict_hours`：严格时间窗，当前目标是 24 小时，不为凑数量放宽。
- `max_total_calls`：每日 Tavily 硬上限 30 次，同时限制正式候选队列最多 30 条；候选先各执行
  第一轮，剩余预算再执行第二轮。
- `max_verify_calls` / `max_refill_rounds`：旧版兼容字段，生产值均为 0。
- `lead_search_rounds`：Lead 与直接 Story 的统一搜索轮次上限，当前为 2。
- `lead_search_depth` / `lead_max_age_hours`：候选增强使用 advanced 搜索和 72 小时时间窗。
- `enrichment_deadline_reserve_seconds`：在全局截止前为摘要、构建和发布保留的秒数。
- `verify_search_depth`、`enable_official_fallback`、refill query 与 `trusted_domains`：仅为旧配置和历史工具兼容，生产候选队列不读取这些字段。

### `editorial_catalog.yaml`

该文件是选题与补量相关性判断的唯一结构化目录，维护：

- 中英文 AI 核心词、机器人/自动驾驶/芯片/算力等相邻领域词；
- 事件动作、对象与话题映射，用于跨来源、跨语言的同事件聚类；
- 美国、中国和基础设施公司的规范实体、别名与稳定模型家族；
- `requires_ai_context`，用于阻止只有 Apple、Microsoft 等泛科技公司名的新闻进入 AI 日报。

新增公司或模型时优先补稳定家族和别名，不要逐个枚举短期版本号；`Qwen3.7`、`DeepSeek-V4`、
`GLM-5` 一类数字后缀会由家族前缀识别。修改目录必须同步选择 fixture 与回放测试。

术语约定：

- `candidate_enrichment`：只处理抓取元数据队列中的 Lead 和直接 Story。
- `refill` / `official_fallback`：历史术语，当前生产路径不执行。
- `fail-open`：Tavily 出错时保住现有抓取和落盘。

## 路径约定

默认路径：

```text
data/     JSON 热数据
content/  Markdown 热数据
dist/     HTML 构建输出
```

注意：

- `dist/` 是构建产物，不进入 Git
- `data/` / `content/` 在部署流程中只保留最近 7 天
- 修改输出路径时，需要同步更新代码和文档

## `.env`

环境变量优先用于密钥和运行时覆盖项。

示例：

```bash
MODELSCOPE_API_KEY=sk-your-key
MODELSCOPE_MODEL=Qwen/Qwen3.5-35B-A3B
MODELSCOPE_SECONDARY_MODEL=
SILICONFLOW_MODEL=Pro/moonshotai/Kimi-K2.6
SYFT_WEB_APP_URL=https://syft.example.com
SYFT_SECRET_KEY=your-syft-secret-key
AGIHUNT_API_KEY=
TAVILY_API_KEY=
```

AI 摘要的默认尝试顺序是：ModelScope `Qwen/Qwen3.5-35B-A3B` → SiliconFlow
`Pro/moonshotai/Kimi-K2.6`。只有显式设置 `MODELSCOPE_SECONDARY_MODEL` 时，才会在两者
之间增加第二个 ModelScope 候选。

当前状态（2026-07-18）：ModelScope 官方 API-Inference 文档使用
`Qwen/Qwen3.5-35B-A3B` 作为当前 OpenAI 兼容示例，GitHub smoke run `29635323864`
已用仓库 Secret 验证非空 `choices`。结构化摘要请求通过 `chat_template_kwargs` 固定关闭
thinking，避免 2000 token 上限被推理过程消耗。旧的 `ZhipuAI/GLM-5.2` 在两次生产尝试中
连续返回空 `choices`，因此不再作为默认模型。
`Tencent-Hunyuan/Hy3` 的非流式响应会拼接多个 JSON 对象，前三个对象为空
`choices`，导致 OpenAI SDK 抛出 `JSONDecodeError`，因此不再作为默认备用模型。
历史人工复核或离线回放仍只能验证契约与渲染，不能作为 API 成功证据。

未配置 `MODELSCOPE_API_KEY` 时，可使用：

```bash
python main.py run --offline
```

`TAVILY_API_KEY` 只在显式启用 Tavily 时需要。本地启用：

```bash
TAVILY_API_KEY=... python3 main.py fetch --enrichment on
TAVILY_API_KEY=... python3 main.py run --offline --enrichment on
```

安全关闭：

```bash
python3 main.py fetch --enrichment off
python3 main.py run --offline --enrichment off
```

AGIHunt 灰度仅在完成授权后显式运行：

```bash
python3 main.py fetch --agihunt on --enrichment off
python3 main.py run --offline --agihunt on --enrichment off
```

`--enrichment auto` 会跟随 `config.yaml`；当前默认 `enrichment.enabled: true`，
缺少 `TAVILY_API_KEY` 时会安全降级并在日报底部显示 `missing_api_key`。

## 相关文档

- 本地运行：[`local.md`](local.md)
- 扩展新闻源：[`../development/source-adapters.md`](../development/source-adapters.md)
- Tavily 接入总览：[`tavily.md`](tavily.md)
