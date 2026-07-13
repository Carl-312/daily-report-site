# Tavily 验证迭代计划与执行记录

配套 HTML 架构图：[`tavily-validation-iteration-plan.html`](tavily-validation-iteration-plan.html)

Gray Test 3 实施准备：[`tavily-gray-3-experiment-plan.md`](tavily-gray-3-experiment-plan.md)

## 当前状态

本文记录 Tavily enrichment 的验证计划和历史执行结果。实现细节、配置说明和当前状态仍以
[`handbook/operations/tavily.md`](../../operations/tavily.md) 为准。

截至 2026-05-12：

- Tavily 默认仍关闭：`config.yaml` 保持 `enrichment.enabled: false`。
- 生产 deploy 只在手动 `enable_tavily=true` 时传入 `secrets.TAVILY_API_KEY`；定时任务不默认开启 Tavily。
- `origin/main` 已包含 Tavily refill budget 修复、scorecard 工具、scorecard 测试、`2026-05-11` 规范化 scorecard artifact，以及 gray workflow 的自动 scorecard 生成步骤。
- 旧 Actions 灰度 run `25680995172` 是真实样本，commit 为 `0417775ecfffd202a59cb6ce61101e5b33b8730a`，runner 能拉取 source 并使用 masked `TAVILY_API_KEY`。
- `2026-05-11` 旧灰度 artifact 已被规范化为 `data/benchmarks/tavily-gray-2026-05-11-scorecard.json` 和 `.md`。
- `2026-05-11` regression fixture 已覆盖原预算冲突：旧行为是 verify 消耗 6 次、只剩 1 次 priority refill、未进入 secondary；当前行为预留 2 次 refill 预算并允许 secondary refill 执行。
- 2026-05-12 本地 live run 因 source timeout / DNS 问题得到 `input_count=0`，只能证明 Tavily secondary refill 能补 5 条，不能作为正式灰度质量证据。
- 2026-05-12 Actions Gray Test 2 已完成：run `25716080642` 跑在 commit `4cf4ce981a87f92eb7717a0575943f904cf1e505`，artifact 为 `tavily-gray-2026-05-12-25716080642`。
- Gray Test 2 已产生 workflow 自动生成的 `scorecard.json` 和 `scorecard.md`，本地规范化副本和人工判断已保存到 `data/benchmarks/tavily-gray-2026-05-12-*`。
- 2026-05-11 至 2026-05-16 的 7 次灰度 artifact 显示：Tavily 请求基本成功，但 `final_count` 多数停在 5-9，主要限制从“是否进入 secondary refill”转为“refill 候选质量和 24h 边界效率”。

## 当前结论

当前提交已经足够替代原始 `2026-05-11` 灰度分析，适合作为预算冲突修复、scorecard 规范化和 Actions 灰度链路的证据。

Gray Test 2 的主要结论：

- source 正常返回输入：`input_count=14`，source 分布为 `{"techcrunch": 14}`。
- workflow 自动生成并上传了 `scorecard.json` 和 `scorecard.md`。
- 预算预留生效：`reserved_refill_calls=2`，`verify_budget=5`，`total_calls=7`。
- secondary refill 已进入并接受 `5` 条候选，修复了旧 run 中 priority refill 后无预算进入 secondary 的问题。
- 最终仍只有 `final_count=8`，低于 `min_articles=10`。
- scorecard 诊断的主限制因素是 `budget_exhausted`，贡献因素包含 `published_date_missing`。
- priority refill 返回 `8` 条但接受 `0` 条，`published_date_missing_rate=1.0`。

因此推荐决策是：继续保持 Tavily 默认关闭。Gray Test 2 证明预算修复和 scorecard workflow 有效，但不能证明 Tavily 已适合默认开启，也不能证明扩大预算或 official fallback 可以直接进入默认路径。

Gray Test 3 用一个最多 3 项的小实验覆盖 Gray Test 2 之后暴露的问题，只在隔离灰度 workflow 中临时覆盖配置，不修改 `config.yaml` 的生产默认值：

1. `priority_refill_media_whitelist` 改为 `reuters.com`、`arstechnica.com`、`techcrunch.com`，把 `thenextweb.com`、`venturebeat.com` 降到 secondary。预期减少 priority 阶段的 `missing_published_date`，提高首轮 refill yield。
2. `strict_hours` 从 24 临时放宽到 30。预期减少北京时间晚间执行时对前一日 UTC 下午新闻的边界误杀。
3. `refill_max_results` 从 8 临时提高到 12。Tavily 当前 Search API 允许 `max_results` 到 20；本轮只小幅提高单次结果深度，不增加默认启用范围。

验收口径：

- `enrichment.enabled` 和 `enable_official_fallback` 仍保持 false 的默认语义；gray workflow 仍只通过 `--enrichment on` 显式打开 Tavily。
- priority + secondary 的 `accepted_count / result_count` 目标达到或接近 50%。
- `final_count` 中位数较 Gray Test 2 之后的 5-9 区间上移，且不能以大量非 AI 或明显过期候选作为代价。
- artifact 必须能看到 `gray-experiment-overrides.json` 和 `gray-config-diff.patch`，说明本轮只是灰度覆盖，不是生产默认配置变更。

详细执行步骤、artifact 检查命令、验收矩阵和回滚方式见 [`tavily-gray-3-experiment-plan.md`](tavily-gray-3-experiment-plan.md)。

