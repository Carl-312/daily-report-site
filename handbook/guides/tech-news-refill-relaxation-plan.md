# 科技新闻边界放宽与 Tavily 补全改造建议

最后更新：2026-06-23

## 定位

本文是一份新的策略转向文档，用于指导后续代码、配置、测试和灰度实验改造。

目标从“严格 AI 新闻验证”调整为：

1. 日报边界放宽为“科技新闻”，AI 是重点子集，不再是唯一入口。
2. Tavily enrichment 默认应尽量补充可解释的科技新闻，而不是优先删减 source 已抓到的内容。
3. 降低误杀，避免出现 Tavily 灰度运行把 5-8 条 source 产物压缩成 0-4 条的情况。
4. 搜到的可信科技新闻应尽量进入候选池，并在去重、时效和基础质量检查后补入最终产物。

本文不直接主张立即默认开启 Tavily。它定义的是下一轮应如何修改系统，使 Tavily 从“AI-only 严格验证器”变成“科技新闻补全层”。

## 背景问题

当前实现位于 `utils/news_enrichment.py`，核心行为是：

```text
source fetch
-> dedupe
-> prefilter
-> verify
-> priority refill
-> secondary refill
-> final articles
```

现有策略的主要问题：

1. 边界过窄：`STRICT_AI_TITLE_RE` 以 AI 标题命中为核心，很多真实科技新闻被降级为 `generic_or_low_signal`。
2. verify 具有破坏性：source 文章如果 Tavily 没匹配到、缺 `published_date` 或超出 24 小时窗口，会从最终结果中消失。
3. refill 仍是 AI-only：`test_refill_keeps_strict_ai_title_relevance_gate` 明确保证非 AI 标题不会进入补量，这与“科技新闻日报”目标冲突。
4. 补量查询过窄：当前 `priority_refill_query` 是 `OpenAI Anthropic AI model launch startup funding developer tools`，天然偏 AI 公司和模型发布。
5. 成功搜索不等于成功补全：近期灰度 artifact 中 Tavily 请求成功，但 `final_count` 仍可能很低，甚至 2026-06-23 灰度为 0 条。
6. 产物安全缺少底线：启用 Tavily 后，最终条数可能低于 source-only 结果，甚至生成空日报。

因此下一轮改造的原则应从“严格验证后替换 source 结果”改为“保留 source 结果，Tavily 提供验证标签和增量补全”。

## 当前 API 能力约束

根据 Context7 对 Tavily 官方文档的查询，当前 Search API 仍支持本项目需要的能力：

- `topic: news`
- `search_depth`
- `max_results`，当前文档上限为 20
- `time_range`
- `start_date` / `end_date`
- `include_domains` / `exclude_domains`
- `include_answer`
- `include_raw_content`
- `auto_parameters`
- 结果字段：`title`、`url`、`content`、`score`、`published_date`、`domain`

建议继续保持 HTTP API 调用方式，不必引入 Tavily Python SDK。项目已有 `requests.Session.post()` 封装，改造重点应在策略和诊断，不在 SDK 迁移。

`auto_parameters` 仍建议默认 `false`，因为本项目需要可复盘的成本和参数边界。可以新增灰度实验专门测试 `auto_parameters=true`，但不应混入本轮主改造。

## 新语义边界

### 旧边界

旧边界接近：

```text
AI news only
```

只有 OpenAI、Anthropic、Claude、ChatGPT、LLM、agent、robotics 等强 AI 词命中时，才被视为高价值候选。

### 新边界

新边界应调整为：

```text
technology news first, AI as a priority subset
```

建议接受以下科技新闻类别：

| Bucket | 示例 | 处理策略 |
|---|---|---|
| `ai_core` | AI 模型、AI 应用、AI 公司、智能体、机器人 | 高优先级 verify 和 refill |
| `tech_core` | 软件平台、开发者工具、网络安全、芯片、硬件、消费电子、云计算、数据中心 | 可进入 verify 和 refill |
| `tech_business` | 科技公司融资、并购、IPO、裁员、监管、产品战略 | 可进入最终产物，但摘要应突出科技影响 |
| `tech_adjacent` | 自动驾驶、能源科技、航天、游戏平台、创作者平台、社交平台重大功能 | 低优先级进入，数量不足时补入 |
| `non_tech` | 普通政治、娱乐、体育、泛商业、纯营销 | 拒绝或只保留诊断 |

