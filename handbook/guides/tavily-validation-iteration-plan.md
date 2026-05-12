# Tavily 验证迭代计划

## 当前状态

本文记录 Tavily enrichment 的下一轮验证计划。实现细节、配置说明和历史分析仍以
`handbook/guides/tavily-integration.md` 为准。

截至 2026-05-12：

- Tavily 默认仍关闭：`config.yaml` 保持 `enrichment.enabled: false`。
- 生产 deploy 只在手动 `enable_tavily=true` 时传入 `secrets.TAVILY_API_KEY`；定时任务不默认开启 Tavily。
- `origin/main` 目前还没有最新 6 个本地提交；远端 `tavily-gray.yml` 只能上传 summary，不会自动生成 scorecard。
- 本地 HEAD 已新增 `scripts/tavily_gray_scorecard.py`、scorecard 测试、`2026-05-11` scorecard artifact，以及 gray workflow 的自动 scorecard 生成步骤。
- 旧 Actions 灰度 run `25680995172` 是真实样本，commit 为 `0417775ecfffd202a59cb6ce61101e5b33b8730a`，runner 能拉取 source 并使用 masked `TAVILY_API_KEY`。
- `2026-05-11` 旧灰度 artifact 已被规范化为 `data/benchmarks/tavily-gray-2026-05-11-scorecard.json` 和 `.md`。
- `2026-05-11` regression fixture 已覆盖原预算冲突：旧行为是 verify 消耗 6 次、只剩 1 次 priority refill、未进入 secondary；当前行为预留 2 次 refill 预算并允许 secondary refill 执行。
- 2026-05-12 本地 live run 因 source timeout / DNS 问题得到 `input_count=0`，只能证明 Tavily secondary refill 能补 5 条，不能作为正式灰度质量证据。

## 当前结论

当前提交已经足够替代原始 `2026-05-11` 灰度分析，适合作为预算冲突修复和 scorecard 规范化的本地证据。

但它还不足以完成下一轮 Tavily live 质量判断，原因是：

- 远端 Actions 尚未包含本地 scorecard workflow 改动。
- 旧 run `25680995172` 跑的是 `0417775`，不是当前修复后的 HEAD。
- 本地 2026-05-12 产物受网络和 source 失败影响，不能代表正常灰度样本。

因此推荐决策是：先 push 当前本地 6 个提交，再用 GitHub Actions 新开一次 gray test 2。不要依赖本地 2026-05-12 产物，也不要因为单次 `final_count` 变高而默认开启 Tavily。

## 推荐下一步：Gray Test 2

### 触发方式

先把当前本地提交推到远端 main：

```bash
git push origin main
```

然后触发隔离灰度 workflow：

```bash
gh workflow run tavily-gray.yml --ref main
gh run list --workflow tavily-gray.yml --limit 1
gh run watch <run-id> --exit-status
```

如果不用 `gh`，可在 GitHub Actions 页面手动运行 `Tavily Gray Daily`。

### 必须记录

新一轮评估文档应记录：

- GitHub Actions run id。
- commit SHA，必须是包含 `5e004fc` 或其后续提交的 SHA。
- artifact 名称：`tavily-gray-YYYY-MM-DD-<run_id>`。
- artifact 内部路径：`gray/tavily/YYYY-MM-DD/`。
- `scorecard.json` 和 `scorecard.md` 是否由 workflow 自动生成。
- 命令：`python3 main.py run --offline --enrichment on`。
- `input_count`、source 分布和 source 失败情况。
- verify / priority refill / secondary refill 的 calls、accepted、rejected 和 request outcome。
- `reserved_refill_calls`、`verify_budget`、`total_calls`、是否进入 secondary。
- `final_count`、`refill_remaining_count`、`stop_reason` 和 scorecard diagnosis。
- 本轮不能证明什么。

建议文件命名：

```text
data/benchmarks/tavily-gray-YYYY-MM-DD-scorecard.json
data/benchmarks/tavily-gray-YYYY-MM-DD-scorecard.md
data/benchmarks/tavily-gray-YYYY-MM-DD-evaluation.md
```

其中 scorecard 可直接来自 artifact；evaluation 只写人工判断和后续决策。

### 通过标准

gray test 2 至少应满足：

- `report_json_present=true`。
- `report_markdown_present=true`。
- `enrichment.applied=true`。
- `input_count > 0`，否则只能归类为 source failure 样本。
- artifact 内存在 `scorecard.json` 和 `scorecard.md`。
- scorecard 能解释 `final_count` 的主限制因素。
- 如 `final_count < min_articles`，必须能区分预算耗尽、metadata 缺失、候选质量差、source 为空或网络失败。
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

完成 gray test 2 后再决定是否进入策略实验。推荐顺序：

1. 先判断新 scorecard 是否显示 source 正常、预算预留生效、secondary refill 有机会执行。
2. 如果主要限制是 `published_date` 缺失，优先研究 metadata 处理和 query 调整。
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
