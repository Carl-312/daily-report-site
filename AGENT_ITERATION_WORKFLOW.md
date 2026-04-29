# Agent Iteration Workflow

本文件面向在 `/home/carl/daily-report-site` 内工作的 agent。

目标不是一次性“大改”，而是用可回退、可验证、可复盘的方式，持续优化项目，尤其适用于 Tavily 接入、抓取稳定性、摘要质量、构建链路等多因素联动的问题。

## 1. 总原则

1. 先读上下文，再动代码。
2. 每次只解决一个明确问题，不把多个假设混在一次提交里。
3. 每一轮修改都必须留下可验证证据。
4. 优先做最小安全改动，避免为了“可能更好”破坏现有可运行路径。
5. 若发现上游抓取、Tavily、摘要、构建是多层问题，必须拆层定位，不允许直接归因。

## 2. 开始前检查

每次开始新一轮迭代前，先执行：

```bash
git status --short --branch
pytest -q tests
```

然后阅读与当前任务直接相关的文件。Tavily 相关任务至少检查：

```bash
sed -n '1,260p' config.py
sed -n '1,260p' main.py
sed -n '1,260p' utils/news_enrichment.py
sed -n '1,220p' tests/test_news_enrichment.py
```

若问题涉及历史结论，再读：

```bash
sed -n '1,260p' handbook/guides/tavily-news-enrichment.md
sed -n '1,220p' handbook/guides/tavily-trusted-domains-draft.md
```

## 3. 单轮迭代模板

每一轮都按下面顺序执行，不要跳步。

### Step 1: 定义本轮唯一目标

把目标收敛成一句话，格式固定：

```text
本轮只验证 / 修复：
<一个具体问题>
```

示例：

- 本轮只验证 Tavily live 请求超时是否与代理环境有关。
- 本轮只修复 enrichment 在 refill 超时时的降级语义。
- 本轮只补 coverage，验证缺失 API key 和 timeout 的行为是否稳定。

### Step 2: 建立假设

对问题给出 1 到 3 个可验证假设。

示例：

1. `session.trust_env = False` 导致请求绕过代理环境。
2. Tavily timeout 发生在 refill 阶段而不是 verify 阶段。
3. `stop_reason` 设计不足，掩盖了真实失败原因。

### Step 3: 先验证，不先改

优先用只读或只运行命令收集证据：

```bash
rg -n "trust_env|timeout|stop_reason|refill_calls|verify_calls" utils/news_enrichment.py
pytest -q tests/test_news_enrichment.py
python3 main.py fetch --enrichment on
```

如果是网络问题，先保留原始输出或 JSON 证据，再决定是否改代码。

### Step 4: 只做最小改动

改动要求：

1. 只改与当前假设直接相关的文件。
2. 不顺手重构无关逻辑。
3. 先保现有默认路径稳定，再增强实验路径。
4. 对高风险逻辑优先补测试，再扩行为。

### Step 5: 执行分层测试

每轮至少跑三层验证，按从快到慢的顺序：

#### A. 单元 / 小范围测试

```bash
pytest -q tests
```

如果只改 Tavily 模块，至少跑：

```bash
pytest -q tests/test_news_enrichment.py
```

#### B. 命令级验证

按本轮目标选择：

```bash
python3 main.py fetch --enrichment off
python3 main.py fetch --enrichment on
python3 main.py run --offline
```

说明：

- `--enrichment off` 用来验证主流程未被破坏。
- `--enrichment on` 用来验证 Tavily 接入路径。
- `--offline` 用来隔离摘要 API 干扰。

#### C. 产物检查

至少检查生成的 JSON 里这些字段：

- `enabled`
- `applied`
- `skip_reason`
- `error`
- `verify_calls`
- `preserved_error_count`
- `refill_calls`
- `fallback_calls`
- `total_calls`
- `final_count`
- `stop_reason`

建议命令：

```bash
sed -n '1,220p' data/$(date +%F).json
```

如果测试的是历史日期或固定样本，就直接查看对应 JSON。

## 4. Tavily 专项执行规则

当任务和 Tavily 有关时，必须额外遵守这些规则。

### 4.1 先区分三类问题

先判断故障属于哪一层：

1. 上游 source 抓取为空或超时
2. enrichment 逻辑判断错误
3. Tavily live 请求失败或结果质量不足

不要把 `0` 条最终文章直接归因给 Tavily。

### 4.2 优先保证 fail-open

如果 Tavily 出错，优先保证：

1. 主流程不中断
2. deduped 原始文章仍可继续保存和摘要
3. 诊断字段足够解释发生了什么
4. verify 阶段如果是 request error / timeout，原始文章必须保留，不能因为“未验证成功”直接丢掉

如果改动会影响 fail-open 行为，必须补测试。

### 4.3 区分“无结果”和“请求失败”

诊断里必须能区分：

1. Tavily 请求成功，但 `0` 结果
2. Tavily 请求超时 / 连接失败 / HTTP 错误
3. 有结果，但被 24 小时窗口、重复检测或 AI relevance 拒绝

当前正式诊断里，至少应能从这些字段看出差异：

- `verify_runs[*].request_outcome`
- `verify_runs[*].validation_outcome`
- `rejected_candidates[*].request_outcome`
- `rejected_candidates[*].validation_outcome`
- `preserved_error_count`
- `accepted_by_stage_preview.preserved_errors`

### 4.4 不轻易修改默认策略

以下参数属于策略层，不要因为一次异常就随意改默认值：

- `max_total_calls`
- `max_verify_calls`
- `max_refill_rounds`
- `refill_max_results`
- `verify_search_depth`
- `trusted_domains`

改这些值前，先补证据，最好同步更新：