实现上不要再用 `ai_relevant` 作为主判断名。建议新增：

```text
technology_relevant
topic_bucket
topic_confidence
acceptance_reason
```

保留 `ai_core` 只是排序信号，不再作为硬门槛。

## 核心策略修改建议

### 1. Tavily 不应再破坏 source-only 结果

当前 verify 失败会导致 source 文章被移出最终集合。新策略应改为：

```text
source articles are preserved by default
Tavily verify annotates confidence
Tavily refill appends additional trusted tech news
```

也就是：

- source 文章缺 title/link 或聚合型垃圾内容时仍可 hard reject。
- source 文章只是 Tavily `no_match`，不应删除。
- source 文章只是 `outside_24h`，应标记为 `date_unverified` 或 `outside_strict_window`，但默认保留，除非明确超过更宽的保留窗口。
- source 文章只是非 AI，但属于科技新闻，应保留。

必须新增产物安全底线：

```text
if input_count > 0 and Tavily has no transport error:
  final_count must be >= source_preserved_count
```

更直接的规则：

```text
Tavily enrichment can add articles, annotate articles, reorder articles, but must not reduce source-only final_count unless a hard reject rule is triggered.
```

这条规则能直接避免灰度产物变成空日报。

### 2. prefilter 从 AI 分层改为科技分层

当前 bucket：

```text
core_ai
ai_neighbor
generic_or_low_signal
```

建议替换或扩展为：

```text
ai_core
tech_core
tech_business
tech_adjacent
generic_or_low_signal
hard_reject
```

建议关键词方向：

| Bucket | 关键词方向 |
|---|---|
| `ai_core` | openai, anthropic, claude, chatgpt, llm, agent, model, inference, generative, AI |
| `tech_core` | software, platform, app, cloud, cybersecurity, chip, semiconductor, hardware, developer, data center |
| `tech_business` | startup, funding, IPO, acquisition, layoffs, regulation, antitrust, enterprise, revenue |
| `tech_adjacent` | autonomous, EV, robotaxi, space, gaming, creator platform, social network product changes |

`generic_or_low_signal` 不能直接等于拒绝。它只表示排序靠后，除非同时命中 `non_tech` 或营销型规则。

### 3. verify 改成 confidence annotation

verify 阶段的新职责：

1. 查 Tavily，确认 source 文章是否能被外部新闻索引找到。
2. 记录 `matched_url`、`matched_title`、`title_similarity`、`published_date`、`date_confidence`。
3. 给文章打标签，而不是删除文章。

建议新增状态：

| Field | Meaning |
|---|---|
| `verification_status=verified` | exact URL 或 same-domain + title similarity 命中且时间可信 |
| `verification_status=matched_but_stale` | 命中但超出严格窗口 |
| `verification_status=matched_missing_date` | 命中但缺 `published_date` |
| `verification_status=no_match_preserved` | 没命中，但 source 原文保留 |
| `verification_status=request_error_preserved` | Tavily 失败，source 原文 fail-open 保留 |

旧的 `rejected_candidates` 不应继续混合“真正拒绝”和“verify 没通过但保留”。建议拆成：

```text
hard_rejected_candidates
preserved_unverified_candidates
verify_diagnostics
```

### 4. refill 接受科技新闻，而不是只接受 AI 标题

当前 refill 接受条件里有严格 `ai_title_relevant()`。新策略应改成：

```text
technology_relevant(candidate.title, candidate.content, candidate.domain) is true
```

建议接受条件：

1. domain 在可信科技媒体池内。
2. title 或 content 命中科技相关 bucket。
3. `published_date` 在主窗口内，或在可配置宽松窗口内并带低置信标记。
4. 不与已有 source 或已补入候选重复。
5. 不是聚合页、纯列表页、广告页或无明确新闻事件的营销页。

