# ModelScope Kimi K2.7 Code 流式日报契约验证

- 验证日期：2026-07-15（Asia/Shanghai）
- endpoint：`https://api-inference.modelscope.cn/v1`
- ModelScope 模型 ID：`moonshotai/Kimi-K2.7-Code:Moonshot`
- 结论：完整日报契约已连续通过；可进入显式 shadow，暂不升级默认 fallback

## 结论

Kimi K2.7 Code 已在当前 ModelScope 凭证和 endpoint 上跑通：

1. 最小流式请求得到非空、可识别的最终 `content=OK`；
2. `reasoning_content` 与最终 `content` 在 SSE 聚合过程中保持隔离；
3. 3 条最小日报通过 JSON、来源绑定与中文质量门禁；
4. 14 条完整候选生成 8 条日报，完整通过现有生产契约；
5. 前 10 条与后 10 条两个真实候选窗口又分别生成 7 条，连续通过且无诊断。

因此，旧结论“当前 ModelScope 路由不可用”已经过期。新的边界是：协议和日报质量已证明可行，
但目前只有一个日历日的真实候选，且完整生成耗时约 125–155 秒，ModelScope provider 还曾在同日
动态返回 `provider_unavailable`。这些证据足以进入 shadow，不足以直接成为默认生产 fallback。

## 官方协议映射

| 维度 | Kimi 原生 API | ModelScope 托管入口 | 本项目实现 |
| --- | --- | --- | --- |
| 模型 ID | `kimi-k2.7-code` | `moonshotai/Kimi-K2.7-Code:Moonshot` | capability 按 endpoint/model 精确匹配 |
| 接口 | `/v1/chat/completions` | OpenAI-compatible `/v1/chat/completions` | OpenAI SDK，禁用 SDK 自动重试 |
| thinking | 强制开启，不应传 `thinking=disabled` | 页面示例分别读取 reasoning/content delta | 不发送 thinking 开关 |
| temperature | K2.7 不可修改 | 页面示例不传 | `supports_temperature=false` |
| 交付 | 官方建议 `stream=true` | 模型页示例使用 `stream=true` | `buffered_stream` 私下完整聚合 |
| 输出预算 | 官方建议至少 16,000 | 页面未声明更小安全值 | 模型级 `max_tokens=16000` |
| 最终正文 | `delta.content` | `delta.content` | 只有聚合后的 content 可进入门禁 |
| reasoning | `delta.reasoning_content` | `delta.reasoning_content` | 只记录长度，原文不保存、不发布 |

官方依据：

