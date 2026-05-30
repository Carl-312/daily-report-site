# Tavily Gray Test 3 实施准备

最后修改：2026-05-30

本文最初为执行 Gray Test 3 做准备。目标是在隔离的 GitHub Actions 灰度 workflow 中验证 Tavily enrichment，不改变生产默认配置，不提交 `.env`，不把 Tavily 默认开启。

2026-05-30 修订：Gray Test 3 已在 GitHub Actions 上出现连续低质量结果。2026-05-28、2026-05-29、2026-05-30 三次 run 均为 `final_count=0`，`stop_reason=budget_exhausted_after_secondary_refill`，priority + secondary refill accepted/result 分别为 `0/23`、`0/23`、`0/24`。后续不再把原 Gray Test 3 的域名/window/depth 组合视为上线候选；当前改造目标是把 gray workflow 改成一个宽松 3 天诊断实验，用来判断 Tavily 是召回不足，还是主要卡在 `published_date` 元数据缺失与严格 freshness 证明。

## 当前方案：宽松 3 天诊断灰度

### 修改目的

本次改造不是为了提高正式 `final_count`，也不是为了证明 Tavily 可以默认开启，而是把 Gray Test 3 改成一个诊断实验：

1. 验证 Tavily 在 3 天窗口内是否能召回足够多的 AI/科技新闻候选。
2. 区分“没有候选”和“有候选但缺少 `published_date`，无法通过严格 freshness 证明”。
3. 量化严格规则与宽松规则之间的差距，避免继续盲目调整域名、预算或 `refill_max_results`。
4. 为下一轮判断提供证据：如果宽松候选充足但严格候选仍为 0，下一步应优先研究 Tavily 日期元数据和 query 命中，而不是把这组配置上线。

### 诊断规则

宽松诊断规则只用于 artifact 观察，不改变生产默认路径：

- `config.yaml` 仍保持 `enrichment.enabled: false`、`strict_hours: 24`、`refill_max_results: 8`。
- `.github/workflows/tavily-gray.yml` 继续是隔离灰度 workflow，不提交、不发布、不部署。
- Gray workflow 只在 runner 工作区临时开启 `lenient_refill_diagnostics_enabled`。
- Tavily refill 请求窗口从 1 天扩大到 3 天，artifact 必须记录实际 `start_date`、`end_date`、`request_window_hours` 和诊断窗口小时数。
- 宽松候选池只排除“明确可判定超过 72 小时”的结果。
- 缺少 `published_date` 的结果不得算作严格通过，但可进入 `missing_date_unproven` 诊断桶。
- 标题 AI 相关性、重复、near duplicate、story cluster 等规则不阻断宽松候选计数，但必须继续作为诊断字段记录。
- 严格产物计数与宽松诊断计数必须分开：宽松候选不能静默写入正式 `final_count`，也不能作为默认开启依据。

Artifact 必须能看到这些字段：

```text
strict_final_count
strict_refill_accepted_count
lenient_candidate_count
proven_within_72h_count
missing_date_unproven_count
outside_72h_rejected_count
lenient_non_ai_count
lenient_duplicate_or_cluster_count
lenient_selected_preview
```

### 当前实施要求

`.github/workflows/tavily-gray.yml` 的灰度覆盖步骤应写出 `gray-experiment-overrides.json` 和 `gray-config-diff.patch`，并临时覆盖：

```json
{
  "experiment": "gray_3_lenient_3day_diagnostic",
  "enrichment": {
    "strict_hours": 24,
    "refill_max_results": 8,
    "refill_search_window_hours": 72,
    "lenient_refill_diagnostics_enabled": true,
    "lenient_refill_window_hours": 72,
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

`utils/news_enrichment.py` 必须保持严格输出路径不变：

- `final_count` 只来自严格 verify/refill/fallback 接受结果。
- 缺少 `published_date` 的结果不能进入严格 accepted candidates。
- 72h 宽松候选只进入诊断字段。
- 当诊断开启时，refill `candidate_results` 应保留所有 Tavily 返回项，便于统计非 AI、重复、cluster、缺日期和明确超过 72h 的候选。

`scripts/tavily_gray_scorecard.py` 必须把 strict/lenient 指标写入 `scorecard.json` 和 `scorecard.md`，避免只靠原始 `report.json` 排查。

### 验收标准

单次 run 只能作为样本。宽松诊断至少观察 3 次 scheduled run，或 1 次手动 run 加后续 2 次 scheduled run。

| 指标 | 通过 | 需复核 | 失败 |
|---|---:|---:|---:|
| artifact 写出宽松诊断字段 | 全部存在 | 缺少 preview 或分阶段字段 | 缺少 strict/lenient 分离 |
| `lenient_candidate_count` | `>= 10` | `5-9` | `< 5` |
| `proven_within_72h_count` | `>= 8` | `3-7` | `< 3` |
| `missing_date_unproven_count / lenient_candidate_count` | `< 0.30` | `0.30-0.70` | `> 0.70` |
| `outside_72h_rejected_count / result_count` | `< 0.20` | `0.20-0.40` | `> 0.40` |
| `strict_final_count` | 不低于原严格规则 | 下降但原因可解释 | 因宽松改造污染严格计数 |

多 run 决策：

- PASS：3 次中至少 2 次 `lenient_candidate_count >= 10`，且 `proven_within_72h_count >= 8`。这只证明 3 天召回有潜力，仍不能默认开启 Tavily。
- METADATA-FAIL：`lenient_candidate_count >= 10`，但 `missing_date_unproven_count / lenient_candidate_count > 0.70`。这说明主要问题是 Tavily 返回缺少 `published_date`，下一步应做 metadata probe 或解析策略验证。
- RECALL-FAIL：`lenient_candidate_count < 5`。这说明当前 query/domain 组合召回不足，继续扩大窗口或预算价值不高。
- CONTAMINATION-FAIL：宽松候选进入正式 `final_count`，或 artifact 无法区分 strict 与 lenient。该 run 不能用于策略判断。

### 实施检查清单

执行前：

```bash
git status -sb
git log --oneline -3
```

确认：

- 工作区没有未确认的 `.env` 或生成日报文件。
- `config.yaml` 仍是 `enrichment.enabled: false`。
- `config.yaml` 仍是 `strict_hours: 24`、`refill_max_results: 8`。
- `enable_official_fallback` 仍是 false。

本地验证：

```bash
.venv/bin/python - <<'PY'
from pathlib import Path
import yaml