建议新配置：

```yaml
enrichment:
  boundary_mode: tech_news
  preserve_source_on_verify_failure: true
  accept_refill_topic_buckets:
    - ai_core
    - tech_core
    - tech_business
    - tech_adjacent
  strict_hours: 24
  refill_search_window_hours: 48
  allow_soft_date_refill: true
  soft_date_window_hours: 72
```

其中 `allow_soft_date_refill` 不表示无条件接受旧新闻，而是允许在 source 不足时补入：

```text
trusted domain + technology relevant + within 72h + marked soft_date
```

最终摘要可以展示这些文章，但 JSON 诊断必须能区分 strict 与 soft。

### 5. refill 查询从窄 AI query 改为多查询科技 query

当前 query：

```text
OpenAI Anthropic AI model launch startup funding developer tools
```

建议拆成多组：

```yaml
refill_queries:
  - "technology news software startups cybersecurity chips hardware apps cloud"
  - "AI technology startups developer tools models robotics automation"
  - "consumer technology platforms social apps security semiconductors funding"
```

策略：

1. 第一组 broad tech query 用于保证科技新闻覆盖。
2. 第二组 AI query 保持 AI 权重。
3. 第三组用于捕捉非 AI 科技新闻。
4. 每组 query 都使用 `topic: news`。
5. 每组最多接受剩余缺口数量，避免补过量。

Tavily Search API 当前支持 `max_results` 到 20。建议 refill 阶段把 `refill_max_results` 从 8 灰度到 12 或 20，但用 final acceptance cap 控制最终数量。

不要只提高 `max_total_calls`。如果 query 仍然 AI-only，提高预算只会更快消耗在错误方向上。

### 6. 域名池调整为科技媒体池

现有 priority domain：

```yaml
thenextweb.com
venturebeat.com
```

现有 secondary domain：

```yaml
reuters.com
arstechnica.com
```

建议改为三层：

```yaml
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
  official_fallback_domains:
    - openai.com
    - anthropic.com
    - googleblog.com
    - microsoft.com
    - nvidia.com
```

注意：

- `source_overlap_domains` 不是坏事。它能帮助找回 source 抓漏或确认 TechCrunch/The Verge 文章。
- `reuters.com` 更适合科技商业、监管、公司事件，不适合纯产品补量。
- 官方域名可以作为产品发布 fallback，但应标记 `source_type=official`，不要和独立媒体新闻混淆。

域名是否最终进入默认配置，必须用灰度样本验证，不要一次性全开。

### 7. 结果排序改为“保留 + 补全 + 排序”

新 final assembly 建议：

```text
1. hard reject source invalid articles
2. preserve all valid source articles
3. append strict refill accepted articles
4. append soft-date refill accepted articles if still below min_articles
5. dedupe and story-cluster collapse
6. sort by topic bucket, freshness, domain trust, score
7. cap to max_articles
```

排序优先级：

1. verified source `ai_core`
2. verified source `tech_core`
3. strict refill `ai_core`
4. strict refill `tech_core`
5. source `tech_business` / `tech_adjacent`
6. strict refill `tech_business` / `tech_adjacent`
7. soft-date refill

这能保证 Tavily 搜到的新闻尽量补进去，但不会让低置信补量挤掉已有 source 主体。

## 配置修改建议

建议新增配置字段，而不是直接重用 AI-only 字段：

```yaml
enrichment:
  boundary_mode: tech_news
  preserve_source_on_verify_failure: true
  min_articles: 10
  max_articles_after_enrichment: 14
  strict_hours: 24
  refill_search_window_hours: 48
  soft_date_window_hours: 72
  allow_soft_date_refill: true
  max_total_calls: 10
  max_verify_calls: 4
  max_refill_rounds: 2
  refill_max_results: 12
  verify_search_depth: basic
  refill_search_depth: advanced
  refill_queries:
    - "technology news software startups cybersecurity chips hardware apps cloud"
    - "AI technology startups developer tools models robotics automation"
    - "consumer technology platforms social apps security semiconductors funding"
  accept_refill_topic_buckets:
    - ai_core
    - tech_core
    - tech_business
    - tech_adjacent
```

