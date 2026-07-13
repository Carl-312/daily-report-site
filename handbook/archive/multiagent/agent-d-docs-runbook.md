# Agent D: Docs Runbook

## Mission

你只负责把 Tavily PR 的使用方式、诊断方式、灰度方式和边界说明写清楚，让维护者不读代码也知道怎么运行、怎么判断失败、怎么回滚到安全路径。

## Owned Files

你可以修改：

- `handbook/operations/tavily.md`
- `handbook/operations/configuration.md`
- `handbook/operations/github-actions.md`
- `handbook/operations/troubleshooting.md`
- `handbook/README.md`
- `README.md`
- `CONTRIBUTING.md`
- `handbook/archive/multiagent/*`

## Forbidden Files

不要修改：

- `utils/news_enrichment.py`
- `tests/*`
- `.github/workflows/*`
- `config.yaml`
- benchmark JSON/MD 产物，除非 E 明确要求归档新实验结果

## Read First

开始前阅读：

```bash
git status --short --branch
sed -n '1,260p' handbook/operations/tavily.md
sed -n '1,220p' handbook/operations/configuration.md
sed -n '1,220p' handbook/operations/github-actions.md
sed -n '1,220p' handbook/README.md
sed -n '1,360p' AGENT_ITERATION_WORKFLOW.md
```

## Required Content

文档必须讲清楚：

1. Tavily 是 post-fetch enrichment，不是 source 替代品。
2. 默认 `enrichment.enabled: false`，PR 不默认开启。
3. 本地显式启用命令：

```bash
TAVILY_API_KEY=... python3 main.py fetch --enrichment on
TAVILY_API_KEY=... python3 main.py run --offline --enrichment on
```

4. 安全关闭命令：

```bash
python3 main.py fetch --enrichment off
python3 main.py run --offline --enrichment off
```

5. GitHub Actions 手动灰度入口的用法和限制。
6. `data/YYYY-MM-DD.json` 中 `enrichment` 字段如何看。
7. source 为 0 条时的解释：这是受控补量场景，不是正常 verify 成熟度证明。
8. Tavily 失败时预期行为：主流程完成，已有 deduped articles 尽量保留，JSON 诊断记录失败。
9. 什么时候才考虑默认开启 Tavily。

## Terminology

术语保持一致：

- `verify`: 验证已有 source 候选。
- `refill`: 在不足时按可信域名补量。
- `official_fallback`: 官方站点补量，默认不启用。
- `fail-open`: Tavily 出错时保住现有抓取和落盘。
- `strict_hours`: 严格时间窗，当前目标是 24 小时。
- `trusted_domains`: 策略层，不是热修名单。

## Independent Acceptance

你必须自己跑：

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

再检查链接目标存在：

```bash
python3 - <<'PY'
from pathlib import Path
for rel in [
    'handbook/operations/tavily.md',
    'handbook/operations/configuration.md',
    'handbook/operations/github-actions.md',
    'handbook/archive/multiagent/README.md',
]:
    assert Path(rel).exists(), rel
print('expected handbook files exist')
PY
```

## Required Self-Review

交付前检查：

- 没有把 Tavily 写成默认 source。
- 没有承诺“必定搜满 10 条”。
- 没有建议放宽 24 小时时间窗。
- 没有把单次 live 结果写成稳定结论。
- 没有写入 secret 或假 token。

## Handoff To E

按这个格式交付：

```text
Agent: D Docs Runbook
本轮唯一目标:
修改文件:
新增/更新的操作说明:
验收命令:
验收结果:
仍需 E 同步的字段名或行为:
```
