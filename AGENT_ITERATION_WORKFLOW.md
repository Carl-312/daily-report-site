# Agent Iteration Workflow

本文件面向在 `/home/carl/daily-report-site` 内工作的 agent。

从本版开始，项目迭代主线不再是“泛化地优化日报流水线”，而是收敛为一个更明确的目标：

> 持续设计、验证、加固一套以 Tavily API 为核心的新闻验证与补量架构，确保进入日报正式产物的新闻具备可解释的时效性、可信度与降级语义。

这意味着：

1. `source` 抓取层仍然重要，但默认视为上游输入层，不再作为当前阶段的主要创新焦点。
2. 重点工作应放在 `utils/news_enrichment.py` 及其配置、诊断、测试、回放样本、GitHub Actions 接线策略。
3. 除非有明确证据表明上游抓取破坏了 Tavily 设计判断，否则不要把大量精力投入本地 `source` 复刻或重构。
4. 任何关于“是否应该继续折腾本地 source”的讨论，都必须回到一个判断标准：它能否直接提升 Tavily 验证架构的确定性。

## 1. 当前阶段唯一主线

当前阶段的唯一主线固定为：

```text
继续设计和优化用 Tavily API 来验证新闻的架构。
```

这里的“验证新闻”至少包括四层含义：

1. 验证候选新闻是否真的存在。
2. 验证候选新闻是否处于目标时间窗口内。
3. 验证候选新闻是否与 AI 日报主题真正相关。
4. 当上游 source 不足时，用 Tavily 做受控补量，而不是无约束替代 source。

任何新任务都必须先判断它属于下面哪一类：

- `verification architecture`：验证链路、判定逻辑、错误语义、诊断结构。
- `refill strategy`：trusted domains、query、budget、去重、story cluster。
- `operationalization`：配置、CLI、GitHub Actions、样本回放、可观测性。
- `upstream source issue`：source 抓取为空、超时、结构变化。

若任务不直接服务前三类，就默认不是当前优先事项。

## 2. 架构定位

当前正式架构定位必须固定，避免任务漂移。

### 2.1 Tavily 不是常驻 source

Tavily 在本项目中的职责不是替代 `sources/` 目录下的抓取器，而是一个 `post-fetch enrichment layer`。

正式顺序保持为：

```text
fetch_all
-> dedupe
-> enrich_articles_with_tavily
-> save_json
-> summarize
-> build
```

因此：

1. 上游 source 抓到的文章优先视为候选真值输入。
2. Tavily 的第一职责是 verify，而不是 refill。
3. Refill 只在文章数不足、且有清晰预算和域名策略时启用。
4. 即便 source 全空，也只能把 Tavily 视为受控补量模式，而不是证明“source 不再重要”。

### 2.2 设计目标顺序

后续设计决策按以下顺序排序，不允许倒置：

1. 正确性
2. 可解释性
3. fail-open 安全降级
4. 预算可控
5. 结果数量

如果某项改动只是“能多抓几条”，但牺牲了时效验证或错误可解释性，应拒绝。

### 2.3 当前推荐调试介质优先级

默认调试优先级如下：

1. 历史样本 replay / 昨日 source 样本
2. 本地命令级 live 验证
3. GitHub Actions 手动触发验证
4. 每日定时 GitHub Actions 观察
5. 本地 source 深挖

解释：

- 历史样本最适合隔离 Tavily 判定问题。
- 本地 live 验证适合确认 API 行为与代理/超时问题。
- GitHub Actions 适合验证生产接线，不适合承担早期策略探索。
- 定时任务适合观测，不适合作为主要调试循环。
- 本地 source 深挖只有在怀疑 source 结构本身影响判断时才升优先级。

## 3. 本阶段不再默认投入的方向

除非本轮目标明确要求，否则不要优先做这些事：