- `handbook/guides/tavily-news-enrichment.md`
- `handbook/guides/tavily-trusted-domains-draft.md`

## 5. 推荐迭代顺序

当任务较大时，按下面顺序推进，而不是混着改。

### Phase 1: 观测性

先补清楚日志、JSON 诊断字段、错误语义、阶段统计。

完成标准：

- 能从 JSON 看出失败发生在哪一层
- 能区分 verify/refill/fallback 的行为

### Phase 2: 安全降级

再强化 timeout、request error、空结果时的降级逻辑。

完成标准：

- Tavily 失败时主流程仍完成
- 不会因为 enrichment 失败导致已有文章丢失

### Phase 3: 连接稳定性

再处理代理、环境变量、timeout、retry、session 策略。

完成标准：

- live 路径的失败原因可复现
- 必要时能通过配置或代码稳定请求链路

### Phase 4: 结果质量

最后再调 whitelist、query、去重、story cluster、strict hours。

完成标准：

- 改动能带来可测的质量收益
- 不只是“多出结果”，而是“多出可信结果”

## 6. 测试矩阵建议

每次改动后，按影响面选择下面矩阵。

### 最小矩阵

```bash
pytest -q tests
```

适用：

- 纯文档更新
- 纯小型条件分支修正

### Tavily 模块矩阵

```bash
pytest -q tests/test_news_enrichment.py
python3 main.py fetch --enrichment off
python3 main.py fetch --enrichment on
```

适用：

- `utils/news_enrichment.py`
- `config.py`
- `main.py` 中 enrichment 接线
- fail-open、timeout、request error、verify/refill 诊断语义修改

### 全链路矩阵

```bash
pytest -q tests
python3 main.py fetch --enrichment on
python3 main.py summarize --offline
python3 main.py build
```

适用：

- 抓取、保存、摘要、构建有联动修改

## 7. 文档回写要求

以下情况必须补文档：

1. 默认行为改变
2. 配置项新增或语义变化
3. 失败模式判断方式变化
4. benchmark 结论推动了正式策略变化

优先更新位置：

- `README.md`
- `handbook/guides/configuration.md`
- `handbook/guides/tavily-news-enrichment.md`
- `handbook/guides/troubleshooting.md`

## 8. Definition Of Done

一轮迭代只有同时满足下面条件才算完成：

1. 本轮目标只有一个，并且已经被验证或修复。
2. 相关测试已经执行，结果明确。
3. 若有行为变化，已在 JSON、命令输出或测试中体现。
4. 没有顺手引入未验证的大范围修改。
5. 需要时已同步更新文档。

## 9. 建议给下一个 Agent 的交接格式

完成一轮后，用下面格式留下交接摘要：

```text
Round Goal:
<本轮唯一目标>

What Changed:
<修改了什么>

Evidence:
<测试结果 / JSON 字段 / 关键命令输出摘要>

Open Risks:
<还没解决的风险>

Next Best Step:
<下一轮最值得做的一件事>
```

## 11. 已固化结论（2026-04-29）

截至 `2026-04-29`，下面这些结论已经有代码或测试证据支撑，下一轮不需要重复争论：

1. verify 阶段的 `request error / timeout` 不能等价于“文章无效”。
2. 当 verify 请求失败时，必须保留对应 deduped 原始文章，确保 fail-open。
3. 正式实现已经固化 fail-open 诊断字段：
   - `preserved_error_count`
   - `accepted_by_stage_preview.preserved_errors`
4. 正式实现已经把 Tavily 诊断拆成两层：
   - transport 层：`request_outcome`
   - content/validation 层：`validation_outcome`
5. `rejection_reason` 现在只应表达内容拒绝语义，不应再承载 timeout、connection error、HTTP error。
6. 受控复现已经确认：当 `search_tavily()` 抛 `requests.Timeout` 时，`final_count` 仍可保持原始文章数量，不会被清空。
7. `requests` 的 live 会继承环境代理；把 `session.trust_env` 设为 `False` 会让 Tavily session 绕过 `HTTP_PROXY` / `HTTPS_PROXY` / `ALL_PROXY` / `NO_PROXY`。
8. 正式配置已经新增 `enrichment.trust_env`，当前默认值是 `true`，下一轮不应再把它当作未验证假设。

## 12. 下一轮推荐唯一目标

如果下一轮继续处理 Tavily，优先把目标定成：

```text
本轮只验证 / 修复：
Tavily live 请求在真实网络下的失败模式是否还需要 retry / timeout / stop_reason 进一步细化。
```

推荐假设只保留这 3 个：

1. 目前 transport / validation 已拆层，但顶层 `stop_reason` 仍不足以表达“流程为什么停”。
2. verify、priority refill、secondary refill、official fallback 可能需要不同 timeout 或 retry 策略。
3. 当前主要风险已经从“语义混层”转移到“真实 live 网络下的连接稳定性”。

下一轮设计修改建议：

1. 先用 live 命令和 JSON 证据区分失败发生在 verify、priority refill、secondary refill 还是 official fallback。
2. 若 timeout 仍频繁出现，再决定是否补 retry、分阶段 timeout 或更细粒度的 stage-level `stop_reason`。
3. 只有在连接稳定性得到证据支持后，才继续调整 trusted domains、query 和预算参数。

命令级验证注意事项：

1. `python3 main.py fetch --enrichment off` 如果长时间无返回，先怀疑上游 source 抓取，不要误判为 Tavily 问题。
2. 若 live 网络不稳定，优先同时保留两类证据：
   - 受控 monkeypatch / fixture 测试
   - 真实 `fetch --enrichment on` 产出的 JSON 诊断字段
