# ModelScope Kimi K2.7 Code 实验记录（历史）

- 实验日期：2026-07-15
- 目标模型：`moonshotai/Kimi-K2.7-Code:Moonshot`
- ModelScope endpoint：`https://api-inference.modelscope.cn/v1`
- 最终状态：完整日报契约已跑通，建议进入显式 shadow

## 实验目标

本次实验验证 ModelScope 上的 Kimi K2.7 Code 是否能够进入项目日报链路，分为三个层级：

1. 获得一次非空、可识别的最终 `content`；
2. 正确隔离强制 thinking 模型的 `reasoning_content` 与最终正文；
3. 让最终正文通过项目现有 JSON、来源绑定、中文质量和发布门禁。

实验同时要求核对 Kimi 原生 API 与 ModelScope 托管实现的差异，不把原生参数未经验证地复制到
第三方 endpoint。

## 过程概览

### 1. 官方文档与历史证据

官方资料确认：Kimi K2.7 Code 强制 thinking，不应传禁用 thinking 或自定义 temperature；推荐使用
流式交付，并分别读取 `delta.reasoning_content` 与 `delta.content`。ModelScope 模型页给出的精确
路由 ID 为 `moonshotai/Kimi-K2.7-Code:Moonshot`。

仓库 Git 历史与 2026-07-14 `.runs` artifact 表明，旧实验已经使用该精确 ID，但当时返回 HTTP 400
`provider_unavailable`，并非模型名拼写或日报提示词造成。

### 2. 路由失败与恢复

本轮最初按约定执行到 20 次 API 调用后停止，其中包括模型目录核对及 `.cn`、`.ai` endpoint 的
多种官方请求形态。K2.7 completion 当时都在生成前返回 provider 路由错误。

随后重新检查密钥配置：当前进程与项目配置加载了同一个非空 `.env` key，且失败与成功之间没有
本地 key 文件修改。再次发出最简单的官方流式请求后，模型立即成功返回 `OK`。因此本轮能够证明
路由已经恢复，但不能把恢复归因于本地代码或 key 文件变化；更可能是 provider 路由或账户授权状态
在服务端动态变化。

### 3. 协议适配

仓库原先只实现 `non_stream`，`buffered_stream` 仍是 fail-closed 的保留枚举。实验据此补充了真正的
流式聚合路径：

- `reasoning_content` 只累计长度，原文不保存、不发布；
- 只有 `delta.content` 被聚合为最终正文；
- 流结束后继续复用原有唯一 JSON、来源和质量门禁；
- reasoning-only、空 choices、refusal、截断和非终止流继续 fail-closed；
- 对该精确模型使用 `stream=true`、`max_tokens=16000`，不发送 temperature 或 thinking 开关。

### 4. 逐级验证

| 阶段 | 输入 | 结果 |
| --- | --- | --- |
| 最小调用 | `只回复 OK` | 最终 `content=OK`，reasoning/content 分离 |
| 最小日报 | 14 条候选，要求 3 条 | 3 条通过全部门禁 |
| 完整日报 | 14 条候选，生产提示词 | 8 条通过全部门禁，无诊断 |
| 稳定性 A | 前 10 条真实候选 | 7 条通过全部门禁，无诊断 |
| 稳定性 B | 后 10 条真实候选 | 7 条通过全部门禁，无诊断 |

完整生产规模连续 3 次成功，耗时约 125–155 秒。ModelScope 返回的 usage token 字段为 `0`，与
实际非空输出不符，因此本轮只把端到端耗时与 reasoning/content 字符长度作为可靠遥测。

## 代码与文档改动

- `utils/llm_compat.py`：增加安全的 buffered SSE collector；
- `summarizer.py`：按精确 capability 选择 `non_stream` 或 `buffered_stream`；
- `config.yaml`：登记 K2.7 的 endpoint-scoped capability；
- `tests/`：覆盖 reasoning 隔离、reasoning-only、未完整终止流和执行模式；
- 运维文档：说明 buffered stream 只能完整聚合后进入原有发布门禁。

默认 ModelScope 主模型与 fallback 顺序没有改变。只有显式配置 K2.7 为 primary 或 secondary 时，
上述 capability 才会生效。

## 验证结果与判断

- 相关测试：85 项通过；
- Ruff lint 与格式检查：通过；
- 全套测试：224 项通过，3 项既有 AGIHunt 时间敏感测试因固定 deadline 已过而失败，与本实验无关；
- 日报协议、来源绑定、编辑质量和发布门禁均保持 fail-closed。

当前判断为 **shadow-ready，fallback-not-ready**。主要限制是只有一个日历日的真实候选、完整生成约
2 分钟，以及同日观察到 provider 动态不可用。建议显式设置
`MODELSCOPE_SECONDARY_MODEL=moonshotai/Kimi-K2.7-Code:Moonshot`，至少连续观察 5 个不同日期后
再评估是否进入默认 fallback。

## 关联资料

- [详细 live 验证与指标](../kimi-k27-modelscope-live-validation.md)
- [Kimi K2.7 与 Hy3 旧实验](kimi-k27-hy3-feasibility.md)
- [LLM thinking、JSON 输出与代码定稿分析](llm-thinking-json-feasibility.md)
- [ModelScope Kimi K2.7 Code 模型页](https://www.modelscope.cn/models/moonshotai/Kimi-K2.7-Code/summary)
- [Kimi Thinking Mode](https://platform.kimi.ai/docs/guide/use-kimi-k2-thinking-model)
- [Kimi Streaming](https://platform.kimi.ai/docs/guide/utilize-the-streaming-output-feature-of-kimi-api)

脱敏 live artifact 位于 `.runs/llm-contract-smoke-kimi-k27-*-20260715.json`，按仓库策略不提交 Git。
