# Agent C: Production Wiring

## Mission

你只负责让 GitHub Actions 可以手动灰度运行 Tavily enrichment，并补齐本地环境示例。你的目标是验证生产 runner 接线能力，不是把 Tavily 变成每日默认路径。

## Owned Files

你可以修改：

- `.github/workflows/deploy.yml`
- `.env.example`

必要时可以小范围修改 GitHub Actions handbook：

- `handbook/deployment/github-actions.md`

如果需要改其他文档，把需求交给 D。

## Forbidden Files

不要修改：

- `utils/news_enrichment.py`
- `tests/test_news_enrichment.py`
- `config.yaml` 中的 `enrichment.enabled`
- `sources/*`
- `summarizer.py`
- `build.py`

不要新增任何 secret 值。

## Read First

开始前阅读：

```bash
git status --short --branch
sed -n '1,240p' .github/workflows/deploy.yml
sed -n '1,180p' .env.example
sed -n '1,220p' handbook/guides/tavily-integration.md
```

## Required Behavior

实现手动灰度入口：

```yaml
workflow_dispatch:
  inputs:
    enable_tavily:
      type: boolean
      default: false
```

期望语义：

- `enable_tavily=false`: 继续现有行为，不显式开启 Tavily。
- `enable_tavily=true`: 注入 `TAVILY_API_KEY`，执行 `python main.py run --enrichment on`。
- schedule 定时任务继续走默认路径，不因为 Tavily key 缺失失败。
- `MODELSCOPE_API_KEY` 缺失时仍可 offline summary。
- `TAVILY_API_KEY` 缺失但手动打开 Tavily 时，主流程仍应完成；日志要明确 key 缺失会触发安全降级。

推荐 shell 逻辑保持简单可读：

```bash
ENRICHMENT_ARGS=""
if [ "${{ inputs.enable_tavily || false }}" = "true" ]; then
  ENRICHMENT_ARGS="--enrichment on"
fi
```

实际写法需符合 GitHub Actions 表达式语法；不要把 boolean 当成一定存在的 schedule input。

## .env.example

补充：

```bash
# Tavily Search API (可选)
TAVILY_API_KEY=
```

不要填真实 key，不要写看起来像真实 token 的占位符。

## Independent Acceptance

你必须自己跑：

```bash
PYTHONPATH=. pytest -q
python3 main.py run --offline --enrichment off
```

再做静态检查：

```bash
python3 - <<'PY'
from pathlib import Path
text = Path('.github/workflows/deploy.yml').read_text(encoding='utf-8')
assert 'enable_tavily' in text
assert 'TAVILY_API_KEY' in text
assert '--enrichment on' in text
assert 'python main.py run' in text
print('deploy workflow Tavily wiring markers found')
PY
```

如果没有安装完整 dev 依赖导致 `pytest` 失败，必须说明失败原因，并至少跑 `tests/test_news_enrichment.py`。

## Required Self-Review

交付前检查：

- schedule 没有默认强制 `--enrichment on`。
- Pages deploy、archive、retention 步骤没有被改坏。
- `skip_generate=true` 时仍只 build，不生成日报。
- workflow 没有打印 secret。
- `.env.example` 没有真实 key。

## Handoff To E

按这个格式交付：

```text
Agent: C Production Wiring
本轮唯一目标:
修改文件:
workflow_dispatch 语义:
验收命令:
验收结果:
需要 GitHub 仓库设置的 secret:
需要 E 关注:
```
