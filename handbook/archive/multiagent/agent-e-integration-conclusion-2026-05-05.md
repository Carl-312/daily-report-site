# Agent E 集成结论与后续推进依据

记录时间：2026-05-05 15:42 CST

本文记录 Tavily multi-agent PR 在 Agent E 集成阶段的最终判断、验收结果、风险边界和后续推进依据。后续继续推进 Tavily 默认开启、GitHub Actions 灰度或诊断字段扩展时，以本文作为本轮集成状态快照。

## 集成结论

当前工作可以收敛成一个 PR。

本轮 PR 的核心结论：

1. Tavily 仍是 `post-fetch enrichment`，不是 `sources/` 下的新默认 source。
2. `config.yaml` 仍保持 `enrichment.enabled: false`，没有默认开启 Tavily。
3. 本地 CLI 已支持显式开关：
   - `--enrichment auto`
   - `--enrichment on`
   - `--enrichment off`
4. GitHub Actions 已增加手动灰度入口：
   - `enable_tavily=false` 时维持默认路径。
   - `enable_tavily=true` 时才注入 `TAVILY_API_KEY` 并追加 `--enrichment on`。
   - schedule 定时任务不会因为仓库存在 `TAVILY_API_KEY` secret 就默认开启 Tavily。
5. Tavily request error 不会伪装成普通验证失败；诊断字段能区分 `timeout`、`http_error`、`connection_error`、`request_error` 和 `unexpected_error`。
6. verify request error 会保留原始 deduped articles，维持 fail-open。
7. source 为 0 条时，结果只能来自受控 refill，不是 verify 成熟度证明，也不能用来证明 source 层可以废弃。

## 本轮唯一发布边界

本轮只发布“受控 Tavily enrichment 加固和手动灰度入口”。

明确包含：

- verify 支持 AI 相关性分层，避免把 AI 邻近新闻在 verify 前硬挡掉。
- refill 继续使用严格 AI 标题相关性门禁，避免低信号补量污染结果池。
- 新增或强化诊断字段，便于复盘 Tavily 是否执行、失败在哪个阶段、保留了哪些原始文章。
- GitHub Actions 只提供手动 `enable_tavily` 灰度入口。
- 文档补齐使用、诊断、PR 操作说明。

明确不包含：

- 不默认开启 `enrichment.enabled`。
- 不扩大 Tavily 默认调用预算。
- 不放宽 `strict_hours: 24`。
- 不把 Tavily 改成常驻 source。
- 不把单次 live 成功或失败写成稳定策略结论。
- 不把 generated 0 条日报产物作为 PR 价值证据。

## A-D 工作收敛摘要

### Agent A: Enrichment Logic

集成状态：已收敛。

主要落点：

- `utils/news_enrichment.py`
- verify 阶段从硬 AI 标题门禁变成分层候选：
  - `core_ai`
  - `ai_neighbor`
  - `generic_or_low_signal`
- verify 消费顺序为 `core_ai -> ai_neighbor -> generic_or_low_signal`。
- 聚合型标题仍在 verify 前硬拒绝。
- refill 仍用严格 `ai_title_relevant()` 门禁。
- request outcome 分类保留：
  - `success`
  - `timeout`
  - `http_error`
  - `connection_error`
  - `request_error`
  - `unexpected_error`

风险判断：

- verify 放宽会让低信号候选有机会进入预算队列，因此必须依靠 `prefilter_bucket_counts` 和 neighbor 诊断字段复盘收益。
- 不能因为某天结果不足就扩大预算或放宽 24 小时时间窗。

### Agent B: Test Contract

集成状态：已收敛。

主要落点：

- `tests/test_news_enrichment.py`

新增覆盖重点：

- enrichment disabled 时直通。
- missing `TAVILY_API_KEY` 安全降级。
- verify timeout 保留原始文章。
- `session.trust_env` 跟随配置。
- source 为 0 且 official fallback 关闭时的 stop reason 语义。
- verify 命中但超出 24 小时时拒绝。
- verify 命中但缺少 `published_date` 时拒绝。
- AI neighbor 候选进入低优先级 bucket。
- verify 顺序优先 `core_ai`，再 `ai_neighbor`，再 `generic_or_low_signal`。
- 聚合型标题不进入 Tavily verify。
- refill 继续保持严格 AI 标题相关性。

风险判断：

