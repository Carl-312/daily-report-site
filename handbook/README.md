# Handbook

这里是项目文档的唯一主题入口。根目录 [`README.md`](../README.md) 只保留导航；具体内容按读者任务和信息生命周期分层。

## 文档地图

| 层级 | 解决的问题 | 入口 |
| --- | --- | --- |
| 入门 | 第一次安装、配置和运行 | [`getting-started.md`](getting-started.md) |
| 架构 | 系统如何工作、边界在哪里 | [`architecture/`](architecture/README.md) |
| 开发 | 如何改代码、扩展 source、验证变更 | [`development/`](development/README.md) |
| 运行 | 如何配置、执行、发布和排障 | [`operations/`](operations/README.md) |
| 质量 | 如何审计日报、验收交付和安排改进 | [`quality/`](quality/README.md) |
| 参考 | 稳定接口和数据契约 | [`reference/`](reference/README.md) |
| 归档 | 已结束实验、旧规划和历史协作记录 | [`archive/`](archive/README.md) |

## 写作与维护规则

1. 当前实现、运行步骤和风险只写在对应的 active 层，不在 README 或多处复制。
2. 运行事实进入 `quality/`；设计决策进入 `architecture/`；可执行操作进入 `operations/`。
3. 实验草案、已完成计划和过期入口移动到 `archive/`，保留原始上下文但不作为当前状态依据。
4. 文档互相引用使用仓库相对链接；改路径时先更新入口，再运行断链检查。
5. 每次影响运行行为的代码变更，至少同步接口、运行、质量三个受影响层中的文档。

## 当前维护入口

- [部署与发布门禁](operations/github-actions.md)
- [日报质量审计](quality/daily-product-quality-audit.md)
- [可靠性验收证据](quality/acceptance.md)
- [稳定性改进分析](quality/improvement-analysis.md)
