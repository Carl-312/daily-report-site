# Kimi K2.7 与 Hy3 日报契约可行性实验（历史）

> 历史结论（2026-07-14）：本文保留当日非流式探针事实。Kimi K2.7 的 ModelScope 路由已于
> 2026-07-15 恢复，并通过 buffered stream 完整日报验证；最新结论见
> [ModelScope Kimi K2.7 Code 流式日报契约验证](../kimi-k27-modelscope-live-validation.md)。Hy3 结论未变。

## 结论

截至 2026-07-14，这两个模型都不应加入生产 fallback：

- `moonshotai/Kimi-K2.7-Code:Moonshot` 在当前 ModelScope endpoint 与凭证下返回 HTTP 400 `provider_unavailable`，请求没有进入模型正文层。提示词无法修复 provider 路由不可用。
- `Tencent-Hunyuan/Hy3` 两次返回 HTTP 200，但响应体均为多个拼接 JSON 文档，分类为 `protocol_multi_document`，没有可安全提取的最终正文。提示词无法修复 HTTP envelope。
- 独立实验提示词通过了 `ZhipuAI/GLM-5.2` 阳性对照，因此目标模型失败不能归因于提示词本身无效。

本轮不修改生产提示词、生产模型能力声明或发布门禁。

## 实验提示词

提示词位于 `prompts/experiments/kimi-k2.7-hy3-feasibility.md`。它专门验证以下最小可发布契约：

- 非流式响应只含一个 JSON 文档；
- 根对象只含 `items` 与 `discussion_topic`；
- 三条摘要对象全部位于同一个 `items` 数组；
- 不混入 reasoning、模板、草稿、Markdown、SSE 或第二份修订结果；
- 本地继续执行 JSON、来源 ID、中文摘要长度和完整句校验。

最终提示词 SHA-256 指纹为 `bf0c10c955c598776362f24446d80215a05ccdd79fc6f37fad008d9d2f1d6639`。

## 模型与入口核对

当前凭证查询 `GET /v1/models` 得到 55 个模型，其中匹配项只有：

- `moonshotai/Kimi-K2.5`
- `Tencent-Hunyuan/Hy3`

目录没有列出 K2.7；[ModelScope 的 Kimi K2.7 页面](https://www.modelscope.cn/models/moonshotai/Kimi-K2.7-Code/summary) 给出的托管推理 ID 是 `moonshotai/Kimi-K2.7-Code:Moonshot`，所以实验使用该精确 ID。K2.7 强制 thinking，本地适配器只读取最终 `content`，不会把 `reasoning_content` 提升为正文。

## 实验结果

输入固定为 `data/2026-07-14.json` 的 14 条候选；全部请求使用 `stream=false`、`prompt_only`、180 秒超时和单次请求预算。总计执行 6 次真实调用，没有自动重试。

| 用途 | 模型 | 提示词 | HTTP / 耗时 | 结果 |
| --- | --- | --- | --- | --- |
| 目标探针 | `moonshotai/Kimi-K2.7-Code:Moonshot` | v1 | 400 / 315 ms | `provider_unavailable`；无正文、无 reasoning |
| 目标探针 | `Tencent-Hunyuan/Hy3` | v1 | 200 / 47,671 ms | `protocol_multi_document`；无可提取正文 |
| 路由对照 | `moonshotai/Kimi-K2.5` | v1 | 400 / 501 ms | `provider_unavailable`；说明当前 Moonshot 托管路由整体不可用 |
| 提示词对照 | `ZhipuAI/GLM-5.2` | v1 | 200 / 6,352 ms | 正文包含多个 JSON 值，促成提示词消歧 |
| 阳性对照 | `ZhipuAI/GLM-5.2` | 最终版 | 200 / 2,986 ms | 3 条摘要全部通过 contract、provenance 与 quality 门禁 |
| 最终复验 | `Tencent-Hunyuan/Hy3` | 最终版 | 200 / 43,056 ms | 仍为 `protocol_multi_document`；排除 v1 歧义影响 |

阳性对照的最终响应只有一个 choice，`content_length=264`、`reasoning_length=0`、`finish_reason=stop`，共计 1,546 tokens。由于实验只要求 3 条，出现非阻断诊断 `quality_item_coverage` 符合预期。

## 可适配边界

### Kimi K2.7

当日结论是“路由阻塞，提示词层尚不可评估”，不是“模型不遵循 JSON”。2026-07-15 路由恢复后，
Kimi 已按第二种路径完成流式复验并进入显式 shadow 候选；以下条件保留为当时的复验标准：

1. K2.7 出现在当前凭证的 `/v1/models` 目录并可接受请求；
2. 配置一个确实提供 K2.7 的 Moonshot 或其他 OpenAI-compatible endpoint。

复验时继续使用最终实验提示词，并单独记录强制 thinking 的 reasoning 长度、最终正文完整性和 token 上限。

### Hy3

当前结论是“模型请求被接受，但 ModelScope 非流式 envelope 不兼容”。不得直接取拼接响应的最后一个 JSON，因为这会掩盖上游协议异常，且无法证明前序文档与最终文档属于同一可靠完成。

后续可行方向按优先级为：

1. 等待 ModelScope 修复 `stream=false` 的单文档响应；
2. 在隔离实验中验证 `stream=true` 是否提供标准 SSE，并完整聚合 delta 后再走本地门禁；
3. 使用 Hy3 官方建议的 vLLM/SGLang 自托管 OpenAI-compatible endpoint，再复用同一提示词和本地验证器。

在上述任一路径得到可重复的单文档正文证据前，Hy3 保持生产禁用。

## 复现实验

```bash
.venv/bin/python scripts/llm_contract_smoke.py \
  --live \
  --data data/2026-07-14.json \
  --prompt-path prompts/experiments/kimi-k2.7-hy3-feasibility.md \
  --models 'moonshotai/Kimi-K2.7-Code:Moonshot' 'Tencent-Hunyuan/Hy3' \
  --request-mode prompt_only \
  --request-budget 2 \
  --timeout 180
```

运行产物只保留脱敏遥测和哈希，不保存完整模型正文、reasoning 或 API 密钥。