- [ModelScope Kimi K2.7 Code 模型页](https://www.modelscope.cn/models/moonshotai/Kimi-K2.7-Code/summary)
- [Kimi Thinking Mode](https://platform.kimi.ai/docs/guide/use-kimi-k2-thinking-model)
- [Kimi Chat Completions](https://platform.kimi.ai/docs/api/chat)
- [Kimi Streaming](https://platform.kimi.ai/docs/guide/utilize-the-streaming-output-feature-of-kimi-api)
- [ModelScope API-Inference 限额与模型覆盖](https://www.modelscope.cn/docs/model-service/API-Inference/limits)

Moonshot 原生参数只用于解释模型行为；本项目没有把原生 API 的 `thinking`、JSON Mode 或其他参数
未经实测复制到 ModelScope。当前只启用 `prompt_only + buffered_stream`，Structured Outputs 仍保持
未验证状态。

## 旧 `provider_unavailable` 的定位

Git 历史与 2026-07-14 artifact 已证明，旧请求使用的就是模型页给出的精确 ID，并非简单拼写错误。
2026-07-15 本轮开始时，当前凭证的 `/v1/models` 仍只列出 55 个模型且 Kimi 匹配项只有 K2.5；
精确 K2.7 的 `.cn` 和 `.ai` 流式调用都返回 HTTP 400 provider 路由错误。

按用户要求累计 20 次 API 调用后停止，随后用户要求重新检查密钥并再试。检查结果显示：

- 当前进程与配置都加载了 `.env` 的同一非空 ModelScope key；
- `.env` 在失败批次与成功批次之间没有发生本地修改；
- 再次发出的最小 K2.7 流式请求随即成功。

因此不能把恢复归因于本地模型 ID、提示词、stream 参数或 key 文件修改。最符合证据的解释是
ModelScope/Moonshot provider 路由或账户授权状态在服务端动态恢复；这是推断，不是服务端根因声明。
目录缺少 K2.7 也不能再作为不可调用的充分条件，因为后续精确路由 ID 已成功返回正文。

## Live 结果

所有响应正文与 reasoning 原文均未落盘；artifact 只保留长度、哈希、状态和门禁结果。

| 样本 | 输入 | 输出 | 耗时 | reasoning / content 字符 | 结果 |
| --- | ---: | ---: | ---: | ---: | --- |
| 最小连通 | `只回复 OK` | `OK` | 1.6 秒 | 179 / 2 | 非空最终正文 |
| 最小日报 | 14 条候选，实验提示词要求 3 条 | 3 条 | 56.3 秒 | 6,920 / 304 | 全门禁通过；仅有预期 coverage 诊断 |
| 完整日报 | 14 条候选，生产提示词 | 8 条 | 154.7 秒 | 15,408 / 647 | 全门禁通过，无诊断 |
| 稳定性 A | 前 10 条真实候选 | 7 条 | 125.1 秒 | 15,441 / 617 | 全门禁通过，无诊断 |
| 稳定性 B | 后 10 条真实候选 | 7 条 | 126.4 秒 | 12,128 / 585 | 全门禁通过，无诊断 |

完整生产规模为 3/3 连续成功，均满足：HTTP 200、单 choice、`finish_reason=stop`、唯一 JSON、
已知 `article_id`、本地可信 URL/标题绑定、7–10 条、30–80 字完整中文句和发布门禁。

ModelScope 流式响应在本轮把 usage token 字段报告为 `0`，与实际非空输出矛盾；因此当前不能用该
usage 值做成本门禁，先保留 reasoning/content 字符长度和端到端耗时作为保守遥测。

脱敏证据：

- `.runs/llm-contract-smoke-kimi-k27-buffered-minimal-20260715.json`
- `.runs/llm-contract-smoke-kimi-k27-buffered-full-20260715.json`
- `.runs/llm-contract-smoke-kimi-k27-head10-20260715.json`
- `.runs/llm-contract-smoke-kimi-k27-tail10-20260715.json`

`.runs/` 按仓库策略保持私有且被 Git 忽略。

## 实现与安全边界

`utils/llm_compat.py` 新增 provider-neutral buffered stream collector：

- 按 choice index 聚合 `delta.content`；
- reasoning 只累计长度，原文立即丢弃；
- refusal、空 choices、reasoning-only、截断和不支持的内容形状继续 fail-closed；
- 完整聚合后复用原有最终正文提取器，再进入唯一 JSON 与日报门禁；
- 只保存完整 SSE 的 SHA-256，不保存正文或 reasoning。

`summarizer.py` 现在按精确 capability 选择 `non_stream` 或 `buffered_stream`。公开摘要 API 没有恢复
旧的伪 `stream` 参数，调用方也不能边生成边发布。默认模型顺序未改变；Kimi capability 只有在显式
把该模型配置为 ModelScope primary/secondary 时才会使用。

## 准入判断

当前判定为 **shadow-ready，fallback-not-ready**：

- 可行性：已达到，完整契约连续 3 次成功；
- 安全性：已达到，reasoning/content 隔离且所有本地门禁保留；
- 稳定性：仅覆盖同一日三个候选窗口，尚未覆盖多日和 provider 波动；
- 性能：完整样本约 2.1–2.6 分钟，能进入 20 分钟 run deadline，但明显慢于当前 Non-think 主模型；
- 运维：同日出现过 provider 动态不可用，不能删除已验证 fallback。

建议以 `MODELSCOPE_SECONDARY_MODEL=moonshotai/Kimi-K2.7-Code:Moonshot` 做显式 shadow，至少连续
5 个不同日期记录成功率、p95 延迟、reasoning/content 长度和质量诊断。达到跨日 100% 完整契约通过、
无来源错误且延迟可接受后，再讨论生产 fallback；本轮不修改默认模型顺序。
