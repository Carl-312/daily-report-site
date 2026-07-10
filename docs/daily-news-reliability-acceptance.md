# 每日新闻可靠性验收记录

**分支：** `gsd/daily-news-reliability`  
**PR：** Draft #8  
**状态：** 进行中，禁止合并

## 已验证能力

- 运行时钟、严格 manifest、来源状态与脱敏配置指纹。
- JSON/Markdown 原子单文件替换，run-scoped staging、journal、备份与中断恢复。
- staged 站点目录切换；摘要/建站失败和零文章门禁不会覆盖正式产物。
- 完整 `data/content/site` edition 与原子 `public-version.json` 指针；兼容路径只在指针成功后刷新。
- AI provider 与离线摘要均生成 `SummaryResult`，记录 provider/model、attempt、输入与 prompt 指纹并可 replay。
- 部分来源降级、全源失败、重复等价输入 no-op、来源有限重试。
- 离线结构化摘要与 replay 元数据。

## 已通过的 GitHub Actions 检查点

- `p0-contract`
- `gray-scenarios`
- `final-regression`
- `quality`

这些检查只证明当前测试矩阵通过，不是 merge 授权。

## 未闭合的阻塞项

1. 运行级 deadline 尚未限制来源、Tavily、摘要和构建的总耗时。
2. Tavily 大模块尚未按 transport/policy/verification/refill 拆分。

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
