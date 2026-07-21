# Daily Report Site 全局上下文

本文档是仓库级协作与交付约束入口。具体运行、架构、质量和历史证据继续在
[`handbook/`](handbook/README.md) 中按主题维护，不在本文档重复展开。

## 协作方式

- 以 INTJ 型高级软件开发专家的方式工作：先拆解意图，再用简洁、可验证的步骤交付。
- 先检查仓库事实、现有测试与运行证据，只把真正的产品取舍交给维护者决策。
- 保留用户未提交的变更；有混合工作树时显式分隔提交范围，不使用破坏性 Git 命令。
- 只在库、框架、SDK、CLI 或云服务的当前版本/API 细节会实质影响结果时使用
  Context7。已知精确 library ID 时直接使用，否则先用完整问题解析；优先高质量官方文档，
  并在 Context7 失败或超额后先明确说明，再使用备选来源。

## 当前产品契约

- 每日公开主新闻的产品目标与发布上限均为 **10 条**；证据合格候选不足时可以更少，
  不复制候选、不降低证据门槛凑数。
- 选题使用 `source_balanced_v2`；发布前必须复核事件去重、来源/主体/模型集中度、
  `article_id` 映射与摘要证据。
- Tavily 是受预算和截止时间约束的候选证据增强层，不取代 source adapter，不把 Tavily answer
  当作事实来源。
- AGI Hunt Trending 可提供选题信号；排名、热度、内部 ID、直接来源 URL 和运行诊断不进入
  读者正文。
- 读者页面固定为编号新闻、独立互动话题、页尾“入选来源”。来源行由本地代码按最终
  `SummaryResult.items` 反查、去重并转为可读名称，不扫描未入选候选。
- 任何阻断的生成、摘要或建站失败都必须保留上一个 last-known-good edition。

## 当前交付状态（2026-07-21）

- 当前实现分支：`agent/content-value-enrichment`
- 当前在线灰度源提交：`0cbaef35569fcecf1620a0eae25379bf071f450e`（后续纯文档提交不会改写该在线产物）
- Draft PR：[#14](https://github.com/Carl-312/daily-report-site/pull/14)
- 状态：正式灰度已通过并在线；尚未合并或发布到生产 `main`。
- 正式灰度：[`daily-report-site-gray`](https://carl-312.github.io/daily-report-site-gray/)，独立仓库
  `Carl-312/daily-report-site-gray` 的 `gh-pages` 分支。
- 生产站：[`daily-report-site`](https://carl-312.github.io/daily-report-site/)，保持现有 `main` / GitHub Actions
  发布边界，灰度运行不得改写。
- 当前仅保留一套灰度：源运行
  [`29818465019`](https://github.com/Carl-312/daily-report-site/actions/runs/29818465019)、灰度 Pages 运行
  [`29818600100`](https://github.com/Carl-312/daily-report-site-gray/actions/runs/29818600100)与对应 deployment。
- 旧灰度运行、失活 deployment、`agent/agihunt-primary-source` 和
  `agent/tavily-gray-36h-diversity` 远端分支已删除；旧 Draft PR #11 已关闭。

## 最新验证基线

- 本地：`211 passed`，`ruff check .`、`ruff format --check .`、`git diff --check` 和
  `python -m compileall -q .` 通过；仅保留已知 Pydantic V2 弃用警告。
- CI：push run
  [`29818445035`](https://github.com/Carl-312/daily-report-site/actions/runs/29818445035) 与 PR run
  [`29818447823`](https://github.com/Carl-312/daily-report-site/actions/runs/29818447823) 的
  `p0-contract` / `quality` / `gray-scenarios` / `final-regression` 全部通过。
- 正式灰度产出 10 条新闻，Trending health 通过，生产 deploy 跳过；线上 HTML 包含 10 个
  编号段落、1 个互动区块和 1 个入选来源区块，与 preview artifact SHA-256 一致。

## 文档与发布边界

- 当前实现以代码、测试、`config.yaml` 和 `.github/workflows/` 为可执行事实。
- 当前架构以 [`handbook/architecture/system.md`](handbook/architecture/system.md) 为基线；运行以
  [`handbook/operations/`](handbook/operations/README.md) 为准；验收证据进入
  [`handbook/quality/acceptance.md`](handbook/quality/acceptance.md)。
- `handbook/archive/` 只保留历史上下文，不作为当前实现或运行依据。
- 不直接推送或修改 `main`。生产合并/发布必须由维护者明确授权，并继续通过 Draft PR、CI、
  正式灰度和生产发布门禁。
