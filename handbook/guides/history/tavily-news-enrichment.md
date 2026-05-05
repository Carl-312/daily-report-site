# Tavily 新闻时效校验与补全方案

> 统一入口：当前 Tavily 接入状态、进度、风险和下一步已经合并到 `handbook/guides/tavily-integration.md`。本文保留为历史方案与实验记录，不再作为当前状态的唯一依据。

## 目标

在现有日报流水线中新增一个统一增强层，用 Tavily 完成两件事：

1. 严格验证进入最终摘要的新闻是否在最近 24 小时内发布。
2. 当有效新闻不足 10 条时，多轮调用 Tavily 进行补全回填。

方案要求优先保证准确性，同时限制单次运行的 API 调用次数与整体耗时。

## 当前状态

截至 `2026-04-01`，本方案处于“Phase 0 基准测试与 replay harness 已完成，正式模块化接入已落地一版，但仍需继续加固”的状态。

- 已完成 Tavily Phase 0 benchmark，并已完成一版正式运行链路接入。
- 已完成 `trusted_domains` 首轮研究，以及 round 1 / round 2 保留性复测、round 3 deferred 池挑战赛。
- 已完成 dry run / replay harness，并补上 near-duplicate / story-cluster 与 staged refill 的实验观察。
- 当前 experimental 结论已经收敛到一版分层 trusted domains 草案。
- 已新增正式模块 `utils/news_enrichment.py`，并把它接入 `main.py` 的 `run` / `fetch` 正式链路。
- 已在 `config.py` / `config.yaml` 中新增 enrichment 配置，并提供 CLI 开关 `--enrichment auto|on|off`。
- 已新增 `tests/test_news_enrichment.py`，目前最小测试矩阵与原有测试一起共 `7` 项通过。
- 已触发一次 `2026-04-01` 当天真实任务测试；主流程跑通并落盘，但当天结果暴露出“source 超时 + Tavily 超时”下仍可能得到 `0` 条正式文章，说明还不适合默认开启。

## 本阶段正式集成目标

本阶段不再只停留在 experiment harness，而是准备把 Tavily 增强层以“可开关、可回退、可观察”的方式接入正式项目。

本阶段目标限定为：

1. 新增 `utils/news_enrichment.py`，把实验里已经验证过的核心逻辑收敛成正式模块。
2. 在 `main.py` 的 `dedupe` 之后接入增强层，但默认仍允许关闭，避免影响现有日常运行。
3. 在 `config.py` / `config.yaml` 中提供明确开关与预算参数，不把实验参数硬编码进主流程。
4. 保留 JSON 输出中的增强诊断信息，确保当天真实运行后能回看 verify / refill / cluster 的行为。
5. 补最小测试，至少覆盖“关闭时直通”“开启但缺 Tavily key 时安全降级”“关键配置解析”这类正式接入护栏。
6. 在正式接入完成后，触发一次 `2026-04-01` 的当天真实任务测试，确认默认主流程可跑通。

## 本轮已实施现状

本轮已经完成的正式接入如下：

1. 正式模块
   已新增 `utils/news_enrichment.py`，当前收敛了这些能力：
   - 本地 prefilter
   - exact verify
   - priority refill
   - secondary refill
   - optional official fallback
   - refill 阶段的 near-duplicate / story-cluster 拦截

2. 配置与开关
   当前正式链路同时支持：
   - `config.yaml` 中的 `enrichment.enabled`
   - CLI 一次性 override：`--enrichment auto|on|off`

   当前 `config.yaml` 默认仍是：
   - `enabled: false`

   这样日常运行不会被 Tavily 直接改变，而当天验证或灰度测试可以显式执行：

   ```bash
   python3 main.py run --enrichment on
   python3 main.py fetch --enrichment on
   ```

3. 正式链路接入点
   当前 `main.py` 的正式顺序已经变成：

   ```text
   fetch_all
   -> dedupe
   -> enrich_articles_with_tavily (optional)
   -> save_json
   -> summarize
   -> build
   ```

   其中：
   - `run` 会执行完整链路
   - `fetch` 会保存 enrichment 后的 JSON
   - `summarize` 仍只消费已有 JSON，不重复调用 Tavily

4. 正式输出
   当前 JSON 已新增顶层 `enrichment` 诊断字段，至少会记录：
   - 是否启用
   - 是否实际应用
   - skip / error 原因
   - verify / refill / fallback / total 调用数
   - cluster 统计
   - `accepted_by_stage_preview`

5. 最小护栏测试
   当前已经覆盖：
   - 关闭时直通
   - 开启但缺 Tavily key 时安全降级
   - enrichment 配置解析

## 2026-04-01 当天真实任务测试

