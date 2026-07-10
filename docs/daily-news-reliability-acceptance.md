# 每日新闻可靠性验收记录

**分支：** `gsd/daily-news-reliability`  
**PR：** Draft #8  
**状态：** 灰度分支实现完成，Draft PR 保持不合并

## 已验证能力

- 运行时钟、严格 manifest、来源状态与脱敏配置指纹。
- JSON/Markdown 原子单文件替换，run-scoped staging、journal、备份与中断恢复。
- staged 站点目录切换；摘要/建站失败和零文章门禁不会覆盖正式产物。
- 完整 `data/content/site` edition 与原子 `public-version.json` 指针；兼容路径只在指针成功后刷新，失败时不影响 pointer 选中的权威版本。
- AI provider 与离线摘要均生成 `SummaryResult`，记录 provider/model、attempt、输入与 prompt 指纹并可 replay。
- enrichment 的 transport、policy、verification、refill 已分别落在独立模块，主编排仍通过稳定边界调用。
- 部分来源降级、全源失败、重复等价输入 no-op、来源有限重试。
- 离线结构化摘要与 replay 元数据。

## 已通过的 GitHub Actions 检查点

- `p0-contract`
- `gray-scenarios`
- `final-regression`
- `quality`

这些检查只证明当前测试矩阵通过，不是 merge 授权。

## 交付门禁证据

- 本地：Ruff lint/format 全绿，pytest `75 passed`（仅既有 Pydantic 弃用 warning）。
- GitHub Actions push run `29073505317`：`p0-contract`、`quality`、`gray-scenarios`、`final-regression` 全部通过。
- GitHub Actions pull request run `29073506997`：`p0-contract`、`quality`、`gray-scenarios`、`final-regression` 全部通过。
- 深度代码审查：`01-REVIEW.md` 当前 verdict 为 `passed`，无 P0/P1/P2 finding。

PR #8 仍必须保持 Draft；不得直接修改或合入 `main`。

在上述阻塞项消除、回滚演练和最终审查重新通过前，PR 必须保持 Draft，且不得合入 `main`。

## 已接纳提交（按主题）

- `eaa0c21`、`6b9d18c`：运行契约、时钟、来源结果。
- `7432f1f`、`fe52d6f`、`90b88d7`、`8efd588`：原子写入、staging、promotion、站点构建。
- `580cbe6`、`731e3b6`、`e2bb273`：P0、灰度、最终回归 CI 检查点。
- `c6b1542`、`fc97bf0`、`3cab692`、`ae6050b`：no-op、manifest 决策、中断恢复、站点目录切换。
- `f4bbdeb`、`b3fab5b`、`251db09`：来源重试、尝试次数、Syft 故障分类。
- `f617360`、`f04d091`、`bfa66b7`：结构化摘要与离线 replay 元数据。

---
*最后更新：2026-07-10*
