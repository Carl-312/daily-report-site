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
    desc_max: 400

output:
  json_dir: data
  md_dir: content
  site_dir: dist

llm:
  default_timeout_seconds: 180
  capability_ttl_hours: 168
  attempts_filename: summary-attempts.json
  compatible_output_contract: true
  capabilities: []

enrichment:
  enabled: false
  trust_env: true
  min_articles: 10
  strict_hours: 24
  max_total_calls: 7
  max_verify_calls: 6
  max_refill_rounds: 1
  refill_max_results: 8
  verify_search_depth: basic
  enable_fuzzy_second_pass: false
  enable_official_fallback: false
  priority_refill_query: "OpenAI Anthropic AI model launch startup funding developer tools"
  official_fallback_query: "OpenAI Anthropic AI model launch startup funding developer tools"
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

### `llm`

定义 OpenAI-compatible 模型的非密钥 capability、逐模型 timeout、token 参数名和请求模式。
能力按 `(provider, base_url, model)` 精确匹配；未知模型默认使用 `prompt_only`，不会按模型名
猜测 thinking 或 Structured Outputs 参数。`json_schema` 只有在冲突负例证明 provider 真正
强制 Schema 后才能启用。完整字段、探针命令和失败分类见
[LLM API 兼容性运行手册](llm-api-compatibility.md)。

### `output`

- `json_dir`：日报原始 JSON 输出目录
- `md_dir`：日报 Markdown 输出目录
- `site_dir`：站点构建输出目录，默认 `dist`

### `enrichment`

Tavily 是 post-fetch enrichment 层，位于 source 抓取、去重之后，不是 `sources/` 下的新默认 source。

默认必须保持：

```yaml
enrichment.enabled: false
```

字段含义：

- `enabled`：默认是否启用 Tavily。当前 PR 不默认开启。
- `min_articles`：目标文章数，不代表一定补满。
- `strict_hours`：严格时间窗，当前目标是 24 小时，不为凑数量放宽。
- `max_total_calls` / `max_verify_calls` / `max_refill_rounds`：调用预算，避免单次运行不可控；默认会从总预算中为 priority + secondary refill 预留调用空间。
- `verify_search_depth`：verify 使用的 Tavily search depth，当前默认 `basic`。
- `enable_official_fallback`：是否启用官方站点补量，默认不启用。
- `trusted_domains`：策略层域名集合，不是线上热修名单。

术语约定：

- `verify`：验证已有 source 候选。
- `refill`：在 verify / preserved 后不足时按可信域名补量；priority 不足时再进入 secondary，达到 `min_articles` 后停止。
- `official_fallback`：官方站点补量，默认不启用。
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
MODELSCOPE_MODEL=ZhipuAI/GLM-5.2
MODELSCOPE_SECONDARY_MODEL=
SILICONFLOW_MODEL=Pro/moonshotai/Kimi-K2.6
SYFT_WEB_APP_URL=https://syft.example.com
SYFT_SECRET_KEY=your-syft-secret-key
AGIHUNT_API_KEY=
TAVILY_API_KEY=
```

AI 摘要的默认尝试顺序是：ModelScope `ZhipuAI/GLM-5.2` → SiliconFlow
`Pro/moonshotai/Kimi-K2.6`。只有显式设置 `MODELSCOPE_SECONDARY_MODEL` 时，才会在两者
之间增加第二个 ModelScope 候选。

当前状态（2026-07-14）：`ZhipuAI/GLM-5.2` 是约 753B 参数的当前旗舰。结构化摘要请求
固定传入 `enable_thinking=false`，避免 2000 token 上限被 reasoning 消耗；相同 14 篇
输入的本地真实请求已返回非空 `choices`、7 条摘要并通过完整 JSON/中文/来源合同。
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

`--enrichment auto` 会跟随 `config.yaml`，因此在默认 `enrichment.enabled: false` 下不会启用 Tavily。

## 相关文档

- 本地运行：[`local.md`](local.md)
- 扩展新闻源：[`../development/source-adapters.md`](../development/source-adapters.md)
- Tavily 接入总览：[`tavily.md`](tavily.md)
