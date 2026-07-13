# Agent E: Integration Owner

## Mission

你负责把 A-D 的工作收敛成一个可提交 PR：解决冲突、跑总验收、确认 fail-open、整理 PR 描述。你不是“再做一个大改”的 agent；你的重点是集成质量和发布边界。

## Owned Files

你可以小范围修改任何文件，但默认应先只读审查。

允许你改的典型 glue 文件：

- `handbook/operations/tavily.md`
- `handbook/README.md`
- `.github/workflows/deploy.yml`
- `tests/test_news_enrichment.py`
- `utils/news_enrichment.py`

规则：只有在集成冲突或验收失败需要最小修正时才改，且必须说明为什么跨越了原 agent 边界。

## Forbidden Actions

不要做：

- 不要把 `enrichment.enabled` 改成 true。
- 不要删除其他 agent 的测试来换取通过。
- 不要扩大 Tavily 调用预算来掩盖策略问题。
- 不要把 Actions 手动灰度改成 schedule 默认开启。
- 不要使用 `git reset --hard` 或覆盖用户已有未提交改动。
- 不要把 live Tavily 失败当作 PR 阻塞，只要 fail-open 和诊断成立即可。

## Read First

开始前阅读：

```bash
git status --short --branch
sed -n '1,260p' handbook/archive/multiagent/README.md
sed -n '1,260p' handbook/operations/tavily.md
sed -n '1,360p' AGENT_ITERATION_WORKFLOW.md
sed -n '1,260p' utils/news_enrichment.py
sed -n '1,320p' tests/test_news_enrichment.py
sed -n '1,240p' .github/workflows/deploy.yml
```

## Integration Checklist

先收集 A-D 的交付摘要，确认每个 agent 都回答：

- 修改了哪些文件。
- 明确没有修改哪些边界。
- 跑了哪些验收命令。
- 哪些命令没跑，原因是什么。
- 是否影响 fail-open。
- 是否需要你处理冲突。

然后检查：

1. `utils/news_enrichment.py` 的 verify/refill 语义没有混在一起。
2. `tests/test_news_enrichment.py` 覆盖新增诊断字段和失败语义。
3. `.github/workflows/deploy.yml` 只提供手动 Tavily 灰度，不默认开启。
4. `.env.example` 有 `TAVILY_API_KEY=`，没有真实 secret。
5. `handbook/operations/tavily.md` 与最终字段、命令一致。
6. `config.yaml` 仍是 `enrichment.enabled: false`。
7. 生成 JSON 的 `enrichment` 字段足以复盘 Tavily 是否执行、失败在哪个阶段、保留了哪些原始文章。

## Total Acceptance

总验收优先跑：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. pytest -q -p no:cacheprovider tests/test_news_enrichment.py
PYTHONPATH=. pytest
python3 main.py fetch --enrichment off
python3 main.py run --offline --enrichment off
```

如果本地有 `TAVILY_API_KEY`，再跑：

```bash
python3 main.py run --offline --enrichment on
```

如果没有 key，不要阻塞 PR；确认 missing-key 安全降级测试通过即可。

Actions 静态检查：

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

## PR Description Template

最终 PR 描述建议使用：

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

- [ ] `pytest -q tests/test_news_enrichment.py`
- [ ] `pytest`
- [ ] `python3 main.py fetch --enrichment off`
- [ ] `python3 main.py run --offline --enrichment off`
- [ ] Optional with key: `python3 main.py run --offline --enrichment on`

## Notes

- Tavily remains a post-fetch enrichment layer, not a replacement source.
- Source=0 runs are controlled refill scenarios, not proof that verify is mature.
```

## Handoff To User

按这个格式交付：

```text
Agent: E Integration Owner
集成结论:
合并的 agent 工作:
最终修改文件:
总验收命令:
总验收结果:
未跑项目和原因:
PR 风险:
建议下一步:
```
