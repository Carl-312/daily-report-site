# 开发指南

按改动类型选择入口：

- [贡献与交付规范](contributing.md)：分支、提交、CI、PR 和安全边界
- [迭代工作流](iteration-workflow.md)：从证据、假设到灰度验证的固定步骤
- [扩展新闻源](source-adapters.md)：新增 source 的接口、测试和配置方式
- [接口参考](../reference/api.md)：调用边界和结果模型
- [架构说明](../architecture/README.md)：确认改动所在层级

## 开发原则

1. 先修复最小的边界契约，再考虑提示词或策略扩展。
2. 每个独立变更都应可单独验证；代码、测试、运行手册和质量证据同步更新。
3. 灰度验证只使用非 `main` 分支或 `publish=false`；未经明确验收不得发布 Pages。
4. 兼容入口可以保留，但内容只维护一份，其他位置使用指向 canonical 文档的短指针。
