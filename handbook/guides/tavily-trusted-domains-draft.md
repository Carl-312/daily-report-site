# Tavily trusted_domains 实验性草案

## 状态与边界

本文档只用于实验性设计，不用于正式集成。

- 基于 `2026-04-01` 首轮 benchmark 与同日保留性复测产物整理。
- 不改 `main.py`、`summarizer.py`、正式运行路径。
- 不把当前结论视为冻结配置，只作为下一轮 Tavily 实验的对照草案。

证据来源：

- `handbook/guides/tavily-news-enrichment.md`
- `data/benchmarks/tavily-baseline-2026-04-01.md`
- `data/benchmarks/tavily-baseline-2026-04-01.json`
- `data/benchmarks/tavily-whitelist-2026-04-01.md`
- `data/benchmarks/tavily-whitelist-2026-04-01.json`
- `data/benchmarks/tavily-whitelist-retention-2026-04-01-round12.md`
- `data/benchmarks/tavily-whitelist-retention-2026-04-01-round12.json`
- `data/benchmarks/tavily-whitelist-deferred-2026-04-01-round3.md`
- `data/benchmarks/tavily-whitelist-deferred-2026-04-01-round3.json`

## 2026-04-01 保留性复测结论

本节专门记录第 1 轮与第 2 轮的保留性复测结果，并明确区分“本次实测结果”与“推断建议”。

### 测试范围与缩减说明

- 本次只复测第 1 轮与第 2 轮目标域名：`thenextweb.com`、`venturebeat.com`、`techcrunch.com`、`openai.com`、`anthropic.com`、`blog.google`。
- 为保证前后可比，仍沿用 `scripts/benchmark_tavily_whitelist.py` 的既有 3 组英文 refill case，没有改 query 设计与判定口径。
- 本次没有重跑 `news.aibase.com`、`www.theverge.com`、`reuters.com`、`arstechnica.com`，原因只是为了把 API 成本收敛在“主白名单保留性 + 官方 fallback 保留性”这两个目标上。
- 影响：本次结果足以判断 round 1 与 round 2 的“保留/继续排除”是否成立，但不足以重排 deferred 池。

### 本次实测结果

1. 第 1 轮主白名单保留性复测成立。
   `thenextweb.com` 在 3 个英文 case 中平均每轮新增有效候选 `3` 条，`published_date` 可用率 `1.0`，平均重复已有结果 `0`；`venturebeat.com` 平均每轮新增有效候选 `1.3333` 条，`published_date` 可用率 `1.0`，平均重复已有结果 `0`。两者都继续满足主白名单保留条件。

2. `techcrunch.com` 继续只适合作为高重合对照组，不适合作为默认主白名单候选。
   它本次平均每轮新增有效候选仍有 `2.6667` 条，但平均每轮重复已有结果 `1.6667` 条，而且本身就是 configured source，边际补全价值没有显著逆转。

3. 第 2 轮官方 fallback 保留性复测成立。
   `anthropic.com` 平均每轮新增有效候选 `0.6667` 条，`published_date` 可用率 `1.0`；`openai.com` 平均每轮新增有效候选 `0.6667` 条，但 `published_date` 可用率只有 `0.6667`。两者都继续呈现“少量但可信”的官方候选信号，更适合作为 `official_fallback_domains`。

4. `blog.google` 继续不应进入默认名单。
   本次 3 个英文 case 下平均新增有效候选仍为 `0`，`published_date` 可用率仍为 `0.0`，没有出现足以推翻现有排除判断的逆转。

5. 本次 18 个请求全部成功，没有新增错误样本。
   与 `data/benchmarks/tavily-whitelist-2026-04-01.json` 对照时，6 个复测域名的核心结论没有出现方向性变化，只看到轻微波动，例如 `thenextweb.com` 的 `within_24h_rate` 从 `0.6667` 提升到 `0.7333`，`blog.google` 的 `ai_title_rate` 从 `1.0` 小幅降到 `0.9167`。

### 基于本次实测的推断建议

1. 当前 experimental 草案足以继续保留，不需要扩展默认名单。
   这次复测没有提供任何把 `techcrunch.com` 升回主白名单、或把 `blog.google` 放进 fallback 的新证据。

2. 当前更像是“维持现状”而不是“收缩名单”。
   `thenextweb.com`、`venturebeat.com`、`openai.com`、`anthropic.com` 都继续满足各自所在层级的保留条件，因此没有必要收缩掉现有草案中的 4 个保留域名。