1. 重构各个 `sources/*.py` 只是为了追求本地复现一致性。
2. 为了多拿结果而放松 24 小时时效约束。
3. 因单日异常就频繁改动 `trusted_domains` 默认名单。
4. 把 Tavily 结果直接当作未经验证的一手文章导入正式产物。
5. 让 GitHub Actions 成为唯一调试入口。
6. 把摘要质量问题误判成 Tavily 验证架构问题。

## 4. 每轮迭代的固定入口问题

每次开始新一轮工作前，必须先回答下面 4 个问题：

```text
1. 本轮是在调 verify、refill、还是接线？
2. 本轮证据来自历史样本、live 请求、还是 GitHub Actions？
3. 本轮要验证的是架构语义，还是某个策略参数？
4. 如果失败，主流程是否仍能保住已有文章并完成落盘？
```

如果这 4 个问题回答不清，不允许直接改代码。

## 5. 开始前检查

每次开始前先执行：

```bash
git status --short --branch
pytest -q tests/test_news_enrichment.py
```

只有在怀疑非 Tavily 模块被破坏时，再补：

```bash
pytest -q tests
```

然后最少阅读：

```bash
sed -n '1,260p' config.py
sed -n '1,260p' main.py
sed -n '1,360p' utils/news_enrichment.py
sed -n '1,260p' tests/test_news_enrichment.py
```

若涉及策略历史，再读：

```bash
sed -n '1,320p' handbook/guides/tavily-integration.md
```

若涉及昨天或历史样本调试，优先读对应 JSON，而不是先跑 live：

```bash
sed -n '1,260p' data/<sample-date>.json
```

## 6. 单轮迭代模板

每一轮都必须按下面结构记录和执行。

### Step 1: 收敛唯一目标

格式固定为：

```text
本轮只验证 / 修复：
<一个 Tavily 架构问题>
```

合法示例：

- 本轮只验证 verify 阶段的 request timeout 是否会误伤原始文章保留。
- 本轮只修复 refill 阶段对 `published_date = null` 结果的拒绝语义。
- 本轮只验证昨日 source 样本在当前 trusted domains 下的补量质量。
- 本轮只确认 GitHub Actions 是否正确注入 `TAVILY_API_KEY` 并显式启用 enrichment。

非法示例：

- 本轮顺便看一下 source、summary、build 哪个有问题。
- 本轮想把日报整体质量一起提上来。

### Step 2: 明确问题层级

先把问题归到一个层级：

1. `upstream_empty_or_timeout`
2. `verify_logic`
3. `refill_logic`
4. `diagnostics_and_observability`
5. `environment_or_network`
6. `production_wiring`

只有先分层，后面的证据和改动才有意义。

### Step 3: 建立 1 到 3 个假设

示例：

1. `verify_runs[*].request_outcome` 仍不足以区分 timeout 与空结果。
2. `priority_refill_media_whitelist` 当前 query 对英文厂商新闻过拟合，导致有效补量偏窄。
3. GitHub Actions 虽能跑主流程，但并未接入 `TAVILY_API_KEY`，因此不能用于判断 Tavily 生产表现。

### Step 4: 先选证据源，再验证

优先级固定如下：

#### A. 历史样本 / 昨日 source 样本

优先用于：

- 调 verify 规则
- 调 refill 规则
- 调去重 / story cluster
- 调 stop_reason 与 accepted preview 语义

推荐做法：

```bash
python3 main.py fetch --enrichment off
sed -n '1,260p' data/<sample-date>.json
```

或直接使用用户提供的历史 source 样本做离线调试。

#### B. 本地 live 验证

优先用于：

- 调代理
- 调 timeout
- 调 trust_env
- 调 Tavily 请求结构

推荐命令：

```bash
python3 main.py fetch --enrichment on
```

#### C. GitHub Actions 手动触发

只用于：

- 验证 secrets 是否注入
- 验证生产 runner 是否能跑通 enrichment
- 验证日志和产物归档

不用于：

- 早期 query 试错
- trusted domains 快速调参
- 单日策略优劣判断

### Step 5: 只做最小改动

改动要求：

