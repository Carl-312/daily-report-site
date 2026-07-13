# 运行与部署

## 按场景进入

- [本地运行](local.md)：安装、命令、产物和本地检查
- [配置](configuration.md)：`config.yaml`、环境变量和 Tavily 开关
- [GitHub Actions](github-actions.md)：定时任务、手动预览、归档和发布门禁
- [GitHub Pages](github-pages.md)：静态站点发布与回滚检查
- [故障排查](troubleshooting.md)：按症状定位并安全恢复
- [Tavily](tavily.md)：可选 enrichment 的当前状态、诊断和灰度边界

## 发布原则

- 预览先于生产；灰度运行必须 `publish=false` 或在非 `main` 分支。
- 摘要、建站、质量门禁任一失败，都保留上一版已发布产物。
- Tavily 默认关闭；输入不足时允许少于目标数，不能通过模型或补全逻辑硬扩展。
- 变更后的最新运行证据统一记录在 [`../quality/acceptance.md`](../quality/acceptance.md) 和[日报质量审计](../quality/daily-product-quality-audit.md)。