3. 官方站点仍然只应保留在 fallback 层，不应提升到主 refill 媒体白名单。
   原因不是它们完全无值，而是它们的产出仍然偏稀疏，且 `openai.com` 的 `published_date` 稳定性仍然不够强，不符合主媒体白名单的准入画像。

## 2026-04-01 deferred 池挑战赛结论

本节记录第 3 轮实验结果，同样区分“本次实测结果”与“推断建议”。

### 测试范围与控制条件

- 本次复测域名：`reuters.com`、`arstechnica.com`、`www.theverge.com`。
- 沿用 `scripts/benchmark_tavily_whitelist.py` 的既有 3 组英文 refill case，没有改 query 设计、搜索深度或判定口径。
- 本次没有补跑 `techcrunch.com`，因为当前 source mix 没有出现明显变化：`config.yaml` 仍是 `techcrunch` / `theverge` / `aibase` 这组 source 配置，历史窗口内也仍以 `techcrunch` 为主、`aibase` 为辅、`theverge` 近窗为 `0`。
- 当前主白名单下界仍按 `venturebeat.com` 的平均每轮新增有效候选 `1.3333` 条作为对照门槛。

### 本次实测结果

1. `reuters.com` 继续只适合留在 deferred 池。
   本次 `published_date` 可用率 `1.0`、平均重复已有结果 `0`、平均每轮新增有效候选 `1`。它满足“metadata 稳定 + 低重合”，但仍低于主白名单下界 `1.3333`。

2. `arstechnica.com` 继续只适合留在 deferred 池。
   本次 `published_date` 可用率 `1.0`、平均重复已有结果 `0`、平均每轮新增有效候选 `1`。它与 `reuters.com` 一样，仍然达不到当前主白名单的新增有效候选门槛。

3. `www.theverge.com` 继续不应进入默认名单。
   本次平均 `published_date` 可用率虽然从首轮的 `0.0` 回升到 `0.3333`，但仍明显不稳定；平均每轮新增有效候选只有 `0.6667`，依旧不满足准入条件。

4. 本次 9 个请求全部成功，没有新增错误样本。
   相比首轮白名单研究，本轮没有出现足以推动任何 deferred / excluded 域名升级的方向性变化。

### 基于本次实测的推断建议

1. `reuters.com` 与 `arstechnica.com` 应继续保留在 `excluded_or_deferred_domains`，更准确地说是继续放在 deferred 候选层，而不是提升进 `refill_media_whitelist`。

2. `www.theverge.com` 应继续视为 excluded，而不是 deferred 优先候选。
   原因不是它完全没有结果，而是 `published_date` 稳定性依旧不足，这与当前“严格 24 小时校验”的硬门槛直接冲突。

3. 当前 experimental 草案不需要因为第 3 轮而扩展主白名单。
   这次挑战赛只支持“维持现有分层”，不支持把任何 deferred 域名晋升为默认 whitelist。

## 配置草案

下面是一版只供后续实验使用的 `config.yaml` 建议片段：

```yaml
enrichment:
  max_total_calls: 7
  max_verify_calls: 6
  max_refill_rounds: 1
  refill_max_results: 8
  verify_search_depth: basic
  enable_fuzzy_second_pass: false

  trusted_domains:
    refill_media_whitelist:
      - thenextweb.com
      - venturebeat.com
    official_fallback_domains:
      - openai.com
      - anthropic.com
    excluded_or_deferred_domains:
      - techcrunch.com
      - news.aibase.com
      - www.theverge.com
      - reuters.com
      - blog.google
      - arstechnica.com
```

这版配置的已有实测支持如下：

