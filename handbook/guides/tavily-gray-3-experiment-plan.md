# Tavily Gray Test 3 实施准备

本文为下一轮实际执行 Gray Test 3 做准备。目标是在隔离的 GitHub Actions 灰度 workflow 中验证 3 个小改动，不改变生产默认配置，不提交 `.env`，不把 Tavily 默认开启。

## 结论先行

本轮建议只做这 3 项：

1. 调整 refill 域名分层：把 `reuters.com`、`arstechnica.com`、`techcrunch.com` 放入 priority refill，把 `thenextweb.com`、`venturebeat.com` 降到 secondary。
2. 将灰度实验的 `strict_hours` 从 `24` 临时放宽到 `30`。
3. 将灰度实验的 `refill_max_results` 从 `8` 临时提高到 `12`。

这些改动只应在 `.github/workflows/tavily-gray.yml` 中以 runner 工作区临时覆盖方式执行。`config.yaml` 仍保持生产默认值：

```yaml
enrichment:
  enabled: false
  strict_hours: 24
  max_total_calls: 7
  refill_max_results: 8
  enable_official_fallback: false
```

## 为什么选这 3 项

最近 7 次 `tavily-gray.yml` artifact 的核心问题不是 Tavily 请求失败，而是 budget 被低效消耗：

| 问题 | artifact 证据 | 对应改动 |
|---|---|---|
| priority refill 经常产出低效 | `thenextweb.com`/`venturebeat.com` 在 2026-05-11、2026-05-12 出现大量 `missing_published_date`，priority 24 个 result 只接受 5 个 | 将 Reuters/Ars/TechCrunch 提到 priority，TNW/VB 降级 |
| 24h 边界过紧 | scheduled run 多在 Asia/Shanghai 晚间执行，前一日 UTC 下午新闻容易被判 `outside_24h` | 灰度临时 `strict_hours=30` |
| 单次 refill 候选不够深 | secondary 在部分日期可接受率不错，但单轮最多只看 8 条；05-16 有较多非 AI 混入，需要更多候选供过滤 | 灰度临时 `refill_max_results=12` |

Context7 已核对 Tavily Search API：`include_domains`、`start_date`、`end_date`、`topic=news`、`search_depth` 和 `max_results` 是当前支持参数；`max_results` 上限为 `20`，所以 `12` 是保守灰度值。

## 不纳入本轮的项

这些项先不做，避免一次实验变量过多：

- 不提高 `max_total_calls`。先看候选质量提升能不能改善 accepted/result；否则无法区分“预算不足”和“候选质量差”。
- 不开启 `enable_official_fallback`。官方站点适合作为稀疏补充，不适合在当前问题未收敛时混入实验。
- 不改 `verify_search_depth`。verify 的 `no_match` 是另一个问题，本轮聚焦 refill。
- 不把 Tavily 默认开启。单轮灰度达标也不能作为默认启用依据。

## 目标改动位置

### `.github/workflows/tavily-gray.yml`

在 `Install runtime dependencies` 之后、`Require Tavily API key` 之前添加灰度覆盖步骤。

原因：

- `pip install -r requirements.txt` 后 runner 已有 `pyyaml`，可以安全读写 `config.yaml`。
- 覆盖发生在 Actions 工作区，不会提交回仓库。
- `main.py run --offline --enrichment on` 会读取覆盖后的工作区配置。

覆盖内容：

```json
{
  "experiment": "gray_3_refill_domain_window_depth",
  "enrichment": {
    "strict_hours": 30,
    "refill_max_results": 12,
    "trusted_domains": {
      "priority_refill_media_whitelist": [
        "reuters.com",
        "arstechnica.com",
        "techcrunch.com"
      ],
      "secondary_refill_candidate_domains": [
        "thenextweb.com",
        "venturebeat.com"
      ]
    }
  },
  "unchanged_safety_defaults": {
    "enabled": false,
    "enable_official_fallback": false
  }
}
```

artifact 必须写出两个观测文件：

- `gray/tavily/YYYY-MM-DD/logs/gray-experiment-overrides.json`
- `gray/tavily/YYYY-MM-DD/logs/gray-config-diff.patch`

### `utils/news_enrichment.py`

本轮不需要改这里，但验收时要知道配置如何被消费：

- `within_strict_hours()` 使用 `settings.strict_hours` 判定 24h/30h 窗口。
- `run_domain_refill_stage()` 使用 `settings.refill_max_results` 作为 Tavily `max_results`。
- `run_domain_refill_stage()` 使用 `include_domains` 限定 priority/secondary 域名。
- `enable_official_fallback` 仍为 false 时，不进入 official fallback。

### `scripts/tavily_gray_scorecard.py`

本轮不需要改这里。验收使用现有字段：

- `refill.priority_refill.result_count`
- `refill.priority_refill.accepted_count`
- `refill.priority_refill.published_date_missing_count`
- `refill.priority_refill.outside_window_rejected_count`
- `refill.priority_refill.non_ai_rejected_count`
- secondary 的同名字段
- `output.final_count`
- `output.refill_remaining_count`
- `budget.total_calls`
- `budget.official_fallback_enabled`

## 实施检查清单

执行前：

```bash
git status -sb
git log --oneline -3
```

确认：

- 工作区没有未确认的 `.env` 或生成日报文件。
- `config.yaml` 仍是 `enrichment.enabled: false`。
- `enable_official_fallback` 仍是 false。

如果当前分支已经包含 `ci: add Tavily gray 3 experiment overrides`，只需要检查 workflow 中的覆盖步骤是否存在：

