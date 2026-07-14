# DeepSeek-V4-Pro 日报契约系统评估

## 系统结论

截至 2026-07-14，`deepseek-ai/DeepSeek-V4-Pro` 的结论是：

> **OpenAI-compatible 协议可接入，Non-think 控制有效，但完整日报的严格发布稳定性不足；暂不加入生产 fallback。**

它与 Kimi K2.7、Hy3 的阻塞层不同：

- 不是 provider 路由问题：6/6 请求均得到 HTTP 200。
- 不是多文档 envelope 问题：响应均可解析为单个 JSON 文档。
- reasoning 隔离有效：默认模式的 reasoning 没有混入读者正文。
- 完成正文的 4 次请求全部通过 JSON 基础契约和来源 ID 溯源。
- 真正阻塞生产的是输出预算、空 choice 抖动、字段归属偏移和摘要长度不稳定。

当前不修改生产提示词、生产模型能力配置或 fallback 顺序。

## 官方能力与实验入口

当前凭证的 `GET /v1/models` 返回 55 个模型，并明确列出：

- `deepseek-ai/DeepSeek-V4-Pro`
- `deepseek-ai/DeepSeek-V4-Flash`
- `deepseek-ai/DeepSeek-V3.2`

[ModelScope 官方模型页](https://www.modelscope.cn/models/deepseek-ai/DeepSeek-V4-Pro) 给出的托管推理 ID 与本次实验一致，并说明 V4-Pro 支持 Non-think、Think High、Think Max 三种推理模式。页面的托管示例使用 `reasoning_content` 与 `content` 分栏。

V4-Pro 页面没有明确给出 ModelScope 托管服务切换 Non-think 的请求字段。同平台的 [DeepSeek-V3.2 官方示例](https://modelscope.cn/models/deepseek-ai/DeepSeek-V3.2) 使用 `extra_body.enable_thinking=false`。本轮将该字段作为显式假设探针，而不是直接写入生产配置。

## 实验设计

固定输入为 `data/2026-07-14.json` 的 14 条候选，endpoint 为 ModelScope `/v1/chat/completions`。全部请求满足：

- `stream=false`
- `request_mode=prompt_only`
- `max_tokens=2000`
- `temperature=0.2`
- 单请求超时 180 秒
- 每次命令请求预算为 1，无自动重试

共执行 6 次真实调用，覆盖默认 thinking、生产提示词、显式 Non-think、长度调优、字段调优与同请求人工复验。

DeepSeek 专用实验提示词位于 `prompts/experiments/deepseek-v4-pro-feasibility.md`，当前 SHA-256 为 `c8c992bdc986dd6c3b60d369d9e62cfbdef0527e3ccc034c0afa8569e2c214e5`。

## 逐次结果

| # | 模式 / 提示词 | HTTP / 耗时 | 协议与正文 | 本地门禁 |
| --- | --- | --- | --- | --- |
| 1 | 默认 thinking / 3 条最小契约 | 200 / 24,311 ms | 1 choice；正文 273 字符；reasoning 1,709 字符；`stop` | 3 条全部通过；因候选较多产生预期的非阻断覆盖率诊断 |
| 2 | 默认 thinking / 生产提示词 | 200 / 41,956 ms | 2,001 completion tokens；`finish_reason=length`；无完整正文 | `incomplete_output`，未进入契约层 |
| 3 | Non-think / 生产提示词 | 200 / 5,981 ms | reasoning=0；完整单文档正文；`stop` | 契约、溯源通过；3 条摘要为 29、29、25 字，质量失败 |
| 4 | Non-think / 长度调优 v1 | 200 / 9,838 ms | reasoning=0；7 条完整正文；`stop` | 宽松门禁通过；但 `discussion_topic` 被错误放入每个 item，根级值由本地默认补齐 |
| 5 | Non-think / 字段收紧 v2 | 200 / 417 ms | `choices` 为空 | `empty_choices`，无正文 |
| 6 | 与 #5 完全相同的人工复验 | 200 / 8,176 ms | reasoning=0；完整单文档正文；`stop` | 前次 `discussion_topic` 偏移未再出现，契约、溯源通过；3 条摘要为 27、29、28 字，质量失败 |

汇总：

- 路由接受率：6/6。
- 可解析单文档 envelope：6/6。
- 至少一个 choice：5/6。
- 得到完整最终正文：4/6。
- 已完成正文的契约与溯源通过率：4/4。
- 已完成正文的质量通过率：2/4；其中只有 1 次覆盖完整 7 条日报，但依赖兼容字段修复。
- 完整日报的严格无诊断发布：0 次。

样本量很小，不能把上述比例解释为 SLA；它们只用于定位系统阻塞层。

## 分层判定

| 层级 | 判定 | 证据 |
| --- | --- | --- |
| 模型路由 | 通过 | 模型在目录中，6 次均 HTTP 200 |
| HTTP envelope | 通过 | 未出现拼接多文档或错误 content type |
| Chat Completions shape | 有条件通过 | 5 次有 choice；1 次 HTTP 200 空 choice |
| reasoning 隔离 | 通过 | thinking 请求的 reasoning 与 content 分栏；Non-think 下 reasoning=0 |
| JSON 契约 | 有条件通过 | 完成正文均可解析；一次发生兼容层字段修复 |
| 来源溯源 | 通过 | 完成正文的 article ID 均来自输入 |
| 编辑质量 | 未稳定通过 | 两次完整生产输出各有 3 条低于 30 字硬门槛 |
| 生产就绪 | 不通过 | 没有严格、连续、无诊断的完整日报成功样本 |

## 模式选择

### 默认 thinking

最小三条摘要可以成功，但完整生产任务在现有 2,000 token 上限内未形成最终正文，最终以 `finish_reason=length` 结束。若继续该模式，必须增加“每模型独立输出预算”并重新评估延迟、配额与完整性；不能直接提高所有模型的全局上限。

### `enable_thinking=false`

该字段被服务端接受且产生可验证的行为差异：reasoning 从 1,709 字符降为 0，完整生成耗时约 6–10 秒，总 token 约 1,796–1,843。对日报任务应优先选择 Non-think，但它只解决预算和延迟，不自动保证摘要长度与字段归属。

## 生产准入条件

在满足以下条件前，不将 DeepSeek-V4-Pro 加入 fallback：

1. 使用固定 Non-think 能力配置，在不同日期快照上连续至少 5 次生成 7–10 条严格无诊断结果。
2. 每条摘要稳定满足 30–80 字硬门槛；建议模型提示词目标保持 38–55 字，为波动预留余量。
3. 明确 `empty_choices` 的有界重试策略，并确认重试不会掩盖持续性 provider 故障。
4. 对 `discussion_topic` 字段归属执行严格契约检查，不依赖本地默认值或忽略未知字段来宣称模型合规。
5. `json_object` 与 `json_schema` 继续保持未验证、禁用；prompt-only 成功不构成 Structured Outputs 能力证据。

满足上述条件后，候选能力配置应至少包含：

```yaml
provider: modelscope
base_url: https://api-inference.modelscope.cn/v1
model: deepseek-ai/DeepSeek-V4-Pro
supports_chat_completions: true
request_mode: prompt_only
thinking_control_parameter: enable_thinking
thinking_control_value: false
reasoning_field: reasoning_content
content_shape: string_or_blocks
max_tokens_parameter: max_tokens
supports_temperature: true
```

这段配置目前只是实验结论，不应复制进生产 `config.yaml`。

## 复现实验

```bash
.venv/bin/python scripts/llm_contract_smoke.py \
  --live \
  --data data/2026-07-14.json \
  --prompt-path prompts/experiments/deepseek-v4-pro-feasibility.md \
  --models deepseek-ai/DeepSeek-V4-Pro \
  --request-mode prompt_only \
  --no-enable-thinking \
  --request-budget 1 \
  --timeout 180
```

运行产物只保存脱敏协议遥测、校验诊断和响应哈希，不保存完整正文、reasoning 或 API 密钥。