1. 参数默认值来自 `data/benchmarks/tavily-baseline-2026-04-01.md`，当前建议就是 `max_total_calls: 7`、`max_verify_calls: 6`、`max_refill_rounds: 1`、`refill_max_results: 8`、校验默认 `basic`、不保留模糊二次确认。
2. `thenextweb.com` 是当前最强的非重合媒体候选，在 `data/benchmarks/tavily-whitelist-2026-04-01.md` 里平均每轮新增有效候选 `3` 条，`published_date` 可用率 `1.0`，重复率 `0`。
3. `venturebeat.com` 是当前主白名单的下界域名，在 `data/benchmarks/tavily-whitelist-2026-04-01.md` 里平均每轮新增有效候选 `1.3333` 条，`published_date` 可用率 `1.0`，AI 标题相关率 `1.0`，重复率 `0`。
4. `openai.com` 与 `anthropic.com` 都表现出一定官方公告补充价值，但平均每轮新增有效候选都只有 `0.6667` 条，更适合作为 `official_fallback_domains`，不适合作为主 refill 媒体白名单。
5. `techcrunch.com` 虽然原始产出强，但重复已有抓取结果的问题明显，在 `data/benchmarks/tavily-whitelist-2026-04-01.md` 中平均每轮重复已有结果 `1.6667` 条，且本身已是 configured source。
6. `www.theverge.com` 在白名单专项 benchmark 中 `published_date` 可用率为 `0.0`，不满足严格 article-level whitelist 的前置条件。
7. `news.aibase.com` 在 `data/benchmarks/tavily-whitelist-2026-04-01.json` 中被标记为 `aggregate`，虽然 AI 标题相关率为 `1.0`，但平均新增有效候选为 `0`。
8. `reuters.com` 与 `arstechnica.com` 并非完全无值，但 AI 主题拟合度明显弱于当前主白名单，平均 AI 标题相关率分别只有 `0.2667` 和 `0.2`。
9. `blog.google` 的 `published_date` 可用率为 `0.0`，平均新增有效候选为 `0`，当前不宜进入任何默认名单。

## 白名单选择规则

本节把规则分成两层：

1. 已有实测支持的规则
2. 基于现有 benchmark 结果推导出的准入规则

### A. 已有实测支持的规则

1. 与现有抓取源高度重合的域名，不直接进入默认 `refill_media_whitelist`。
   证据：`techcrunch.com` 已是 configured source，在 `data/benchmarks/tavily-whitelist-2026-04-01.md` 中平均每轮重复已有结果 `1.6667` 条。它虽然平均每轮仍有 `2.6667` 条新增有效候选，但 refill 的边际价值弱于非重合媒体。

2. `published_date` 不稳定时，不进入默认 article-level whitelist。
   证据：`www.theverge.com` 与 `blog.google` 在 `data/benchmarks/tavily-whitelist-2026-04-01.md` 中的 `published_date` 可用率都为 `0.0`。在当前“严格 24 小时”设计下，这属于硬性排除条件。

3. 聚合站点不作为默认 article-level verify / refill 白名单。
   证据：`news.aibase.com` 在 `data/benchmarks/tavily-whitelist-2026-04-01.json` 中被标记为 `aggregate`，且在两组中文 refill case 中平均新增有效候选为 `0`。这也与 `data/benchmarks/tavily-baseline-2026-04-01.md` 中“聚合型标题不适合直接进入 Tavily article-level verify”的结论一致。

4. 官方博客与厂商站点单独管理，不与编辑型媒体主白名单混用。
   证据：`openai.com` 与 `anthropic.com` 在 `data/benchmarks/tavily-whitelist-2026-04-01.md` 中都只表现出“稀疏但有价值”的信号，平均每轮新增有效候选均为 `0.6667` 条，更适合进入 `official_fallback_domains`。

5. 主白名单优先选择非重合、`published_date` 稳定、重复低、持续有新增的编辑型媒体。
   证据：`thenextweb.com` 与 `venturebeat.com` 都满足 `published_date` 可用率 `1.0`、重复率 `0`、且在英文 refill benchmark 中持续产出新增有效候选，因此是当前最合适的 `refill_media_whitelist`。

6. 即使 `published_date` 稳定，如果 AI 主题相关性偏弱，也应先放入 deferred，而不是直接进主白名单。
   证据：`reuters.com` 与 `arstechnica.com` 的 `published_date` 都稳定，但在 `data/benchmarks/tavily-whitelist-2026-04-01.md` 中平均 AI 标题相关率分别只有 `0.2667` 与 `0.2`，明显弱于当前 shortlist。

### B. 基于现有结果推导出的准入规则

下面这些不是单条 benchmark 直接给出的结论，而是依据当前已入选域名画像推导出的下一轮准入门槛。它们属于“推断建议”。

1. 新域名只有在同一套 refill benchmark 矩阵下同时满足以下三项时，才允许进入 `refill_media_whitelist`：
   `published_date` 持续稳定、与现有日报重复数为 `0`、平均新增有效候选不弱于当前主白名单下界 `venturebeat.com` 的 `1.3333` 条每轮。

2. 如果域名有一定价值，但不满足默认 refill 目标，应降级为 `deferred`，而不是硬塞进主白名单。
   当前可见的降级原因包括：与现有抓取源高重合，例如 `techcrunch.com`；AI 主题拟合偏弱，例如 `reuters.com`、`arstechnica.com`；或者结果过窄、还不够稳定。

