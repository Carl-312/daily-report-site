# LLM 执行架构

- 当前状态：已上线 endpoint/model 级执行策略和两种完整响应收集模式
- 最近验证：2026-07-15，ModelScope Kimi K2.7 Code buffered stream
- 发布边界：模型响应必须完整通过本地契约后才能发布

## 当前链路

```text
候选文章
  -> endpoint/model capability
  -> execution policy 与运行 deadline
  -> non_stream 或 buffered_stream collector
  -> 最终正文提取
  -> JSON / contract / provenance / quality gate
  -> 本地 Markdown 渲染与原子发布
```

公开摘要 API 只返回完整、已校验的结果，不暴露边生成边消费的 `stream` 开关。

## 交付模式

| 模式 | 使用条件 | 发布语义 |
| --- | --- | --- |
| `non_stream` | 默认；provider 能返回单一完整 JSON envelope | 完整响应后校验 |
| `buffered_stream` | 精确路由已通过 SSE live probe | 内存聚合完毕后按同一门禁校验 |

`buffered_stream` 只聚合 `delta.content`。reasoning 只记录长度，不保存原文，也不会提升为正文；缺少
终止信号、reasoning-only、refusal、截断或协议形状异常均 fail-closed。

## 执行策略

每个 capability 可以独立配置：

- `max_output_tokens`：模型输出预算；
- `attempt_timeout_seconds`：单次请求等待上限；
- `provider_budget_seconds`：同模型全部尝试与退避预算；
- `max_attempts`、`retryable_codes`：显式、可审计的应用层重试；
- `delivery_mode`：选择完整响应收集器。

SDK 自动重试保持关闭。每个真实 HTTP 请求对应独立 attempt artifact，并同时受 provider budget 与
整次 run deadline 限制。`finish_reason=length` 不通过延长 timeout 或原样重试修复。

## 能力边界

能力只绑定精确 `(provider, base_url, model)`：

- 不按模型名推断 thinking、temperature 或 Structured Outputs；
- 不把一个 provider 的验证结论复制到另一个 endpoint；
- 新交付模式先经过 smoke/shadow，再讨论 fallback；
- 默认 provider 顺序只能由跨日稳定性和质量证据改变。

当前 Kimi K2.7 capability 为 shadow-ready、fallback-not-ready。完整证据见
[Kimi K2.7 live 验证](kimi-k27-modelscope-live-validation.md)。

## 维护入口

- 运维配置：[LLM 配置](../operations/configuration.md)
- 故障与 artifact：[LLM API 兼容性运行手册](../operations/llm-api-compatibility.md)
- API 边界：[摘要接口参考](../reference/api.md)
- 实施历史：[LLM 执行架构修复记录](history/llm-execution-architecture-remediation.md)