本次当天真实任务使用：

```bash
python3 main.py run --enrichment on
```

本次实测结果：

- `aibase`、`techcrunch`、`theverge` 三个抓取源都在 live 请求阶段超时，导致 fetch 原始结果为 `0` 条。
- Tavily enrichment 仍被正式触发，`verify_calls = 0`、`refill_calls = 2`、`fallback_calls = 0`、`total_calls = 2`。
- priority refill 与 secondary refill 两次 Tavily 请求都在 `45` 秒超时，没有拿回结果。
- 尽管如此，正式主流程仍然跑完了：
  - `data/2026-04-01.json` 已写出
  - `content/2026-04-01.md` 已写出
  - `dist/` 已成功重建
- 当天最终正式文章数为 `0`，Markdown 内容为 `暂无新闻`。

这次当天测试说明的不是“功能无效”，而是：

- 正式接入的控制面已经跑通
- 主流程没有因为 enrichment 异常而中断
- 但当前 fail-open / retry / timeout 策略还不够强，面对真实网络波动时，正式结果仍可能被压到 `0`

因此当前更准确的结论是：

- 正式模块化接入已经完成第一版
- 还不适合作为默认开启路径
- 下一轮应优先补“网络超时下的正式降级策略”，再考虑把 `enabled` 默认改成 `true`

## 正式集成边界

本阶段与前一轮 experiment harness 的边界不同，但仍保留以下限制：

- 只把已经有实验依据的路径接入正式项目，不额外扩展新的 Tavily 策略。
- 默认仍以当前实验参数作为初始值：`max_total_calls = 7`、`max_verify_calls = 6`、`max_refill_rounds = 1`、`refill_max_results = 8`。
- verify 默认仍用 `basic`。
- fuzzy second pass 默认仍关闭。
- staged refill 默认顺序仍是：
  - priority whitelist：`thenextweb.com`、`venturebeat.com`
  - secondary refill：`reuters.com`、`arstechnica.com`
  - official fallback：`openai.com`、`anthropic.com`
- cluster 规则目前只把“refill 与已接受集合之间的同 story 重复”视为已经有实测支持的正式候选路径；verify 预算优化虽然会保留接口，但当前还没有实测收益。
- 不把 Tavily 改造成一个常驻 source；它仍然只是 post-fetch enrichment 层。

## 正式集成计划

当前建议按下面顺序实施，而不是一次性把所有实验细节塞进 `main.py`：

### 第 1 步：抽出正式模块

- 新增 `utils/news_enrichment.py`
- 复用实验里已经稳定的能力：
  - 本地 prefilter
  - exact verify
  - priority refill
  - secondary refill
  - optional official fallback
  - refill 阶段的 near-duplicate / story-cluster 拦截
- 统一返回两部分：
  - `articles`：最终进入保存与摘要的正式文章集合
  - `report`：本次增强的诊断信息

### 第 2 步：接入配置与开关

- 在 `config.py` 中新增 enrichment 配置结构。
- `config.yaml` 中新增 `enrichment.enabled` 与相关预算参数。
- 主流程需要同时支持：
  - 配置默认关闭
  - 显式开启
  - 显式关闭

当前更推荐：

- 配置层保留默认值与日常开关
- CLI 层再提供一次性 override，方便当天测试而不改变长期默认行为

### 第 3 步：接入 main 正式链路

主流程目标调整为：

```text
fetch_all
-> dedupe
-> enrich_articles_with_tavily (optional)
-> save_json
-> summarize
-> build
```

需要同步覆盖：

- `run`：全流程正式运行
- `fetch`：只抓取但仍保存 enrichment 结果，便于后续单独 summarize
- `summarize`：继续只消费已有 JSON，不重复调用 Tavily

### 第 4 步：补测试与当天验证

- 先跑单元测试与最小命令级检查
- 再触发一次 `2026-04-01` 的当天真实任务
- 当天真实任务至少要记录：
  - 是否真的启用了 enrichment
  - verify / refill / fallback 实际调用数
  - final article count
  - 是否命中 cluster 拦截
  - 是否发生安全降级

### 第 5 步：回写文档结论

当天真实任务完成后，再把本节从“计划”更新为“已实施现状”，但仍要区分：

- 已正式接入的行为
- 仍仅属于 experimental 的推断

当前相关产物：

