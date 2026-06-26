# 配置文件详解

项目配置主要来自 `config.yaml` 和 `.env`。

## `config.yaml`

当前示例：

```yaml
sources:
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

enrichment:
  enabled: false
  trust_env: true
  boundary_mode: tech_news
  preserve_source_on_verify_failure: true
  min_articles: 10
  max_articles_after_enrichment: 14
  strict_hours: 24
  max_total_calls: 10
  max_verify_calls: 4
  max_refill_rounds: 2
  refill_max_results: 12
  refill_search_window_hours: 48
  soft_date_window_hours: 72
  allow_soft_date_refill: true
  verify_search_depth: basic
  refill_search_depth: advanced
  enable_fuzzy_second_pass: false
  enable_official_fallback: false
  refill_queries:
    - "technology news software startups cybersecurity chips hardware apps cloud"
    - "AI technology startups developer tools models robotics automation"
    - "consumer technology platforms social apps security semiconductors funding"
  accept_refill_topic_buckets:
    - ai_core
    - tech_core
    - tech_business
    - tech_adjacent
  trusted_domains:
    source_overlap_domains:
      - techcrunch.com
      - www.theverge.com
    priority_tech_media_domains:
      - arstechnica.com
      - thenextweb.com
      - venturebeat.com
      - engadget.com
      - wired.com
    secondary_business_tech_domains:
      - reuters.com
      - bloomberg.com
      - cnbc.com
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
  aibase: true
  techcrunch: true
  theverge: true
  syft: false
```

### `limits.max_articles`

控制每天进入摘要与构建流程的文章上限。

### `summarize.prompt_path`

指定摘要 Prompt 模板文件。

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
- `boundary_mode`：当前为 `tech_news`，表示科技新闻优先，AI 是高优先级子集。
- `preserve_source_on_verify_failure`：默认 `true`。Tavily verify 失败、无匹配或缺日期时标注置信度，但不删除有效 source 文章。
- `min_articles`：目标文章数，不代表一定补满。
- `max_articles_after_enrichment`：source 保留后的最终上限；不会为了 cap 删除有效 source。
- `strict_hours`：严格时间窗，当前目标是 24 小时。
- `soft_date_window_hours` / `allow_soft_date_refill`：在 source 不足时，允许可信科技新闻在较宽窗口内以 `soft_refill` 标记补入。
- `max_total_calls` / `max_verify_calls` / `max_refill_rounds`：调用预算，避免单次运行不可控；默认会从总预算中为 priority + secondary refill 预留调用空间。
- `verify_search_depth`：verify 使用的 Tavily search depth，当前默认 `basic`。
- `refill_search_depth`：refill 使用的 Tavily search depth，当前默认 `advanced`。
- `refill_queries`：科技新闻多 query 补量池，不再只搜 AI 公司和模型发布。
- `accept_refill_topic_buckets`：允许进入补量的 topic bucket；默认接受 `ai_core`、`tech_core`、`tech_business`、`tech_adjacent`。
- `enable_official_fallback`：是否启用官方站点补量，默认不启用。
- `trusted_domains`：策略层域名集合，不是线上热修名单；新字段按 source overlap、priority tech media、secondary business tech 分层，旧 whitelist 字段暂时保留兼容。

术语约定：

- `verify`：验证已有 source 候选并写入 `verification_status`，默认不负责删除。
- `refill`：在 source preserved 后仍不足时按可信域名补量；priority 不足时再进入 secondary。
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
MODELSCOPE_MODEL=ZhipuAI/GLM-5.1
SYFT_WEB_APP_URL=https://syft.example.com
SYFT_SECRET_KEY=your-syft-secret-key
TAVILY_API_KEY=
```

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

`--enrichment auto` 会跟随 `config.yaml`，因此在默认 `enrichment.enabled: false` 下不会启用 Tavily。

## 相关文档

- 本地运行：[`../deployment/local.md`](../deployment/local.md)
- 扩展新闻源：[`extending-sources.md`](extending-sources.md)
- Tavily 接入总览：[`tavily-integration.md`](tavily-integration.md)