- 当前测试主要用 monkeypatch 模拟 Tavily，不依赖 live API。
- 这符合 PR 边界，因为 live Tavily 失败不应阻塞，只要 fail-open 和诊断成立。

### Agent C: Production Wiring

集成状态：已收敛。

主要落点：

- `.github/workflows/deploy.yml`
- `.env.example`

最终行为：

- `workflow_dispatch.inputs.enable_tavily` 默认 `false`。
- `ENABLE_TAVILY` 只来自手动输入。
- `TAVILY_API_KEY` 只在 `inputs.enable_tavily` 为 true 时注入。
- 手动开启且 key 缺失时打印 warning，并依赖 enrichment 层安全降级。
- `skip_generate=true` 只 build，不验证 Tavily。
- schedule 不追加 `--enrichment on`。

风险判断：

- Actions 静态 marker 已通过。
- 生产 runner 上的 `enable_tavily=true` 仍需手动实跑验证。

### Agent D: Docs Runbook

集成状态：已收敛，且用户提醒后已重新检查最新文档。

主要落点：

- `README.md`
- `CONTRIBUTING.md`
- `handbook/README.md`
- `handbook/deployment/github-actions.md`
- `handbook/guides/configuration.md`
- `handbook/guides/tavily-integration.md`
- `handbook/guides/troubleshooting.md`

已覆盖说明：

- Tavily 是 `post-fetch enrichment`，不是默认 source。
- 默认 `enrichment.enabled: false`。
- 本地显式启用：
  - `TAVILY_API_KEY=... python3 main.py fetch --enrichment on`
  - `TAVILY_API_KEY=... python3 main.py run --offline --enrichment on`
- 安全关闭：
  - `python3 main.py fetch --enrichment off`
  - `python3 main.py run --offline --enrichment off`
- GitHub Actions 手动灰度用法和限制。
- `data/YYYY-MM-DD.json` 顶层 `enrichment` 字段如何看。
- source 为 0 条时如何解读。
- Tavily 失败时的 fail-open 预期。
- 什么时候才考虑默认开启 Tavily。

风险判断：

- 主文档中已清理旧的“Actions 尚未接入 Tavily”状态。
- 历史归档文档仍保留旧语义是可接受的，因为它们明确是 history。

## 最终修改范围

本轮 PR 相关修改文件：

- `.env.example`
- `.github/workflows/deploy.yml`
- `README.md`
- `CONTRIBUTING.md`
- `config.py`
- `handbook/README.md`
- `handbook/deployment/github-actions.md`
- `handbook/guides/configuration.md`
- `handbook/guides/tavily-integration.md`
- `handbook/guides/troubleshooting.md`
- `scripts/benchmark_tavily.py`
- `scripts/benchmark_tavily_whitelist.py`
- `scripts/experiment_news_enrichment.py`
- `tests/test_news_enrichment.py`
- `utils/news_enrichment.py`
- `handbook/guides/mutiagent/agent-e-integration-conclusion-2026-05-05.md`

说明：

- `config.py` 和 `scripts/*` 的改动来自 `ruff format` 以及 benchmark 脚本 side-effect import 的 `F401` 标注，目的是让 CI 的 `ruff check .` 和 `ruff format --check .` 通过。
- `data/2026-05-05.json` 与 `content/2026-05-05.md` 是本地验收生成产物。它们记录了 source timeout 后 0 条输出，不建议作为 PR 价值证据提交。
- `.env` 不纳入 git 备份，不应提交任何 secret。

## 总验收记录

### 单测