for path in [".github/workflows/tavily-gray.yml", "config.yaml"]:
    with open(path, encoding="utf-8") as f:
        yaml.safe_load(f)
    print(f"YAML OK: {path}")
PY

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. pytest -q -p no:cacheprovider
ruff check .
ruff format --check .
git diff --check
```

## 运行 Gray Test 3 诊断

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

Artifact 必须有：

```text
gray/tavily/YYYY-MM-DD/enrichment-summary.json
gray/tavily/YYYY-MM-DD/scorecard.json
gray/tavily/YYYY-MM-DD/scorecard.md
gray/tavily/YYYY-MM-DD/logs/gray-experiment-overrides.json
gray/tavily/YYYY-MM-DD/logs/gray-config-diff.patch
```

快速检查：

```bash
python3 - <<'PY'
import glob
import json
from pathlib import Path

base = Path("ARTIFACT_DIR")
summary = json.loads(next(base.glob("**/enrichment-summary.json")).read_text(encoding="utf-8"))
overrides = json.loads(next(base.glob("**/gray-experiment-overrides.json")).read_text(encoding="utf-8"))
scorecard = json.loads(next(base.glob("**/scorecard.json")).read_text(encoding="utf-8"))
params = summary["enrichment"]["parameters"]
diag = scorecard["lenient_diagnostics"]

print("experiment:", overrides["experiment"])
print("strict_hours:", params["strict_hours"])
print("refill_max_results:", params["refill_max_results"])
print("refill_search_window_hours:", params["refill_search_window_hours"])
print("lenient enabled:", params["lenient_refill_diagnostics_enabled"])
print("diagnostic window:", diag["window_hours"])
print("strict_final_count:", diag["strict_final_count"])
print("lenient_candidate_count:", diag["lenient_candidate_count"])
print("proven_within_72h_count:", diag["proven_within_72h_count"])
print("missing_date_unproven_count:", diag["missing_date_unproven_count"])
print("outside_72h_rejected_count:", diag["outside_72h_rejected_count"])
PY
```

## 结果记录模板

把每次 run 追加到 `handbook/guides/tavily-validation-iteration-plan.md`：

```markdown
### Gray Test 3 Diagnostic Run - YYYY-MM-DD

- run id:
- commit:
- artifact:
- override file present: yes/no
- config diff present: yes/no
- input_count:
- verify: calls / accepted / rejected / skipped
- priority refill: result_count / accepted_count / missing_date / outside_strict / non_ai
- secondary refill: result_count / accepted_count / missing_date / outside_strict / non_ai
- strict_final_count / min_articles:
- lenient_candidate_count:
- proven_within_72h_count:
- missing_date_unproven_count:
- outside_72h_rejected_count:
- lenient_non_ai_count:
- lenient_duplicate_or_cluster_count:
- stop_reason:
- decision: PASS / METADATA-FAIL / RECALL-FAIL / CONTAMINATION-FAIL / NEEDS-MORE-RUNS
- notes:
```

## 原 Gray Test 3 方案（归档）

以下内容仅保留为 2026-05-17 原始方案和回滚上下文。2026-05-30 之后不再把这组域名/window/depth 组合视为上线候选。

原方案只做 3 项：

1. 调整 refill 域名分层：把 `reuters.com`、`arstechnica.com`、`techcrunch.com` 放入 priority refill，把 `thenextweb.com`、`venturebeat.com` 降到 secondary。
2. 将灰度实验的 `strict_hours` 从 `24` 临时放宽到 `30`。
3. 将灰度实验的 `refill_max_results` 从 `8` 临时提高到 `12`。

该方案在后续 run 中没有改善正式 `final_count`，因此当前只保留域名分层作为诊断变量，不再保留 `strict_hours=30` 和 `refill_max_results=12` 作为当前灰度目标。

## 不做事项

- 不提交 `.env`。
- 不修改 `config.yaml` 的生产默认值。
- 不把 `enable_official_fallback` 改成 true。
- 不因为单次 `final_count >= 10` 就默认开启 Tavily。
- 不把缺少 `published_date` 的候选静默当作有效新闻。
- 不在同一轮混入 `max_total_calls`、`verify_search_depth` 或 official fallback 实验。