- 基准脚本：`scripts/benchmark_tavily.py`
- 白名单研究脚本：`scripts/benchmark_tavily_whitelist.py`
- dry run / replay harness：`scripts/experiment_news_enrichment.py`
- 基准结果：`data/benchmarks/tavily-baseline-2026-04-01.json`
- 基准结论：`data/benchmarks/tavily-baseline-2026-04-01.md`
- 白名单结果：`data/benchmarks/tavily-whitelist-2026-04-01.json`
- 白名单结论：`data/benchmarks/tavily-whitelist-2026-04-01.md`
- 主白名单 / 官方 fallback 保留性复测：`data/benchmarks/tavily-whitelist-retention-2026-04-01-round12.json`
- 主白名单 / 官方 fallback 保留性复测结论：`data/benchmarks/tavily-whitelist-retention-2026-04-01-round12.md`
- deferred 池挑战赛结果：`data/benchmarks/tavily-whitelist-deferred-2026-04-01-round3.json`
- deferred 池挑战赛结论：`data/benchmarks/tavily-whitelist-deferred-2026-04-01-round3.md`
- dry run / replay harness 结果：`data/benchmarks/tavily-enrichment-dryrun-2026-04-01.json`
- dry run / replay harness 结论：`data/benchmarks/tavily-enrichment-dryrun-2026-04-01.md`
- 分层 trusted domains 草案：`handbook/guides/history/tavily-trusted-domains-draft.md`

## 最新 experimental 结论概览

### 本次实测已确认的结论

- `thenextweb.com` 与 `venturebeat.com` 经过保留性复测后，仍满足默认 `refill_media_whitelist` 的保留条件。
- `openai.com` 与 `anthropic.com` 经过保留性复测后，仍适合作为 `official_fallback_domains`，但不应提升到主 refill 白名单。
- `reuters.com` 与 `arstechnica.com` 在 deferred 池挑战赛里都满足“metadata 稳定 + 低重合”，但新增有效候选仍低于主白名单下界，因此继续留在 deferred。
- `www.theverge.com` 虽然在挑战赛里出现了少量可用候选，但 `published_date` 仍明显不稳定，继续排除。

### 基于当前实测的推断建议

- 当前 experimental 草案足以继续保留，不需要扩展默认名单。
- 当前也不需要收缩已保留的 4 个域名。
- 当前更适合继续在“实验性 dry run / replay harness”里验证 cluster 与 staged refill，而不是直接改正式运行链路。

### 首轮 dry run / replay harness 新发现

以下都是 `2026-04-01` 新增 replay harness 的实验性观察，不代表正式链路已经采用。

本次最小完整 dry run 使用：

- 历史日期：`2026-03-24`、`2026-03-25`
- verify 默认：`basic`
- fuzzy second pass：关闭
- media refill：仅 `thenextweb.com`、`venturebeat.com`
- official fallback：默认关闭

本次实测结果：

- `2026-03-24`：本地 prefilter 后从 `15` 条降到 `4` 条 verify 候选；exact verify 接受 `2` 条，media refill 新增 `3` 条，最终 `5` 条，停止原因为 `official_fallback_disabled`
- `2026-03-25`：本地 prefilter 后从 `14` 条降到 `9` 条 verify 候选；exact verify 因 `max_verify_calls = 6` 实际调用 `6` 次、接受 `4` 条，media refill 新增 `5` 条，最终 `9` 条，停止原因为 `budget_exhausted_after_media_refill`
- 手动开启 official fallback 的单日验证已跑通，默认关闭时不会触发；开启后能单独统计 `fallback_calls` 与 `official_refilled_count`

当前更值得记录的推断：

- 现有 replay harness 已足以继续做 benchmark / replay，不需要先动 `main.py` 或 `summarizer.py`
- 当前预算下，default path 有机会接近 `min_articles = 10`，但还不能证明“稳定达到 10 条”
- refill 结果里已经出现“主题近似重复但 URL 不同”的 case，说明正式集成前仍需补一层更强的 near-duplicate / story-cluster 规则
- official fallback 仍更适合作为显式开关，而不是默认路径；当前证据还不足以证明它应进入默认 dry run

### 第二轮 dry run / replay harness 增量发现

以下同样都是 `2026-04-01` 的实验性 replay 观察，不代表正式链路已经采用。

本轮增量只在 experiment harness 内推进：

- 先加入 near-duplicate / story-cluster 诊断与 refill 合并拦截
- 再把 refill 拆成 `priority whitelist` 与 `secondary refill` 两段
- `priority_refill_media_whitelist`：`thenextweb.com`、`venturebeat.com`
- `secondary_refill_candidate_domains`：`reuters.com`、`arstechnica.com`
- official fallback：仍默认关闭

本次实测结果：