命令：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. pytest -q -p no:cacheprovider tests/test_news_enrichment.py
```

结果：

```text
12 passed, 1 warning
```

warning：

- `config.py` 中 Pydantic V2 class-based `Config` deprecation。
- 与 Tavily 行为无直接关系。

### 全量 pytest

命令：

```bash
PYTHONPATH=. pytest
```

结果：

```text
16 passed, 1 warning
```

### Ruff lint

命令：

```bash
ruff check .
```

结果：

```text
All checks passed!
```

### Ruff format

命令：

```bash
ruff format --check .
```

结果：

```text
23 files already formatted
```

### Git diff whitespace

命令：

```bash
git diff --check
```

结果：通过，无输出。

### Actions 静态安全检查

命令：

```bash
python3 - <<'PY'
from pathlib import Path
workflow = Path('.github/workflows/deploy.yml').read_text(encoding='utf-8')
config = Path('config.yaml').read_text(encoding='utf-8')
assert 'enable_tavily' in workflow
assert 'TAVILY_API_KEY' in workflow
assert '--enrichment on' in workflow
assert 'enabled: false' in config
print('release safety markers found')
PY
```

结果：

```text
release safety markers found
```

### 文档术语检查

命令：

```bash
python3 - <<'PY'
from pathlib import Path
required = [
    'post-fetch enrichment',
    'enrichment.enabled: false',
    '--enrichment on',
    '--enrichment off',
    'TAVILY_API_KEY',
    'fail-open',
]
text = '\n'.join(p.read_text(encoding='utf-8') for p in Path('handbook').rglob('*.md'))
missing = [item for item in required if item not in text]
assert not missing, missing
print('doc terminology markers found')
PY
```

结果：

```text
doc terminology markers found
```

### 文档链接目标检查

命令：

```bash
python3 - <<'PY'
from pathlib import Path
for rel in [
    'handbook/guides/tavily-integration.md',
    'handbook/guides/configuration.md',
    'handbook/deployment/github-actions.md',
    'handbook/guides/mutiagent/README.md',
]:
    assert Path(rel).exists(), rel
print('expected handbook files exist')
PY
```

结果：

```text
expected handbook files exist
```

### 命令级验收：fetch 关闭 Tavily

命令：

```bash
PYTHONPATH=. python3 main.py fetch --enrichment off
```

结果：

- `aibase` timeout。
- `techcrunch` timeout。
- `theverge` timeout。
- Tavily enrichment disabled。
- `data/2026-05-05.json` 成功落盘。
- 最终文章数为 0。

关键诊断：

```text
Applied: False
Skip: disabled
Final articles: 0
```

### 命令级验收：offline run 关闭 Tavily

命令：

```bash
PYTHONPATH=. python3 main.py run --offline --enrichment off
```

结果：

- `aibase` timeout。
- `techcrunch` timeout。
- `theverge` timeout。
- Tavily enrichment disabled。
- JSON 成功保存。
- Markdown 成功保存。
- HTML 站点成功构建到 `dist/`。

关键诊断：

```text
Applied: False
Skip: disabled
Final articles: 0
```

生成 JSON 复核：

```text
date: 2026-05-05
article_count: 0
enabled: False
applied: False
skip_reason: disabled
stop_reason: disabled
input_count: 0
final_count: 0
verify_calls: 0
refill_calls: 0
fallback_calls: 0
```

## 补跑项目

### 命令级验收：offline run 开启 Tavily

命令：

```bash
PYTHONPATH=. python3 main.py run --offline --enrichment on
```

结果：

- `aibase` timeout。
- `techcrunch` timeout。
- `theverge` timeout。
- Tavily enrichment enabled。
- `data/2026-05-05.json` 成功保存。
- `content/2026-05-05.md` 成功保存。
- HTML 站点成功构建到 `dist/`。

关键诊断：

```text
Applied: True
Skip: -
Final articles: 4
verify=0
refill=2
fallback=0
total=2
```

生成 JSON 复核：

```text
date: 2026-05-05
article_count: 4
enabled: True
applied: True
skip_reason: None
stop_reason: below_min_articles_after_secondary_refill_official_fallback_disabled
input_count: 0
final_count: 4
verify_calls: 0
refill_calls: 2
fallback_calls: 0
total_calls: 2
preserved_error_count: 0
priority_refilled_count: 0
secondary_refilled_count: 4
priority_refill_runs request_outcome: success
secondary_refill_runs request_outcome: success
```

解读：

- 这证明本地显式 `--enrichment on` 路径在当前 `.env` 有 `TAVILY_API_KEY` 时可以执行 Tavily refill。
- 这不是默认开启证据，因为本轮 live 样本仍是 source 为 0 的受控补量场景。
- 这不是 verify 成熟度证据，因为本轮 `verify_calls=0`。
- 生成的 `data/2026-05-05.json` 和 `content/2026-05-05.md` 仍是本地验收产物，不建议作为 PR 内容提交。

## PR 风险

### P0: 不适合默认开启

原因：

- 上游 source 在本地验收中全部 timeout。
- 当 source 为 0 且 Tavily 未启用或 Tavily 失败时，最终结果可能为 0 条。
- 本地补跑 `--enrichment on` 虽然通过 refill 得到 4 条，但这是单次 source=0 样本，不能支撑默认开启。
- GitHub Actions 手动 Tavily 灰度入口尚未在生产 runner 上实跑。
- 还没有多日稳定样本证明默认路径可靠。

结论：

- 本 PR 不能把 `enrichment.enabled` 改成 true。

### P1: verify 放宽需要持续复盘

原因：

- `generic_or_low_signal` 也可能进入 verify 队列。
- 预算顺序可以降低风险，但不能替代多日样本验证。

后续应观察：

- `prefilter_bucket_counts`
- `neighbor_candidates_verified_count`
- `neighbor_candidates_outside_24h_count`
- `neighbor_candidates_no_match_count`
- `verify_skipped_due_budget`

### P1: production runner 仍需手动灰度

后续必须在 GitHub Actions 手动触发一次：

- `enable_tavily=true`
- `skip_generate=false`

如果没有 secret：

- 验证 warning 和 `missing_api_key` 安全降级。

如果有 secret：

- 验证 `--enrichment on` 被执行。
- 复盘 `data/YYYY-MM-DD.json` 的 `enrichment` 字段。

### P2: 生成产物不建议进入 PR

本地验收生成：

- `data/2026-05-05.json`
- `content/2026-05-05.md`

这两个文件反映的是本地 source timeout 后的验收产物；关闭 Tavily 时为 0 条，补跑 `--enrichment on` 后被刷新为 4 条 Tavily refill 结果。它们可作为本地验收痕迹，但不建议作为 PR 内容提交。

## 建议 PR 描述

```markdown
## Summary

