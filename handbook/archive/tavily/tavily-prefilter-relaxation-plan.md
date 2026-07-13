# Tavily Prefilter Relaxation Plan

> 统一入口：当前 Tavily 接入总状态与 prefilter 下一步已经合并到 `handbook/guides/tavily-integration.md`。本文保留为 prefilter 放宽的专项计划草案。

## Goal

把 `utils/news_enrichment.py` 的本地预筛从“强 AI 标题门禁”调整为“时效优先、相关性分层”。

当前最该保住的硬目标不是“标题里必须显式出现 AI 词”，而是：

1. 文章真实存在
2. 文章在严格时间窗内
3. 错误时主流程安全降级
4. Tavily 调用预算仍然可控

## First pass scope

这一轮先只做一个保守版本，目标不是一次把策略放宽到底，而是先验证“放宽后能不能把更多边界样本送进 24 小时验证”。

本轮只建议做：

1. 把 `non_ai_relevant` 从硬拒绝改成软标签
2. verify 按 `core_ai -> ai_neighbor -> generic_or_low_signal` 分层消费预算
3. 增加基础观测项，确认新增候选到底变成了“有效命中”还是“额外噪音”

本轮先不做：

1. 不放宽 refill
2. 不引入更激进的 trusted-source 直通逻辑
3. 不改 `within_strict_hours()`、URL 精确匹配或相似度硬门槛

## Current bottleneck

当前 [`utils/news_enrichment.py`](../../../utils/news_enrichment.py#L533) 的 `build_prefilter_summary()` 里，只要标题不命中 `AI_KEYWORD_RE`，就会直接记为 `non_ai_relevant` 并被排除。

这会带来两个问题：

1. `Otter enterprise search`、`OpenClaw`、`autonomous vehicles` 这类 AI 邻近新闻在进入 verify 之前就被挡掉。
2. 你真正最关心的 `outside_24h` 过滤，经常还没机会执行，因为候选已经在本地标题门禁阶段被过滤掉了。

## What should stay strict

下面这些不建议放宽：

1. `within_strict_hours()` 仍然是最终硬门槛。
2. verify 阶段的 exact URL / same-domain + high-similarity 仍应保留。
3. 缺标题、缺链接、明显聚合型标题，仍然可以继续硬拒绝。
4. refill 仍然应该比 verify 更严格，避免预算失控。

## Relaxation plan

### Stage 1: 把 AI 相关性从 hard reject 改成 soft label

最小改动方案：

1. `missing_title`
2. `missing_link`
3. `aggregate_like`

上面 3 类继续硬拒绝。

`non_ai_relevant` 不再直接排除，而是改成候选标签，例如：

- `core_ai`
- `ai_neighbor`
- `generic_or_low_signal`

这样样本仍然可以进入后续时效验证，只是排序和预算优先级不同。

### Stage 2: verify 按分层队列消费预算

建议把 verify 预算改成分层消费，而不是单一顺序：

1. 先跑 `core_ai`
2. 再跑 `ai_neighbor`
3. 最后才考虑 `generic_or_low_signal`

这样既能放宽标题门禁，又不会把 Tavily 预算浪费在低信号项上。

### Stage 3: trusted source 可以降低标题门槛

这一段建议视第一轮观测结果再决定是否落地，不作为首批必做项。

对这些来源可适度放宽：

- `reuters`
- `techcrunch`
- `theverge`
- `cnn`
- `nytimes`
- `politico`
- `blog.google`

放宽方式不是“直接放过”，而是：

1. 如果标题没有命中强 AI 词，但 `content` 或 `description` 命中 AI 词，则从 `generic` 升为 `ai_neighbor`
2. 如果来源属于可信媒体或官方博客，则允许 `ai_neighbor` 进入 verify

这会直接解决当前“标题不显 AI、正文其实很 AI”的误杀问题。

### Stage 4: verify 和 refill 分开对待

建议只放宽 verify，不先放宽 refill。

原因：

1. verify 是对已有候选做时效性与真实性确认，放宽风险较低
2. refill 是主动补量，放宽太早会把结果池变脏

所以第一阶段最好保持：

- verify：放宽 AI 相关性门槛
- refill：继续维持当前较严的 AI 主题限制

这也是第一轮最重要的边界：先只动 verify，避免把主动补量链路一起放宽。

### Stage 5: 先补观测，再决定是否继续放宽

建议新增的观测项：

1. `prefilter_bucket_counts`
2. `neighbor_candidates_verified_count`
3. `neighbor_candidates_outside_24h_count`
4. `neighbor_candidates_no_match_count`

有了这些统计，才能判断“放宽后增加的是有效新闻，还是噪音”。

如果这一轮要再收敛一点，最少也应至少记录：

1. `prefilter_bucket_counts`
2. `neighbor_candidates_verified_count`
3. `neighbor_candidates_outside_24h_count`

## Recommended rollout

推荐按下面顺序推进：

1. 先把 `non_ai_relevant` 从硬拒绝改成分层标签
2. 保持 `strict_hours=24` 与 verify 严格匹配不变
3. 先只放宽 verify，不放宽 refill
4. 先加最小观测，确认 `ai_neighbor` 的去向是 `verified / outside_24h / no_match`
5. 用 curated replay fixture 观察 `Otter`、`OpenClaw`、`autonomous vehicles`、`Palantir` 这些边界样本
6. 如果噪音可控，再决定是否把 trusted source 放宽或把 `ai_neighbor` 扩展到部分 refill 路径

## Concrete first patch

如果现在就按“先小改一下”落代码，文档对应的最小实现面应当是：

1. 仅调整 `build_prefilter_summary()` 的 `non_ai_relevant` 处理方式，让它产出 bucket，而不是直接拒绝
2. verify 消费顺序改为先高信号、再中信号、最后低信号
3. 新增少量计数日志，先观察边界样本是不是只是更早暴露了 `outside_24h`

只要这三点成立，这次改动就已经达成“让时效过滤真正有机会生效”的目标。

## Success criteria

你要的“时效性优先”落地后，最理想的状态是：

1. 更多 AI 邻近新闻能进入 verify
2. 这些新闻仍然会被 24 小时时间窗正确淘汰或保留
3. Tavily 总调用数没有明显失控
4. refill 结果质量不被明显拉低