- `2026-03-24`：prefilter 阶段 `cluster_count = 0`、`verify_saved_calls = 0`；refill 合并阶段拦下 `1` 条同 story 结果，`story_cluster_rejected_count = 1`；priority refill 新增 `1` 条，secondary refill 新增 `2` 条，最终 `5` 条，总调用数 `6`
- `2026-03-25`：prefilter 阶段同样 `cluster_count = 0`、`verify_saved_calls = 0`；refill 合并阶段拦下 `1` 条同 story 结果；priority refill 新增 `4` 条，但由于总预算已到 `7` 次，没有进入 secondary refill，最终 `8` 条

当前更值得记录的推断：

- cluster 规则已经在 refill 合并阶段展现出价值，至少能拦住“同 story、不同 URL”的补全结果
- 现有 `2026-03-20` 到 `2026-03-25` 历史窗口里，prefilter 候选还没有形成可用 cluster，因此“verify 预算节省”目前只有实现，没有实测收益
- secondary refill 只有在 verify 阶段留下预算余量时才有边际价值；在当前默认预算下，`2026-03-25` 这类 `verify_calls = 6` 的日期不会触发 secondary
- 当前证据足以支持继续保留 secondary 作为 experimental path，但还不足以支持把它写成正式 implementation 草案默认路径

## Phase 0 基准测试结论

### 已完成的最小测试矩阵

Phase 0 已实际跑过以下场景：

| 场景 | 查询方式 | depth | max_results | 实测用途 |
|------|----------|-------|-------------|----------|
| 精确校验 | `\"{title}\"` | `basic` | 3 | 验证低成本 exact verify 是否够用 |
| 精确校验 | `\"{title}\"` | `advanced` | 3 | 对比 `basic` 是否有明显收益 |
| 模糊校验 | `\"{title}\" AI` | `advanced` | 5 | 验证是否值得保留二次确认 |
| 主题补全 | AI 主题 query | `advanced` | 8 | 评估 refill 质量与重复率 |

历史回放时，`within_24h` 不是按当前日期硬算，而是按样本所属日报日期加项目文档里的调度时间 `21:19 Asia/Shanghai` 作为参考点计算。

### 核心实测结果

- `verify_exact` + `basic` + `max_results=3`：`3/4` 命中，平均延迟约 `546 ms`，`published_date` 可用率 `100%`
- `verify_exact` + `advanced` + `max_results=3`：同样 `3/4` 命中，没有比 `basic` 更高的命中收益
- `verify_fuzzy` + `advanced` + `max_results=5`：`2/4` 命中，`0` 个 rescue case
- 英文 refill query + `advanced` + `max_results=8`：新增有效新闻 `4` 条，重复 `0`
- 中文泛 AI refill query + `advanced` + `max_results=8`：新增有效新闻 `0` 条

### 当前可落地结论

- `published_date` 在当前基准里足够稳定，可作为严格 24 小时判定依据
- 校验阶段默认应该用 `basic`
- 默认不保留模糊二次确认
- 聚合型标题，如 `AI日报...`，不适合直接进入 Tavily article-level verify
- refill 阶段应优先使用英文 AI 主题 query；中文泛 query 暂不作为默认路径

## 白名单研究结论

### 研究目标

白名单研究不是为了找“名气最大的网站”，而是为了找到在本项目 refill 场景下更能稳定提供：

- `24h` 内新闻
- AI 主题相关标题
- 与现有日报低重复
- `published_date` 元数据稳定

的域名集合。

### 当前建议

当前建议把白名单拆成两层，而不是继续只维护一个混合的 `trusted_domains`：

- `refill_media_whitelist`
  - `thenextweb.com`
  - `venturebeat.com`
- `official_fallback_domains`
  - `openai.com`
  - `anthropic.com`

当前建议暂缓或排除的域名：

- `techcrunch.com`
- `news.aibase.com`
- `www.theverge.com`
- `reuters.com`
- `blog.google`
- `arstechnica.com`

其中当前更细的 experimental 解释是：

- `techcrunch.com`：高重合对照组，不进入默认主白名单
- `reuters.com`、`arstechnica.com`：deferred 候选，继续观察但暂不升级
- `news.aibase.com`、`www.theverge.com`、`blog.google`：当前更接近 excluded

### 选择理由

- `thenextweb.com`：非重合媒体里补全价值最高，且 round 1 保留性复测后仍保持 `published_date` 稳定、重复低、持续有新增
- `venturebeat.com`：结果数量不大，但 AI 相关性高、重复低，且在 round 1 复测后仍保持主白名单下界画像
- `techcrunch.com`：虽然结果质量高，但与现有抓取源重合度太高，round 1 复测也没有推翻“高重合对照组”的结论
- `news.aibase.com`：更像聚合摘要源，不适合作为严格 article-level verify / refill 白名单
- `www.theverge.com`：在首轮与 round 3 挑战赛里都表现出 `published_date` 不稳定，现阶段不宜纳入默认白名单
- `reuters.com` / `arstechnica.com`：metadata 稳定、重复低，但在 round 3 挑战赛里新增有效候选仍低于当前主白名单下界，更适合继续放在 deferred
- `openai.com` / `anthropic.com`：适合作为官方公告补充源，但不建议与编辑型 refill 主白名单混用；其中 `openai.com` 的 `published_date` 稳定性仍不足以支持升级

