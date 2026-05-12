# Tavily 验证迭代计划与执行记录

## 当前状态

本文记录 Tavily enrichment 的验证计划和最新执行结果。实现细节、配置说明和历史分析仍以
`handbook/guides/tavily-integration.md` 为准。

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