## 已执行：Gray Test 3

### Gray Test 3 Run - 2026-05-17

- run id: `25986770588`
- commit: `52b89a3a4f82bc18eb67f752a5881ff4e693d597`
- artifact: `tavily-gray-2026-05-17-25986770588`
- artifact local check path: `/tmp/daily-report-tavily-gray-3.1w3Vid/tavily-gray-2026-05-17-25986770588/gray/tavily/2026-05-17/`
- override file present: yes, `logs/gray-experiment-overrides.json`
- config diff present: yes, `logs/gray-config-diff.patch`
- input_count: `7`
- verify: `5` calls / `5` accepted / `0` rejected / `2` skipped due budget
- priority refill: `12` result_count / `1` accepted_count / `0` missing_date / `1` outside_window / `7` non_ai
- secondary refill: `1` result_count / `0` accepted_count / `1` missing_date / `0` outside_window / `0` non_ai
- final_count / min_articles: `6 / 10`
- stop_reason: `budget_exhausted_after_secondary_refill`
- decision: FAIL
- notes: Gray Test 3 覆盖参数已生效：`strict_hours=30`、`refill_max_results=12`、priority 域名为 `reuters.com`、`arstechnica.com`、`techcrunch.com`，secondary 域名为 `thenextweb.com`、`venturebeat.com`，`enable_official_fallback=false`。但 priority + secondary refill 只接受 `1/13`，accepted/result 约 `0.077`，低于失败阈值；`final_count=6` 也低于失败阈值。priority 的 missing date 问题改善为 `0/12`，但 duplicate、near duplicate 和 non-AI 拒绝仍高；secondary 仅返回 1 条且缺少 published date。本轮不能支持默认开启 Tavily。

## 已执行：Gray Test 2

### 执行命令

本轮执行前先把本地 main rebase 到远端日报提交 `dce18d4` 之上，再推送到远端：

```bash
git push origin main
```

然后触发隔离灰度 workflow 并按 run id watch：

```bash
gh workflow run tavily-gray.yml --ref main
gh run list --workflow tavily-gray.yml --limit 1
gh run watch 25716080642 --exit-status
```

注意：`gh run watch --workflow tavily-gray.yml` 不是当前 GitHub CLI 支持的用法；`gh run watch` 应传入 run id。

### 已记录

- GitHub Actions run id：`25716080642`。
- commit SHA：`4cf4ce981a87f92eb7717a0575943f904cf1e505`。
- artifact 名称：`tavily-gray-2026-05-12-25716080642`。
- artifact 内部路径：`gray/tavily/2026-05-12/`。
- `scorecard.json` 和 `scorecard.md` 由 workflow 自动生成。
- 命令：`python3 main.py run --offline --enrichment on`。
- 评估文件：
  - `data/benchmarks/tavily-gray-2026-05-12-scorecard.json`
  - `data/benchmarks/tavily-gray-2026-05-12-scorecard.md`
  - `data/benchmarks/tavily-gray-2026-05-12-evaluation.md`

### 通过标准结果

- `report_json_present=true`。
- `report_markdown_present=true`。
- `enrichment.applied=true`。
- `input_count=14`，不是 source failure 样本。
- artifact 内存在 `scorecard.json` 和 `scorecard.md`。
- scorecard 能解释 `final_count` 的主限制因素。
- `final_count < min_articles` 的主因被归类为预算耗尽，并记录了 `published_date` 缺失贡献因素。
- 不得把单次 `final_count` 达标解释为默认开启 Tavily 的依据。

## 验证原则

每次 Tavily 策略迭代都必须同时满足三类证据：

1. 确定性回归：单元测试和 fixture 不调用 live Tavily，能复现预算、refill、fail-open、JSON 保存和 summary 输入链路。
2. 可解释 artifact：scorecard 不依赖日志全文即可解释输入质量、阶段结果、预算使用、输出数量和失败原因。
3. 生产灰度观察：Actions live run 能证明当前 runner/source/Tavily 组合下的真实行为，但单次结果只作为样本，不作为默认启用依据。

每次策略或 workflow 改动至少运行：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. pytest -q -p no:cacheprovider
ruff check .
ruff format --check .
git diff --check
```

## 后续实验顺序

Gray Test 2 已完成。后续如继续策略实验，推荐顺序：

1. 优先研究 priority refill 的 `published_date` 缺失问题，确认是 Tavily media domain 返回质量、query、topic/time window 还是解析策略导致。
2. 如果 priority refill 仍长期不可用，再比较调整 query、替换 priority domain、提高预算或启用 official fallback 的灰度收益。
3. 如果主要限制是候选质量，优先调整 domain 分层和标题相关性规则。
4. 如果主要限制是网络失败，先修 source timeout / runner 网络问题，不评估 Tavily 质量。
5. 如果连续多轮显示稳定收益，再考虑扩大调用预算或实验 official fallback；这些仍只能作为灰度配置。

## 不做事项

- 不提交 `.env`。
- 不直接提交 `data/2026-05-12.json` 或 `content/2026-05-12.md`，除非确认它们是有效正式产物。
- 不把 Tavily 改成常驻 source。
- 不在单元测试中真实调用 Tavily。
- 不用扩大 domain 白名单替代质量评估。
- 不把 `published_date` 缺失的候选静默当作有效 24 小时新闻。
- 不因为单次 live run 的 `final_count` 变高就建议默认开启 Tavily。