1. 只改与当前假设直接相关的文件。
2. 默认先补测试，再扩行为。
3. 不为了文档整洁而顺手重构无关逻辑。
4. 不因单次结果差就改多个预算参数。
5. 如果改动影响 fail-open，必须同时补测试和 JSON 预期检查。

### Step 6: 分层验证

每轮至少跑以下 3 层验证。

#### A. 单测层

```bash
pytest -q tests/test_news_enrichment.py
```

#### B. 命令层

按目标选择其一或组合：

```bash
python3 main.py fetch --enrichment off
python3 main.py fetch --enrichment on
python3 main.py run --offline --enrichment on
```

说明：

- `--enrichment off` 用于确认主流程不被 Tavily 改坏。
- `--enrichment on` 用于确认 enrichment 路径。
- `run --offline` 用于隔离摘要模型干扰。

#### C. 产物层

至少检查：

- `enabled`
- `applied`
- `skip_reason`
- `error`
- `verify_calls`
- `refill_calls`
- `fallback_calls`
- `preserved_error_count`
- `final_count`
- `stop_reason`
- `verify_runs`
- `rejected_candidates`
- `accepted_by_stage_preview`

推荐命令：

```bash
sed -n '1,260p' data/<date>.json
```

## 7. Tavily 架构专项规则

### 7.1 永远先分清 verify 与 refill

所有 Tavily 讨论先回答：

```text
当前问题发生在 verify，还是 refill？
```

约束：

1. verify 负责“判断已有候选是否可信”。
2. refill 负责“在可信预算内补量”。
3. verify 做错会误伤 source 真值。
4. refill 做错会污染最终结果池。

### 7.2 fail-open 是硬约束

如果 Tavily 出错，必须优先满足：

1. 主流程不中断。
2. 原始 deduped 文章尽可能保留。
3. 请求错误不能伪装成“验证失败”。
4. JSON 中必须看得出错在哪里。

尤其是 verify 阶段：

- request timeout
- connection error
- HTTP error
- malformed response

这些都应优先走“保留并标注错误”的方向，而不是直接丢弃原始文章。

### 7.3 区分四种失败语义

诊断上必须至少区分：

1. `request_failed`
2. `request_succeeded_but_no_results`
3. `results_returned_but_failed_validation`
4. `budget_or_stage_limit_reached`

不要把这四种情况混成一个 `stop_reason` 或一个 `error` 字段。

### 7.4 trusted domains 属于策略层，不是热修层

以下内容视为策略层：

- `priority_refill_media_whitelist`
- `secondary_refill_candidate_domains`
- `official_fallback_domains`
- `priority_refill_query`
- `official_fallback_query`
- `max_total_calls`
- `max_verify_calls`
- `max_refill_rounds`
- `refill_max_results`
- `verify_search_depth`

策略层修改前必须满足：

1. 有至少一份样本证据。
2. 能明确说清改善的是哪类问题。
3. 更新相应文档，而不是只改配置。

### 7.5 source 为 0 条时的解释规则

若 `input_count == 0`，必须先写明：

```text
这是“上游 source 空输入下的 Tavily 受控补量场景”，不是“正常 verify 架构场景”。
```

此时重点检查：

1. refill 是否还能拿到可信结果。
2. stop_reason 是否解释清楚为什么未达 `min_articles`。
3. 当前结果是否足以支撑继续总结，或只适合落盘留痕。

不要把 source=0 时的表现直接外推为 verify 架构已经成熟。

## 8. 推荐研发路线图

后续迭代默认沿下面路线推进，不混做。

### Phase 1: 诊断契约稳定化

目标：先把“发生了什么”说清楚。

完成标准：

- JSON 可明确区分 verify / refill / fallback
- request outcome 与 validation outcome 语义稳定
- stop_reason 能直接反映停止条件

### Phase 2: verify 安全性强化

目标：避免误杀已有文章。

完成标准：

- request error 不会直接导致原始文章丢失
- verify 的保留 / 拒绝逻辑有单测覆盖
- preserved error 路径在 JSON 中可追踪

### Phase 3: refill 策略收敛

目标：让补量有边界、有证据。