- Adds controlled Tavily enrichment improvements for 24h AI/tech news fallback.
- Keeps Tavily disabled by default and available through explicit CLI / manual Actions paths.
- Preserves existing fetch, summary, and build behavior when Tavily is missing or failing.

## Safety

- `enrichment.enabled` remains false.
- Missing `TAVILY_API_KEY` falls back safely.
- Tavily request errors preserve original deduped articles where applicable.
- GitHub Actions schedule does not force Tavily on.

## Validation

- [x] `ruff check .`
- [x] `ruff format --check .`
- [x] `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. pytest -q -p no:cacheprovider tests/test_news_enrichment.py`
- [x] `PYTHONPATH=. pytest`
- [x] `python3 main.py fetch --enrichment off`
- [x] `python3 main.py run --offline --enrichment off`
- [x] Actions static release-safety marker check
- [x] Optional with key: `PYTHONPATH=. python3 main.py run --offline --enrichment on`

## Notes

- Tavily remains a post-fetch enrichment layer, not a replacement source.
- Source=0 runs are controlled refill scenarios, not proof that verify is mature.
- Local source requests timed out during final validation. The off-path produced 0 articles; the explicit Tavily on-path refilled 4 articles from a source=0 scenario, so generated 2026-05-05 artifacts should not be treated as quality evidence.
```

## 后续推进建议

### 下一步 1: GitHub Actions 手动灰度

目标：

- 验证生产 runner 是否正确注入 `TAVILY_API_KEY`。
- 验证 `enable_tavily=true` 是否实际追加 `--enrichment on`。
- 验证缺 key 时是否 fail-open。

验收：

- workflow 日志可见 Tavily 手动启用路径。
- JSON `enrichment` 字段可复盘 Tavily 是否执行。
- schedule 默认路径仍不启用 Tavily。

### 下一步 2: 多日样本复盘

目标：

- 判断 verify 分层是否提升有效保留。
- 判断 refill 是否在 source 不足时提供可解释补量。
- 判断 request failure 是否持续 fail-open。

样本建议：

- 至少覆盖 source 非空样本。
- 至少覆盖 source 为空样本。
- 至少覆盖 missing-key 或 request timeout 场景。

### 下一步 3: 再评估默认开启

只有同时满足以下条件后，才讨论 `enrichment.enabled: true`：

- source 非空时 verify 不误伤主要真值。
- source 为空时 refill 结果可解释。
- Tavily timeout 不会让已有文章丢失。
- Actions 手动路径多次成功。
- JSON 诊断足够支撑复盘。

## Git 备份策略

本次建议备份范围：

- 代码、测试、workflow、文档和本结论文档。

本次不建议备份：

- `.env`
- `data/2026-05-05.json`
- `content/2026-05-05.md`

理由：

- `.env` 可能包含 secret。
- 2026-05-05 生成产物来自 source timeout 下的本地验收；补跑 `--enrichment on` 后包含 4 条 Tavily refill 结果，但仍不适合作为 PR 内容。
