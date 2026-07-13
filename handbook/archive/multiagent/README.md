# Tavily Multi-Agent PR 指南

本文是 `/home/carl/daily-report-site` 中推进 Tavily 兜底新闻能力的 multi-agent 工作入口。

> 归档说明：本文记录 2026 年 5 月的协作方案，不代表当前任务状态。当前 Tavily 入口是 [`../../operations/tavily.md`](../../operations/tavily.md)，当前开发规范见 [`../../development/README.md`](../../development/README.md)。

目标不是让多个 agent 同时“随便优化 Tavily”，而是把一个 PR 拆成互不干扰的独立工作区：每个 agent 有明确文件所有权、禁止触碰范围、验收命令和交付格式。

原文曾使用拼写错误的 `mutiagent` 路径；本次文档整理已将其归档到 `archive/multiagent/`，历史引用仅保留作上下文。

## PR 总目标

这个 PR 最终要满足两件事：

1. 在现有 source 抓取不足时，Tavily 能作为受控补量层，尽量兜底搜到 24 小时内的科技/AI 新闻。
2. 如果 Tavily key 缺失、请求失败、超时、返回结构异常或 GitHub Actions 没启用 Tavily，现有抓取、落盘、AI 总结和站点构建不能被破坏。

硬约束：

- Tavily 仍是 `post-fetch enrichment layer`，不是 `sources/` 下的新常驻 source。
- 默认配置继续保持 `enrichment.enabled: false`，不要在这个 PR 中默认开启。
- 严格 24 小时时间窗不能为了凑数量而放宽。
- request error 不能伪装成验证失败；诊断里必须能看出是 timeout、HTTP error、connection error 还是其他 request error。
- 每个 agent 必须自己跑完独立验收，再把结果交给 Integration Owner。

## 当前架构基线

正式链路保持：

```text
fetch_all
-> dedupe
-> enrich_articles_with_tavily
-> save_json
-> summarize
-> build
```

关键文件：

- `utils/news_enrichment.py`: Tavily verify/refill/diagnostics 正式模块。
- `main.py`: `run` 和 `fetch` 中的 enrichment 接线。
- `config.py`: `TAVILY_API_KEY` 和 enrichment 配置读取。
- `config.yaml`: 默认 Tavily 策略，当前必须保持默认关闭。
- `tests/test_news_enrichment.py`: Tavily 行为契约测试。
- `.github/workflows/deploy.yml`: 生产 runner 接线。
- `handbook/operations/tavily.md`: Tavily 当前状态总入口。

## Agent 分工总表

| Agent | 目标 | Owned files | 必须独立验收 |
|---|---|---|---|
| A. Enrichment Logic | 让 verify 支持 AI 相关性分层，并保持 refill 严格 | `utils/news_enrichment.py` | `pytest -q tests/test_news_enrichment.py` |
| B. Test Contract | 为 A/C 的行为加可回归测试和 fixture 断言 | `tests/test_news_enrichment.py`, `data/benchmarks/fixtures/*` | `pytest -q tests/test_news_enrichment.py` |
| C. Production Wiring | 增加 GitHub Actions 手动 Tavily 灰度入口 | `.github/workflows/deploy.yml`, `.env.example` | `pytest -q tests`, YAML/命令检查 |
| D. Docs Runbook | 更新使用、诊断、PR 操作说明 | `handbook/**`, `README.md`, `CONTRIBUTING.md` | 链接检查、术语一致性检查 |
| E. Integration Owner | 收敛分支、解决冲突、跑总验收、准备 PR | 全局只读优先，必要时小范围修 glue | 全量矩阵和 PR checklist |

## 全局边界

所有 agent 都必须遵守：

1. 开始前先看 `git status --short --branch`，不要覆盖别人的未提交改动。
2. 只修改自己 owned files；需要跨边界时，先在交付说明里提出，不要擅自改。
3. 不要重构 `sources/`、`summarizer.py`、`build.py`，除非 Integration Owner 明确批准。
4. 不要修改 `config.yaml` 中的 `enrichment.enabled: false`。
5. 不要删除历史 benchmark、fixture、handbook 归档材料。
6. 不要把 `TAVILY_API_KEY`、模型 key 或任何 secret 写进仓库。
7. 不要把 live Tavily 成功当作唯一验收；必须有单测或可回放证据。

## 推荐并行顺序

第一波可以并行：

- A 只改 `utils/news_enrichment.py`。
- B 先写当前应有行为测试，可用 monkeypatch 模拟 Tavily。
- C 只改 Actions 和 `.env.example`。
- D 先写 runbook，不依赖 A 的最终代码细节。

第二波由 E 收敛：

- 合并 A/B 的测试语义。
- 检查 C 的 Actions 入口不会默认启用 Tavily。
- 让 D 的文档与最终字段名、命令、stop reason 对齐。
- 跑总验收并整理 PR 描述。

## 冲突处理规则

如果两个 agent 都想改同一个文件，以这个优先级处理：

1. `utils/news_enrichment.py`: A 拥有，其他 agent 只提需求。
2. `tests/test_news_enrichment.py`: B 拥有，A 可提出需要覆盖的 case。
3. `.github/workflows/deploy.yml`: C 拥有，E 只做最终集成修正。
4. `handbook/**`: D 拥有，但 E 可以做最终术语同步。
5. `config.yaml`: 默认不归任何 agent 修改；确需改策略必须由 E 合并并说明证据。

## 每个 Agent 的交付格式

每个 agent 完成后必须给 E 这段摘要：

```text
Agent: <A/B/C/D/E 名称>
本轮唯一目标: <一句话>
修改文件: <列表>
明确未修改: <关键边界>
验收命令: <实际跑过的命令>
验收结果: <通过/失败/跳过原因>
fail-open 影响: <保持/加强/无关>
需要 E 处理: <冲突、后续、无>
```

## 独立指南

- [Agent A: Enrichment Logic](agent-a-enrichment-logic.md)
- [Agent B: Test Contract](agent-b-test-contract.md)
- [Agent C: Production Wiring](agent-c-production-wiring.md)
- [Agent D: Docs Runbook](agent-d-docs-runbook.md)
- [Agent E: Integration Owner](agent-e-integration-owner.md)
