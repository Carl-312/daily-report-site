# Daily Report Site

AI 驱动的技术新闻日报生成器。

每日公开主新闻的产品目标和发布上限均为 10 条；证据合格候选不足时允许更少，不为凑数降低证据门槛。

本页只负责导航；项目说明、运行手册、架构设计、质量证据和历史记录按主题维护在 [`handbook/`](handbook/README.md) 中。

## 从这里开始

- [快速开始](handbook/getting-started.md)：安装、配置和一次本地运行
- [系统架构](handbook/architecture/README.md)：数据流、模块边界和可靠性约束
- [运行与部署](handbook/operations/README.md)：本地运行、Actions、Pages、配置和故障排查
- [开发指南](handbook/development/README.md)：贡献、扩展新闻源和迭代流程
- [质量与验收](handbook/quality/README.md)：质量审计、验收证据和后续改进
- [接口参考](handbook/reference/README.md)：CLI、摘要契约、去重和存储 API
- [历史归档](handbook/archive/README.md)：已结束的实验、旧规划和 multi-agent 记录

## 项目约束

- [AGENTS.md](AGENTS.md)：当前工作区的协作与交付约束
- [`.github/workflows/`](.github/workflows/)：CI 与每日发布流程
- [配置示例](config.yaml)：非密钥运行配置
