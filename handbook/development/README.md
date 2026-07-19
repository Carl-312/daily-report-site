# 开发指南

## 当前进度

- LLM 执行层已支持 endpoint/model 级 `non_stream` 与安全 `buffered_stream`，统一经过 JSON、来源、质量和发布门禁。
- ModelScope Kimi K2.7 Code 已完成 2026-07-15 live 验证，当前为 **shadow-ready、fallback-not-ready**。
- 默认生产模型顺序未改变；thinking、Structured Outputs 和新模型能力仍按精确路由独立验证，不做模型名推断。

## 当前文档

- [贡献与交付规范](contributing.md)：分支、提交、CI、PR 与安全边界
- [迭代工作流](iteration-workflow.md)：证据、假设、实现和灰度验证流程
- [扩展新闻源](source-adapters.md)：source 接口、测试与配置约定
- [LLM 执行架构](llm-execution.md)：交付模式、双预算、重试和 publication gate
- [MiMo 分级验收契约建议](mimo-adaptive-contract-proposal.md)：逐条隔离编辑问题、保留来源与安全硬门禁
- [Kimi K2.7 最新验证](kimi-k27-modelscope-live-validation.md)：流式协议、live 结果与 shadow 准入结论
- [历史规划与实验](history/README.md)：已完成、已替代或暂未准入的阶段性资料

接口边界见[接口参考](../reference/api.md)，系统分层见[架构说明](../architecture/README.md)。

## 开发原则

1. 先修复边界契约，再扩展提示词或策略。
2. 代码、测试、运行手册和质量证据同步更新。
3. 未经明确验收的模型和数据源只进入隔离 smoke/shadow，不进入默认生产链。