## 接入位置

现有主流程：

```text
fetch_all -> dedupe -> save_json -> summarize -> build
```

调整后主流程：

```text
fetch_all
-> dedupe
-> enrich_articles_with_tavily
-> save_json
-> summarize
-> build
```

推荐新增模块：`utils/news_enrichment.py`

选择这个位置的原因：

- `summarizer.py` 只负责消费新闻，不负责补数据。
- `sources/` 只负责单一新闻源抓取，不适合承载“跨源校验 + 条件补全”。
- `utils/` 已经承载 `dedupe.py` 这类后处理逻辑，语义最一致。

## 涉及文件

建议后续实现时修改这些文件：

- `utils/news_enrichment.py`：新增核心增强逻辑
- `main.py`：在 `dedupe` 之后调用增强层
- `config.py`：读取 Tavily 与增强策略配置
- `.env.example`：新增 Tavily 环境变量示例
- `requirements.txt`：加入 Tavily Python SDK
- `tests/test_news_enrichment.py`：补单元测试

## 设计原则

### 1. 不把 Tavily 设计成固定新闻源

Tavily 在这里的角色是“校验器 + 兜底补全器”，不是和 `aibase`、`techcrunch`、`theverge` 并列的常驻 source。

### 2. 先本地过滤，再调用 Tavily

先用本地已有字段做低成本过滤，再把 Tavily 预算留给真正需要验证或补全的新闻。

### 3. 多轮调用，但必须有预算上限

允许多次调用 Tavily 提升准确性，但每次运行都要有固定预算，避免单日任务因为搜索过多而变慢或变贵。

### 4. 对最终入选新闻执行严格 24 小时校验

“24 小时内”按运行时刻回看 24 小时计算，不按自然日粗略判断。

## 配置设计

### `.env`

```bash
TAVILY_API_KEY=
```

### `config.yaml`

建议新增：

```yaml
enrichment:
  enabled: true
  min_articles: 10
  strict_hours: 24
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

### 配置含义

这些值已经根据 Phase 0 benchmark 与白名单研究做过第一轮收敛，但仍应视为“experimental 初始建议值”，不是最终冻结配置。

- `min_articles`：目标条数，默认 10
- `strict_hours`：严格时效窗口，默认 24 小时
- `max_total_calls`：单次运行 Tavily 调用总上限
- `max_verify_calls`：用于校验现有新闻的调用预算
- `max_refill_rounds`：补全轮数上限
- `refill_max_results`：每轮 Tavily 最多返回多少条候选
- `verify_search_depth`：当前默认校验深度，建议先固定为 `basic`
- `enable_fuzzy_second_pass`：当前默认关闭；仅在后续实验中再决定是否恢复
- `trusted_domains.refill_media_whitelist`：默认补全时使用的编辑型媒体域名白名单
- `trusted_domains.official_fallback_domains`：当需要补官方公告时再启用的厂商域名
- `trusted_domains.excluded_or_deferred_domains`：当前不建议纳入默认白名单的域名，内部可再按 deferred / excluded 解读

## 当前白名单选择规则

白名单选择优先遵循以下规则：

1. 与现有抓取源高度重合的域名，不直接进入默认 refill 白名单。
   `techcrunch.com` 是当前最典型例子，虽然结果质量高，但与现有数据重叠太大。
2. `published_date` 不稳定的域名，不进入默认白名单。
   `www.theverge.com` 与 `blog.google` 在本轮 Tavily 域名限定结果里都存在这个问题。
3. 聚合摘要站点不作为默认 article-level verify / refill 白名单。
   `news.aibase.com` 更适合作为独立抓取源，而不是 Tavily 回填域名。
4. 官方博客类域名单独管理，不和编辑型媒体混用。
   `openai.com`、`anthropic.com` 适合作为 `official_fallback_domains`，而不是主 refill 白名单。
5. 新域名要进入主白名单，至少要同时满足：
   - `published_date` 基本稳定
   - AI 主题相关性高
   - 与现有日报低重复
   - 在小样本下能稳定产出新增有效新闻
6. 若某域名有一定价值但样本稀疏、主题范围不够稳定，优先放入 deferred / fallback，而不是直接纳入默认白名单。

## 模块职责

建议在 `utils/news_enrichment.py` 中提供一个主函数：

```python
def enrich_articles_with_tavily(
    articles: list[Article | dict],
    *,
    report_dt: datetime,
    min_articles: int,
    strict_hours: int = 24,
) -> list[Article]:
    ...