```bash
rg -n "gray_3_refill_domain_window_depth|gray-experiment-overrides|refill_max_results" .github/workflows/tavily-gray.yml
```

如果需要重新实现，按“目标改动位置”添加 workflow 覆盖步骤，然后运行：

```bash
.venv/bin/python - <<'PY'
from pathlib import Path
import yaml

for path in [".github/workflows/tavily-gray.yml", "config.yaml"]:
    with open(path, encoding="utf-8") as f:
        yaml.safe_load(f)
    print(f"YAML OK: {path}")
PY

git diff --check
```

## 运行 Gray Test 3

推送包含 workflow 改动的 commit 后触发：

```bash
gh workflow run tavily-gray.yml --ref main
gh run list --workflow tavily-gray.yml --limit 3 --json databaseId,createdAt,status,conclusion,headSha,url
gh run watch RUN_ID --exit-status
```

下载 artifact：

```bash
artifact_dir="$(mktemp -d /tmp/daily-report-tavily-gray-3.XXXXXX)"
gh run download RUN_ID --dir "$artifact_dir"
find "$artifact_dir" -maxdepth 6 -type f | sort
```

GitHub CLI 用法已用 Context7 核对：`gh workflow run` 可指定 workflow 和 `--ref`，`gh run list` 可用 `--workflow` 和 `--limit`，`gh run watch` 接 run id，`gh run download RUN_ID --dir DIR` 可下载 artifact。

## Artifact 必查项

artifact 中必须有：

```text
gray/tavily/YYYY-MM-DD/enrichment-summary.json
gray/tavily/YYYY-MM-DD/scorecard.json
gray/tavily/YYYY-MM-DD/logs/gray-experiment-overrides.json
gray/tavily/YYYY-MM-DD/logs/gray-config-diff.patch
```

用 Python 快速检查参数确实生效：

```bash
python3 - <<'PY'
import glob
import json
from pathlib import Path

base = Path("ARTIFACT_DIR")
summary_path = next(base.glob("**/enrichment-summary.json"))
override_path = next(base.glob("**/gray-experiment-overrides.json"))
scorecard_path = next(base.glob("**/scorecard.json"))

summary = json.loads(summary_path.read_text(encoding="utf-8"))
overrides = json.loads(override_path.read_text(encoding="utf-8"))
scorecard = json.loads(scorecard_path.read_text(encoding="utf-8"))
params = summary["enrichment"]["parameters"]

print("override experiment:", overrides["experiment"])
print("strict_hours:", params["strict_hours"])
print("refill_max_results:", params["refill_max_results"])
print("priority domains:", params["priority_refill_media_whitelist"])
print("secondary domains:", params["secondary_refill_candidate_domains"])
print("official fallback:", params["enable_official_fallback"])
print("final_count:", scorecard["output"]["final_count"])
print("stop_reason:", scorecard["output"]["stop_reason"])
PY
```

期望输出：

- `strict_hours: 30`
- `refill_max_results: 12`
- priority domains 为 `reuters.com`、`arstechnica.com`、`techcrunch.com`
- secondary domains 为 `thenextweb.com`、`venturebeat.com`
- `official fallback: False`

## 验收指标

单次 run 只能作为样本。建议至少观察 3 次 scheduled run，或 1 次手动 run + 后续 2 次 scheduled run。

核心指标：

| 指标 | 通过 | 需复核 | 失败 |
|---|---:|---:|---:|
| priority + secondary accepted/result | `>= 0.50` | `0.35-0.49` | `< 0.35` |
| `final_count` | `>= 10` | `8-9` | `< 8` |
| `published_date_missing_rate` | `< 0.10` | `0.10-0.25` | `> 0.25` |
| `non_ai_rejected_count / result_count` | `< 0.20` | `0.20-0.35` | `> 0.35` |
| `official_fallback_enabled` | false | false | true |

多 run 决策：

- PASS：3 次中至少 2 次 `final_count >= 10`，且 refill accepted/result 中位数 `>= 0.50`。
- FLAG：`final_count` 有改善但仍常在 8-9，需要再分离预算实验或 verify 实验。
- FAIL：priority 仍大量 `missing_published_date`，或 Reuters/Ars/TechCrunch priority 混入非 AI 过多。

## 结果记录模板

把每次 run 追加到 `handbook/guides/tavily-validation-iteration-plan.md`：

```markdown
### Gray Test 3 Run - YYYY-MM-DD

- run id:
- commit:
- artifact:
- override file present: yes/no
- config diff present: yes/no
- input_count:
- verify: calls / accepted / rejected / skipped
- priority refill: result_count / accepted_count / missing_date / outside_24h / non_ai
- secondary refill: result_count / accepted_count / missing_date / outside_24h / non_ai
- final_count / min_articles:
- stop_reason:
- decision: PASS / FLAG / FAIL
- notes:
```

## 回滚方式

如果 Gray Test 3 质量变差，回滚只需要移除 workflow 中的 `Apply gray experiment overrides` 步骤，或直接 revert 对应 commit：

```bash
git revert COMMIT_SHA
```

回滚后确认：

```bash
rg -n "gray_3_refill_domain_window_depth|gray-experiment-overrides" .github/workflows/tavily-gray.yml
```

应无匹配。

## 不做事项

- 不提交 `.env`。
- 不修改 `config.yaml` 的生产默认值。
- 不把 `enable_official_fallback` 改成 true。
- 不因为单次 `final_count >= 10` 就默认开启 Tavily。
- 不把缺少 `published_date` 的候选静默当作有效新闻。
- 不在同一轮混入 `max_total_calls`、`verify_search_depth` 或 official fallback 实验。