完成标准：

- trusted domains 分层稳定
- query 与域名层级相匹配
- near-duplicate / story-cluster 拦截可解释

### Phase 4: 生产接线

目标：让 GitHub Actions 真实承载 Tavily 正式路径。

完成标准：

- Actions 显式注入 `TAVILY_API_KEY`
- 能显式执行 `--enrichment on` 或受配置控制
- 产物和日志足以复盘当天 Tavily 行为

### Phase 5: 默认开启评估

目标：决定是否让 Tavily 成为日常默认路径。

完成标准：

- 连续多天样本下行为稳定
- source 非空与 source 为空两类场景都可解释
- 失败时不会破坏日报基本可用性

在到达 Phase 5 前，不要因为一次成功就把 `enabled` 默认改成 `true`。

## 9. 决策规则

### 9.1 什么时候继续用历史样本调试

满足任一条件时，优先用历史样本：

1. 你在调判断语义而不是网络连通性。
2. 你要比较两个 trusted domains 策略。
3. 你要验证 stop_reason、accepted preview、rejected_candidates 的设计。
4. 用户已经提供昨天抓到的 source。

### 9.2 什么时候跑本地 live

满足任一条件时，优先跑本地 live：

1. 你在调 `trust_env`、timeout、proxy、session。
2. 你怀疑 Tavily API 返回结构变了。
3. 你要验证当前配置是否还能拿到实时结果。

### 9.3 什么时候值得上 GitHub Actions

只有满足下面条件时，才值得推 PR 或手动触发：

1. 本地语义已经基本稳定。
2. 你要验证生产环境 secrets / network / runner。
3. 你需要确认 Pages 主链路是否受 Tavily 接入影响。

如果只是想快速判断 query 好不好、域名好不好，不要先上 GitHub Actions。

### 9.4 什么时候才该回头折腾本地 source

只有满足下面条件时，才把 `source` 调到高优先级：

1. 多次证据显示上游 source 结构变动，导致 verify 输入质量失真。
2. GitHub Actions 和本地 source 行为出现稳定分叉。
3. Tavily 设计判断被 source 字段缺失直接阻塞。

否则，默认 source 不是当前主线。

## 10. 推荐测试矩阵

### 最小矩阵

适用：纯文档、纯诊断字段、小逻辑修复

```bash
pytest -q tests/test_news_enrichment.py
```

### Tavily 语义矩阵

适用：verify / refill / stop_reason / fail-open 逻辑改动

```bash
pytest -q tests/test_news_enrichment.py
python3 main.py fetch --enrichment off
python3 main.py fetch --enrichment on
```

### 生产接线矩阵

适用：GitHub Actions、secrets、默认开关、命令入口改动

```bash
pytest -q tests
python3 main.py run --offline --enrichment on
```

然后再做手动 `workflow_dispatch` 或 PR 验证。

## 11. 产物审查清单

每轮完成后，至少给出以下结论：

1. 本轮唯一目标是什么。
2. 本轮问题属于哪一层。
3. 证据来自历史样本、本地 live、还是 GitHub Actions。
4. 是否修改了 verify 语义、refill 策略、还是生产接线。
5. fail-open 是否仍成立。
6. 最终应继续推进哪一个下一步。

推荐用语：

```text
本轮只验证 / 修复：<问题>
证据层：<sample/live/actions>
结论：<一句话>
下一步：<一句话>
```

## 12. 当前默认行动建议

如果没有用户额外指定方向，agent 默认按下面顺序推进：

1. 优先索取并使用“昨天抓到的 source 样本”做 Tavily 调试。
2. 优先优化 `utils/news_enrichment.py` 的 verify / refill / diagnostics 架构。
3. 在本地验证语义稳定后，再考虑 GitHub Actions 接线。
4. 只有在证据要求下才回头调查本地 source。

当前默认判断是：

```text
最值得投入的工作，不是继续折腾本地 source，
而是把 Tavily 新闻验证架构做成可解释、可回放、可灰度上线的正式层。
```