3. 如果域名的主要价值来自厂商原始公告，而不是持续提供编辑型补全，应降级为 `official_fallback_domains`。
   当前典型例子就是 `openai.com` 与 `anthropic.com`。

4. 如果域名直接违反 article-level 硬门槛，应继续留在 `excluded`，直到复测证据发生变化。
   当前典型例子是 `www.theverge.com`、`blog.google`、`news.aibase.com`。

## 这些规则如何服务后续 Tavily 实验

1. 它们把 refill 实验的关注点放在“边际补全价值”而不是“原始结果数量”上。
   这样可以避免已有强抓取源因为量大而反复挤占 refill 白名单。

2. 它们保护了当前“严格 24 小时校验”设计。
   只要把 `published_date` 稳定性设为硬门槛，后续实验就不会偏离 `data/benchmarks/tavily-baseline-2026-04-01.md` 已经验证过的时间判定路径。

3. 它们把三类 Tavily 任务拆开了。
   `refill_media_whitelist` 负责补编辑型新闻，`official_fallback_domains` 负责补厂商原始公告，`excluded_or_deferred_domains` 负责存放待复核或暂不适用的域名。

4. 它们为新域名提供了可重复的对照基线。
   后续不需要每次凭感觉讨论“要不要加这个站”，只需要看它是否达到当前已入选域名的最低画像。

## 后续实验迭代建议

下面三轮都保持最小增量，不涉及正式集成。

- 第 1 轮与第 2 轮已在 `2026-04-01` 完成保留性复测，当前小节保留其设计目标与后续使用方式，方便继续对照。
- 第 3 轮已在 `2026-04-01` 完成一次挑战赛复测，当前判定是不升级 deferred 池。

### 第 1 轮：主白名单保留性复测

当前状态：
已完成一次保留性复测，见 `data/benchmarks/tavily-whitelist-retention-2026-04-01-round12.md`。当前判定仍为“保留成立”。

实验目标：
确认 `thenextweb.com` 与 `venturebeat.com` 在新的回放窗口里是否仍然值得保留在 `refill_media_whitelist` 中。

需要比较的域名：
`thenextweb.com`、`venturebeat.com`、`techcrunch.com`

成功标准：
只要 `thenextweb.com` 与 `venturebeat.com` 继续保持 `published_date` 稳定、重复已有结果为 `0`、且在同类英文 refill case 中仍有非零新增有效候选，就视为保留成立。`techcrunch.com` 只作为重合对照组，不作为本轮主白名单候选。

支持类型：
比较对象来自已有实测；保留阈值属于基于当前 benchmark 的推断建议。

### 第 2 轮：官方 fallback 保留性复测

当前状态：
已完成一次保留性复测，见 `data/benchmarks/tavily-whitelist-retention-2026-04-01-round12.md`。当前判定仍为“保留成立，但不提升层级”。

实验目标：
确认 `openai.com` 与 `anthropic.com` 是否继续保留在 `official_fallback_domains`，以及是否还有其他官方站点值得保留在候选池。

需要比较的域名：
`openai.com`、`anthropic.com`、`blog.google`

成功标准：
若官方站点在同类 benchmark 中仍能稳定产出少量但可信的官方候选，可继续保留在 `official_fallback_domains`。若 `published_date` 继续不稳定，则继续排除。除非它同时满足主媒体白名单准入门槛，否则不提升到 `refill_media_whitelist`。

支持类型：
`openai.com` 与 `anthropic.com` 当前“稀疏但有值”的判断有实测支持；禁止直接提升为主白名单属于推断性护栏。

### 第 3 轮：deferred 池挑战赛

当前状态：
已完成一次挑战赛复测，见 `data/benchmarks/tavily-whitelist-deferred-2026-04-01-round3.md`。当前判定仍为“全部留在 deferred / excluded，不升级”。

实验目标：
确认当前 deferred 域名里是否有人应被提升，或者相反，deferred 池是否还可以进一步收缩。

需要比较的域名：
`reuters.com`、`arstechnica.com`、`www.theverge.com`

可选补充对照：
如果未来 source mix 有明显变化，可附带重跑 `techcrunch.com`。

成功标准：
只有当候选域名同时满足 `published_date` 稳定、与现有抓取低重合、且新增有效候选表现达到当前主白名单下界时，才允许提升。若继续存在 metadata 不稳定或 AI 主题拟合弱的问题，就维持在 `deferred` 或 `excluded`。

支持类型：
当前 defer / exclude 状态有实测支持；提升门槛属于从现有 accepted profile 推导出的实验规则。