```

职责拆分如下：

- 规范化输入结构
- 对候选新闻做本地初筛
- 调用 Tavily 验证时效性
- 不足 10 条时执行多轮回填
- 合并结果并再次去重
- 返回可直接进入 `save_json` / `summarize` 的最终列表

## 详细流程

### 第 1 步：本地预筛

输入为 `dedupe` 后的新闻列表。

本地预筛规则：

- 优先保留已有 `priority` 高的新闻
- 尝试解析已有 `publish_time`
- 明确超过 24 小时的新闻直接淘汰
- `publish_time` 缺失或格式不可信的新闻标记为“待验证”

这一层只做低成本裁剪，不做最终确认。

### 第 2 步：Tavily 严格验证

对排序后的候选池执行 Tavily 校验，直到满足以下任一条件：

- 已确认新闻数达到 `min_articles`
- 候选池耗尽
- 校验调用数达到 `max_verify_calls`

推荐候选池大小：

```text
candidate_pool_size = max(min_articles * 2, 16)
```

这样可以避免对全部抓取结果逐条调用 Tavily。

基于当前实测，默认策略应为：

- 只对“单篇文章标题”执行 exact verify
- 聚合型标题默认不进入 verify 主路径
- 校验默认使用 `basic`
- 默认不进入模糊二次确认

### 第 3 步：不足 10 条时回填

如果严格校验后的有效新闻仍少于 10 条，则启动补全逻辑：

- 优先按主题对白名单媒体发起 1 轮 Tavily `news` 搜索
- 每轮抓回一批候选
- 对候选执行同样的 24 小时校验
- 与已有结果合并后再次去重

当前默认分层建议是：

- 第 1 层：只使用 `trusted_domains.refill_media_whitelist`
- 第 2 层：仅在明确需要官方公告补充时，才单独使用 `trusted_domains.official_fallback_domains`
- `excluded_or_deferred_domains` 不进入默认补全路径

若到达预算上限后仍不足 10 条，则允许当天结果少于 10 条，不应强行凑数。

## Tavily 调用策略

基于 Tavily 当前文档，可直接使用这些能力：

- `topic="news"`
- `time_range="day"` 或 `start_date` / `end_date`
- `max_results`
- `include_domains`
- `search_depth="basic"` / `advanced`
- 结果中的 `published_date`

### A. 现有新闻验证

第一轮建议使用低成本查询：

```python
client.search(
    query=f'"{title}"',
    topic="news",
    search_depth="basic",
    max_results=3,
    start_date=window_start,
    end_date=window_end,
)
```

判定通过条件建议同时满足：

- Tavily 返回结果存在可解析的 `published_date`
- `published_date` 在 `report_dt - 24h` 之后
- 命中结果与原文满足以下任一条件：
  - URL 规范化后完全一致
  - 同域名且标题相似度高于阈值

标题相似度可以先用标准库 `difflib.SequenceMatcher`，避免新增依赖。

### B. 模糊结果二次确认

Phase 0 实测中，模糊二次确认没有带来 rescue case，因此当前不建议默认开启。

如果后续要重新实验，可使用下面的模板，但只应作为 feature flag 控制下的可选路径：

```python
client.search(
    query=f'"{title}" AI',
    topic="news",
    search_depth="advanced",
    max_results=5,
    start_date=window_start,
    end_date=window_end,
)
```

只有当后续实验明确证明它能稳定补回 exact verify 漏检的高价值新闻时，才值得重新启用。

### C. 补全回填

补全不建议按单条 title 查，而建议按主题批量抓。

当前默认应优先使用英文 AI 主题 query。基准中有效的英语模板可从下面两类开始：

```text
OpenAI Anthropic AI model launch startup funding developer tools
Anthropic Claude Code AI agent developer tools
```

示例调用：

```python
client.search(
    query=query,
    topic="news",
    search_depth="advanced",
    max_results=refill_max_results,
    include_domains=trusted_domains["refill_media_whitelist"],
    start_date=window_start,
    end_date=window_end,
)
```

中文泛 AI query 在 Phase 0 基准中没有带来新增有效新闻，因此当前不作为默认 refill 模板。

### D. 官方 fallback 补充

当前 experimental 结论不建议把官方站点和编辑型媒体混在同一轮 refill 中。

如果后续需要验证“官方公告补充”路径，建议单独控制：

```python
client.search(
    query=query,
    topic="news",
    search_depth="advanced",
    max_results=refill_max_results,
    include_domains=trusted_domains["official_fallback_domains"],
    start_date=window_start,
    end_date=window_end,
)
```

是否进入这一步，应由显式条件触发，例如：

- 当前有效新闻仍不足目标条数
- 当前查询确实与厂商公告强相关
- 仍有剩余 Tavily 调用预算

回填结果需要转换成项目已有 `Article` 结构，建议映射为：

- `title` <- Tavily result `title`
- `link` <- Tavily result `url`
- `description` <- Tavily result `content`
- `publish_time` <- Tavily result `published_date`
- `priority` <- 1
- `source` <- `"tavily"`

## 结果判定逻辑

建议把验证结果分成三类：

- `verified`：Tavily 明确确认在 24 小时内，可进入最终列表
- `rejected`：确认超时或无法匹配，直接丢弃
- `uncertain`：没有足够证据，不进入最终 10 条

为了保证“严格验证”，`uncertain` 不应混入最终结果。

## 性能与调用预算

建议默认预算如下：

- 总调用数不超过 7 次
- 现有新闻验证不超过 6 次
- 模糊二次确认默认关闭
- 回填轮数先固定为 1 轮

建议的提前停止条件：

- 已验证条数 >= 10，立即停止
- 连续一轮补全没有新增有效新闻，立即停止
- 达到 `max_total_calls`，立即停止

目标是把新增搜索层控制在“单次运行增加可接受延迟”的范围内，而不是让抓取阶段退化成重型搜索任务。

## 主流程伪代码

```python
def run_pipeline():
    articles = fetch_all(...)
    articles = dedupe(articles)

    articles = enrich_articles_with_tavily(
        articles,
        report_dt=now_in_shanghai(),
        min_articles=10,
        strict_hours=24,
    )

    save_json(...)
    summarize(...)
    build_site()
