# Handbook

工程文档已经从原来的 `docs/` 迁移到 `handbook/`，避免与站点构建产物混放。

## 导航

- 本地运行：`deployment/local.md`
- GitHub Actions：`deployment/github-actions.md`
- GitHub Pages：`deployment/github-pages.md`
- 配置说明：`guides/configuration.md`
- 扩展新闻源：`guides/extending-sources.md`
- Tavily 接入总览：`guides/tavily-integration.md`
- Tavily 灰度下一轮策略：`guides/tavily-gray-next-steps.md`
- Tavily multi-agent PR 指南：`guides/mutiagent/README.md`
- Tavily 历史文档归档：`guides/history/README.md`
- 故障排查：`guides/troubleshooting.md`
- API 参考：`api/README.md`
- 分 PR 落地建议：`project-rollout.md`

## Tavily 快速入口

Tavily 当前是默认关闭的 post-fetch enrichment 能力，不是默认 source。

- 使用、诊断、默认开启门槛：`guides/tavily-integration.md`
- 当前灰度状态和下一轮测试策略：`guides/tavily-gray-next-steps.md`
- 配置字段和本地开关：`guides/configuration.md`
- GitHub Actions 隔离灰度：`deployment/github-actions.md`
- 失败排查和安全关闭：`guides/troubleshooting.md`