关键变化：

- `max_verify_calls` 从 6 降到 4，把预算让给 refill。
- `max_refill_rounds` 从 1 增到 2，提高补全机会。
- `refill_max_results` 从 8 灰度到 12，后续可测 20。
- 新增多 query，避免单一 AI query 限制 recall。
- `preserve_source_on_verify_failure=true` 是防空报告的核心。

## 代码修改点

### `config.py`

新增字段：

- `boundary_mode`
- `preserve_source_on_verify_failure`
- `max_articles_after_enrichment`
- `soft_date_window_hours`
- `allow_soft_date_refill`
- `refill_search_depth`
- `refill_queries`
- `accept_refill_topic_buckets`
- 新的 trusted domain 分层

保留旧字段一段时间，避免历史文档和测试立即失效。

### `utils/news_enrichment.py`

建议修改：

1. 将 `STRICT_AI_TITLE_RE` 拆成 `AI_CORE_RE` 与 `TECH_RELEVANCE_RE`。
2. 将 `AI_NEIGHBOR_TITLE_RE` 改为更通用的 `TECH_ADJACENT_RE`。
3. 新增 `classify_topic_bucket(title, content="", domain="")`。
4. 将 `ai_title_relevant()` 改成兼容 wrapper，但内部调用 `classify_topic_bucket()`。
5. 修改 `build_prefilter_summary()`：只 hard reject missing title/link 和聚合垃圾，不 hard reject 非 AI。
6. 修改 `run_verify_stage()`：verify 失败时按配置保留 source article，并记录 `verification_status`。
7. 修改 refill 接受条件：从 `ai_title_relevant` 改为 topic bucket allowlist。
8. 修改 final assembly：从“verified + refill”改为“source preserved + refill appended”。
9. 新增 final floor：如果 enrichment 后条数低于 source hard-valid 条数，回退到 source preserved + accepted refill。
10. 将 `accepted_by_stage_preview` 扩展为 `source_preserved`、`strict_refill`、`soft_refill`。

### `scripts/tavily_gray_scorecard.py`

新增指标：

- `source_input_count`
- `source_preserved_count`
- `source_dropped_count`
- `hard_rejected_count`
- `preserved_unverified_count`
- `strict_refill_accepted_count`
- `soft_refill_accepted_count`
- `topic_bucket_counts`
- `added_by_tavily_count`
- `final_count_delta_vs_source`

新的核心红线：

```text
final_count_delta_vs_source must be >= 0
```

除非 hard reject 明确说明 source 原文无效。

## 测试修改建议

需要新增或修改以下测试。

### Source 保留

1. `test_verify_no_match_preserves_source_article_when_configured`
2. `test_verify_outside_24h_preserves_source_with_date_warning`
3. `test_enrichment_never_returns_empty_when_source_has_valid_articles`

### 科技边界

1. `test_prefilter_classifies_non_ai_technology_as_tech_core`
2. `test_prefilter_classifies_startup_funding_as_tech_business`
3. `test_refill_accepts_trusted_non_ai_technology_news`
4. `test_refill_rejects_non_tech_social_or_political_news`

### 补全行为

1. `test_refill_uses_multiple_queries_until_min_articles`
2. `test_refill_appends_without_replacing_source_articles`
3. `test_soft_date_refill_can_enter_after_strict_pool_exhausted`
4. `test_refill_caps_at_max_articles_after_enrichment`

### 诊断字段

1. `test_report_records_source_preserved_and_added_by_tavily_counts`
2. `test_scorecard_surfaces_final_count_delta_vs_source`
3. `test_scorecard_fails_fixture_when_tavily_reduces_source_count`

需要修改的旧测试：