```

```python
def enrich_articles_with_tavily(articles, report_dt, min_articles, strict_hours):
    pool = local_prefilter(articles, report_dt, strict_hours)
    verified = verify_existing_articles(pool, report_dt, strict_hours)

    if len(verified) < min_articles:
        verified = refill_missing_articles(
            verified,
            report_dt,
            strict_hours,
            target_count=min_articles,
        )

    verified = dedupe(verified)
    return sort_by_priority_and_time(verified)
```

## 输出与可观测性

推荐在 `data/YYYY-MM-DD.json` 中追加元信息，方便排查：

```json
{
  "date": "2026-04-01",
  "articles": [],
  "meta": {
    "raw_count": 18,
    "deduped_count": 14,
    "verified_count": 9,
    "refilled_count": 1,
    "tavily_calls": 7
  }
}
```

这样即使后续出现“为什么今天只有 8 条”之类的问题，也能快速定位是源不足、严格校验淘汰，还是 Tavily 搜索不足。

## 失败与降级策略

### Tavily Key 缺失

- 跳过增强层
- 打印 warning
- 保持现有抓取链路继续运行

### Tavily 请求失败

- 单次请求失败允许记录并继续下一步
- 不因为补全失败而阻断整条日报流水线

### 当天真实不足 10 条

如果严格 24 小时窗口内确实找不到 10 条高质量新闻：

- 允许最终结果少于 10 条
- 不要用旧闻强行补齐

## Prompt 同步调整

当前提示词要求“必须完整输出所有 10 条新闻”，这和严格 24 小时校验存在冲突。

建议把 `prompts/daily.md` 中的要求改成：

```text
优先输出 10 条；若严格校验后不足 10 条，则按实际可用条数输出。
```

这样补全失败时，模型不会为了凑够 10 条而重复或臆造内容。

## 测试建议

至少覆盖以下测试：

- 本地 `publish_time` 明显超时，直接被过滤
- Tavily 返回 24 小时内同 URL 结果，验证通过
- Tavily 返回同标题但超过 24 小时，验证失败
- 有效新闻不足 10 条时触发回填
- 回填结果与已有结果重复时可正确去重
- 达到调用预算后停止进一步搜索
- 无 `TAVILY_API_KEY` 时正常降级

## 下一步建议

在正式集成前，当前最合适的下一步已经不再是“新增 dry run harness”，因为这一步已完成。更符合当前技术现状的下一步应聚焦两个实验问题：

1. 为 replay harness 增加 `near-duplicate / story-cluster` 规则
2. 在 Tavily 补全阶段新增“优先白名单 + 次级综合补搜”的二次搜索逻辑

### A. 先补 near-duplicate / story-cluster 规则

当前 dry run 已经出现“主题近似重复但 URL 不同”的 refill 结果，这说明现有去重粒度仍不足以支撑更宽的补全域名池。

当前最合适的实验落点：

- 先只改 `scripts/experiment_news_enrichment.py`
- 不先改 `utils/dedupe.py`
- 不接入 `main.py` / `summarizer.py`

建议分两层做：

- `near_duplicate`
  - 处理标题高度相似、URL 不同但明显属于同一报道的情况
  - 先用 `normalize_title` + `SequenceMatcher` + URL/domain 规则实现
- `story_cluster`
  - 处理标题写法不同、但明显属于同一事件的情况
  - 先用低成本 token overlap / entity-like token 规则做启发式聚类，不引入 embedding 或 LLM 判重

建议优先插入的位置：

- 本地 prefilter 之后、exact verify 之前：
  先对已有候选聚类，只验证 cluster representative，减少 `max_verify_calls` 消耗
- 每轮 Tavily refill 结果合并之前：
  先对新候选与已接受集合做 cluster，避免同一事件被重复补入

建议最先验证的问题：

- cluster 后，`verify_calls` 是否能下降
- cluster 后，`final_count` 中“同一事件不同写法”的重复是否明显减少
- 当前 dry run 中出现的 Helion / OpenAI 等近似重复 case 是否能被稳定识别
- 规则是否会误杀真正独立的 AI 新闻

### B. 再做分层二次 Tavily 搜索

在 cluster 规则补上之前，不建议直接把默认 whitelist 一次性放宽，因为那更容易把事件重复放大。

更合适的实验结构是三层：

- `priority_refill_media_whitelist`
  - `thenextweb.com`
  - `venturebeat.com`
- `secondary_refill_candidate_domains`
  - `reuters.com`
  - `arstechnica.com`
- `official_fallback_domains`
  - `openai.com`
  - `anthropic.com`

当前仍不建议进入默认 secondary 层的域名：

- `techcrunch.com`
  原因是与现有 source mix 高重合，更适合作为对照组
- `www.theverge.com`
  原因是 `published_date` 仍不够稳定
- `news.aibase.com`
  原因是更接近聚合摘要源
- `blog.google`
  原因是当前 metadata 仍偏弱

建议的实验调用顺序：

```text
local_prefilter
-> local cluster / near-duplicate collapse
-> exact verify
-> priority refill
-> cluster against accepted set
-> secondary refill
-> cluster against accepted set
-> optional official fallback
```

这里的关键不是“默认搜更多域名”，而是“把补全分成主白名单和次级候选两轮”，从而回答：

- 次级补搜是否真的带来新的 story，而不是重复已有结果
- 当前预算下，二次搜索是否值得
- `official_fallback` 是否仍应保持显式开关

建议先保持 query 模板不变，只改变域名层级。这样实验结果更容易解释。

### C. 当前最值得回答的实验问题

- 在加入 cluster 后，`max_verify_calls = 6` 是否仍然过紧
- 在 `max_total_calls = 7` 下，是否还能容纳 `priority refill + secondary refill`
- `secondary_refill_candidate_domains` 带来的新增是否主要是新 story，而不是主题近似重复
- 当前默认路径是否仍然经常停在 `< 10` 条
- `official_fallback_domains` 是否只适合作为显式补救，而不应进入默认补搜路径

### D. 当前阶段的成功标准

- 仍然不接入 `main.py` / `summarizer.py`
- 仍然不修改正式 config 读取逻辑
- 只扩展实验脚本、实验报告、实验文档
- 能明确回答“cluster 是否必要”以及“secondary refill 是否有边际价值”

## 推荐落地顺序

1. 已完成：Tavily Phase 0 benchmark，收敛默认参数与预算
2. 已完成：`trusted_domains` 白名单专项研究，收敛主白名单与 fallback 域名
3. 已完成：新增实验性 dry run / replay harness，验证本地预筛 -> exact verify -> media refill -> optional official fallback
4. 下一步：先在 replay harness 中加入 `near-duplicate / story-cluster` 规则，验证是否能减少 verify 预算消耗与同事件重复
5. 在 cluster 稳定后，再加入 `priority_refill_media_whitelist + secondary_refill_candidate_domains` 的二次 Tavily 搜索
6. 先只扩展实验报告指标，确认 secondary refill 的边际价值，再决定是否继续保留或收缩次级域名池
7. 若 cluster + secondary refill 的结果稳定，再补 `utils/news_enrichment.py` 的 experimental 实现草案
8. 之后再决定是否进入 `main.py` 接入阶段
9. 接入前补测试与 `.env.example` / `requirements.txt` 同步
10. 最后再调整 `prompts/daily.md`

这个顺序可以先保证数据质量，再处理摘要侧的文案约束。