- `test_refill_keeps_strict_ai_title_relevance_gate` 应改为 `test_refill_keeps_technology_relevance_gate`。
- `test_prefilter_keeps_ai_neighbor_in_lower_priority_bucket` 应扩展为科技 bucket 测试。
- `test_verify_rejects_matched_article_outside_24h` 应改为保留 source 并记录日期风险，除非配置显式选择 destructive verify。

## 灰度实验建议

下一轮不要再只看 `final_count`。要看 Tavily 是否净增科技新闻。

### Experiment A: source-preserve

只改一个变量：

```yaml
preserve_source_on_verify_failure: true
```

成功标准：

- `final_count >= source_valid_count`
- `source_dropped_count = 0`
- verify 失败文章进入 `preserved_unverified_candidates`
- 不再出现 source 有输入但 final 为 0 的情况

### Experiment B: tech-boundary

只改 topic classifier 和 refill accept bucket。

成功标准：

- 非 AI 科技新闻不再被 `generic_or_low_signal` 误判为低价值。
- refill 能补入至少 1 条非 AI 科技新闻。
- 非科技新闻仍被拒绝。

### Experiment C: multi-query refill

只改 refill query 策略。

成功标准：

- `added_by_tavily_count > 0`
- `final_count_delta_vs_source > 0`
- 补入候选有明确 topic bucket 和 domain trust 解释。

### Experiment D: wider result pool

只改：

```yaml
refill_max_results: 12
```

或单独测试：

```yaml
refill_max_results: 20
```

成功标准：

- accepted/result 比例不显著恶化。
- 不是靠大量低质候选堆出来。
- Tavily latency 和调用成本可接受。

## GitHub Actions 安全建议

在灰度 workflow 允许回写最终报告前，必须加硬门槛：

```text
if source_valid_count > 0 and final_count < source_valid_count:
  do not commit generated data/content
  upload artifact only
  mark scorecard as failed or unsafe
```

建议新增 artifact 文件：

```text
gray/tavily/YYYY-MM-DD/safety-gate.json
```

字段：

```json
{
  "safe_to_commit": false,
  "source_valid_count": 7,
  "final_count": 0,
  "reason": "final_count_below_source_valid_count"
}
```

只有 `safe_to_commit=true` 时，灰度 workflow 才允许回写 `data/` 和 `content/`。

## 文档更新清单

如果按本文实施，需要同步修改：

1. `handbook/guides/tavily-integration.md`
   - 把“AI-only strict verifier”状态改为“technology news additive enrichment”目标。
   - 明确 source-preserve 是新红线。
2. `handbook/guides/configuration.md`
   - 增加新配置字段。
   - 删除“不为凑数量放宽”的绝对表述，改成“通过 source-preserve 和 soft-date 分层控制风险”。
3. `handbook/guides/troubleshooting.md`
   - 新增 “Tavily 搜到了但没有补入” 的排查路径。
   - 新增 “final_count 低于 source_count” 的安全门诊断。
4. `handbook/guides/gray1.3.md`
   - 当前仍是 AI-only 实验计划。应标记为历史计划，新增 Gray 1.4 或直接引用本文。
5. `README.md`
   - 将 Tavily 描述从 “AI 灰度增强” 改为 “科技新闻补全与验证增强”，但说明默认仍可关闭。

## 推荐实施顺序

1. 先实现 source-preserve 和安全门。
2. 再改 topic bucket，从 AI-only 放宽到 tech-news。
3. 再改 refill accept gate。
4. 再引入 multi-query refill。
5. 最后调预算和 `refill_max_results`。

不要反过来先加预算。当前主要问题不是调用次数绝对不足，而是策略过窄且 verify 具有破坏性。

## 最小可交付标准

下一轮 PR 至少应满足：

1. Source 有有效文章时，Tavily 不能把最终日报变空。
2. 非 AI 但明确科技的新闻可以保留并参与排序。
3. Refill 可以接受可信域名的非 AI 科技新闻。
4. JSON 诊断能区分 source preserved、strict refill、soft refill、hard reject。
5. Scorecard 能直接回答：Tavily 净增了几条新闻，误杀了几条，为什么。

达到这些标准后，再讨论是否让 Tavily 灰度结果回写正式每日产物。
