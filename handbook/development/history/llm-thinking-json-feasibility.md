# LLM thinking、JSON 输出与代码定稿可行性分析（历史）

- 状态：设计结论；不直接修改生产模型或发布门禁
- 评估日期：2026-07-15
- 评估对象：ModelScope OpenAI-compatible 主链路、ModelScope secondary 与 SiliconFlow fallback
- 证据基线：当前 `main` 工作树、2026-07-14 live smoke artifact、既有兼容性与模型实验文档

## 结论

本项目可以在**部分模型、部分 endpoint** 上开启 thinking，并让模型把最终答案放在 JSON 中；
但不能把“支持 thinking”“能输出 JSON”“严格遵守 JSON Schema”视为同一个能力。对日报生产链路，
推荐结论是：

1. **生产默认不开 thinking。** 当前日报是有来源约束的选择、压缩和改写任务，不是需要长链推理的
   数学、规划或 agent 任务。现有 Non-think 主模型已经能在约 5 秒内形成可发布的 7 条结果。
2. **thinking 只进入显式 shadow/A-B。** 只有 Non-think 在跨文章消歧、事件聚类或事实冲突判断上
   出现可量化缺陷，且 Think 相对对照组显著改善质量时，才考虑按模型启用。
3. **JSON 必须继续由本地代码兜底。** 模型只返回最小 `SummaryDraft`；本地代码解析唯一 JSON、
   校验字段和来源 ID、回填可信 URL/标题、执行中文句式与长度门禁，再确定性渲染 Markdown。
4. **Structured Outputs 不能凭参数名启用。** 当前没有一个生产模型通过“正常正例 + 冲突负例”
   证明 Schema 强制执行；因此生产继续使用 `prompt_only`，不能把 `json_schema` 当安全边界。
5. **thinking 与最终 JSON 可以共存，但必须隔离。** `reasoning_content` 只做长度/usage 遥测，
   永远不能作为日报正文；只有 `message.content` 中唯一、完整、通过本地门禁的 JSON 才能发布。

简化成一句话：**可以开，但目前没有充分理由在正式日报默认开启；可以要求 JSON，但最终日报必须由
代码定稿，而不是信任模型格式。**

## 证据范围与可信度

本文区分三种证据，优先级从高到低如下：

| 证据 | 能证明什么 | 不能证明什么 |
| --- | --- | --- |
| 当前代码与配置 | 生产实际会发送哪些参数、解析和发布哪些字段 | provider 是否真的遵守未实测参数 |
| 脱敏 live artifact | 特定 `(provider, endpoint, model)` 在某次请求中的真实行为 | 长期 SLA、其他 endpoint 或同名模型行为 |
| 官方模型页/文档 | 模型设计支持的模式、推荐调用方式 | 当前凭证和 ModelScope 托管路由一定实现相同行为 |

能力判断必须绑定 `(provider, base_url, model)`。模型卡声明、`GET /models` 有模型、HTTP 200、
一次 JSON 正例，都不足以升级生产 capability。当前能力 TTL 为 168 小时，但过期只表示要复验，
不表示自动改用猜测值。

## 当前链路已经怎样“让代码定稿”

现有实现并不是让 LLM 直接写最终 Markdown，而是下面这条受控链路：

```text
候选文章
  -> 本地压缩并分配 a1、a2 ...
  -> LLM 只返回 {items, discussion_topic}
  -> 只读取 message.content；reasoning_content 仅计量
  -> 提取唯一 JSON 对象
  -> 字段 allowlist + article_id + 中文质量校验
  -> 本地按 article_id 回填原始 title/url
  -> 代码生成编号、标点与互动话题 Markdown
  -> publication gate
```

对应代码证据：

- [`compress_articles()`](../../../summarizer.py) 在请求前分配确定性的 `article_id`，模型看不到发布 URL。
- [`model_request_options()`](../../../summarizer.py) 只发送 capability 明确允许的 thinking 或
  `response_format` 参数；不会按模型名猜能力。
- [`request_chat_completion()`](../../../utils/llm_compat.py) 先校验 HTTP body 是单一 JSON 文档；
  [`_extract_final_text()`](../../../utils/llm_compat.py) 将 reasoning 与最终 `content` 分开，拒绝
  `reasoning_only`、空 choices、refusal 和 `finish_reason=length`。
- [`extract_single_json_object()`](../../../utils/llm_compat.py) 拒绝多个根 JSON，不会猜“最后一份才是答案”。
- [`SummaryDraft`](../../../utils/summary_contracts.py) 只接受模型生成的 `article_id`、`summary` 和
  `discussion_topic`；[`_parse_summary_result()`](../../../summarizer.py) 再从本地输入绑定标题和 URL。
- [`validate_summary_result()`](../../../utils/summary_contracts.py) 限制条数、来源 ID、URL、单句、
  30–80 可见字符和完整句末标点。
- [`render_summary_markdown()`](../../../utils/summary_contracts.py) 负责编号和最终读者文本，模型不负责
  Markdown、链接或展示格式。

因此，用户设想的“让模型输出 JSON，再用代码规则把最后日报清晰定稿”不仅可行，而且已经是当前
架构主体。后续应强化这条边界，而不是重新让模型输出 Markdown。

## thinking 和 JSON 是两条独立轴

### thinking 控制的是求解过程

thinking 决定模型是否在最终答案前消耗额外推理 token。它可能帮助复杂消歧和多约束选择，但也会
增加延迟、token、截断和 provider 特有协议的风险。官方 Qwen 文档说明 Qwen3 默认可思考并可用
`enable_thinking` 切换；Qwen3.5 默认思考且不支持 `/think`、`/nothink` 软切换，需要 API 参数。
[Qwen3 模型页](https://modelscope.cn/models/Qwen/Qwen3-4B)；
[Qwen3.5 模型页](https://modelscope.cn/models/Qwen/Qwen3.5-4B)。

### JSON 控制的是最终答案形状

JSON 有三个强度不同的层级：

| 模式 | provider 约束 | 本地仍需做什么 | 当前生产结论 |
| --- | --- | --- | --- |
| `prompt_only` | 只有提示词约束 | 唯一 JSON、字段、类型、来源和质量全部校验 | 当前默认，证据最完整 |
| `json_object` | 通常只保证 JSON 对象 | 仍需 Schema、来源和质量校验 | 目标模型未形成启用证据 |
| `json_schema` | 理想情况下强制指定 Schema | 仍需来源、事实和质量校验 | 当前均未证明强制执行 |

即使 provider 严格执行 JSON Schema，也只能保证字段和类型，不能保证摘要事实来自对应文章、同一事件
没有重复、中文句子可读或讨论话题合适。因此本地 provenance/quality gate 不能删除。

### 两者可以组合，但不互相担保

可发送 `enable_thinking=true + response_format=json_schema` 不等于组合可靠。必须分别证明：

1. thinking 参数在精确 endpoint/model 上产生可观测行为；
2. reasoning 与 `content` 分栏且最终正文完整；
3. JSON 模式稳定返回非空 choice；
4. 冲突负例仍被 Schema 强制纠正；
5. 最终结果通过本地来源与质量门禁。

任一项失败都应保持 `prompt_only` 或关闭 thinking。

## 当前模型逐项判定

| 模型 / 路由 | thinking 证据 | JSON 证据 | 当前判定 |
| --- | --- | --- | --- |
| ModelScope `ZhipuAI/GLM-5.2` | 当前显式 `enable_thinking=false`；成功样本 reasoning=0 | prompt-only 可发布；`json_object`、`json_schema` 曾返回空 choices | **生产保持 Non-think + prompt-only**；没有开 Think 的对照证据 |
| ModelScope `Qwen/Qwen3.5-397B-A17B` | 未发送控制字段的 live 样本有 15,214 字符 reasoning、约 79.9 秒 | prompt-only 8 条通过 | 可确认默认请求进入了推理形态；仅适合 shadow，需先验证开关和预算 |
| ModelScope `Qwen/Qwen3.5-35B-A3B` | live artifact 有 18,495 字符 reasoning、70,406 ms、7,010 completion tokens | prompt-only 7 条通过 | 技术上可得到 Think + JSON；成本/延迟高，且样本过少，不准默认生产 |
| ModelScope `Qwen/Qwen3-235B-A22B-Instruct-2507` | 官方定义为仅 Non-thinking，无需 `enable_thinking=false` | 正常 `json_schema` 请求通过，但冲突探针 HTTP 200 空 choices | **不能开 Think**；Structured Outputs 未证明强制执行，保持 prompt-only |
| ModelScope `deepseek-ai/DeepSeek-V4-Pro`（实验） | 默认 Think 的 3 条最小任务成功；完整生产任务在 2,000 token 时 `length`；Non-think 快约 6–10 秒 | 完整正文均能解析，但质量/字段归属不稳定 | 能切换，但日报优先 Non-think；未达到 fallback 准入条件 |
| ModelScope `moonshotai/Kimi-K2.7-Code:Moonshot`（实验） | 强制 thinking；流式样本 reasoning 6,920–15,441 字符并与正文隔离 | prompt-only 完整生产契约连续 3 次通过 | 可进入显式 shadow；跨日稳定性和约 2 分钟延迟尚不足以默认 fallback |
| ModelScope `Tencent-Hunyuan/Hy3`（实验） | 无可用正文证据 | 两次 HTTP 200 均为拼接多 JSON 文档 | envelope 不兼容；thinking/JSON 均不能进入生产判断 |
| SiliconFlow `Pro/moonshotai/Kimi-K2.6` | 当前无 endpoint-scoped capability，代码不会发送 thinking 控制 | 只使用 prompt-only 安全默认值 | 不应猜测；必须对 SiliconFlow 精确路由单独探针 |

Qwen3.5 的模型卡同时说明默认 thinking 和 API 参数切换方式，但不同托管服务的参数形状可能不同；
例如自托管 vLLM/SGLang 示例会把开关放进 `chat_template_kwargs`，云 API 可能直接使用
`enable_thinking`。这正是生产配置必须以精确 endpoint live probe 为准的原因。
[Qwen3.5-397B-A17B 官方模型页](https://modelscope.cn/models/Qwen/Qwen3.5-397B-A17B)。

`Qwen3-235B-A22B-Instruct-2507` 官方模型页明确说明它只支持 Non-thinking；不能因为 capability
模型里存在通用 `thinking_control_parameter` 字段，就给这个模型硬塞开关。
[官方模型页](https://modelscope.cn/models/Qwen/Qwen3-235B-A22B-Instruct-2507)。

DeepSeek V4 官方模型页列出 Non-think、Think High、Think Max 三档，并展示 reasoning 与最终答案
分离的托管示例；但 ModelScope 页面没有为本项目精确说明三档对应的全部托管请求字段，所以当前只把
`enable_thinking=false` 的实测差异视为有效证据，不推断 High/Max 配置。
[DeepSeek-V4-Pro 官方模型页](https://modelscope.cn/models/deepseek-ai/DeepSeek-V4-Pro)。

## 为什么不建议日报默认开 thinking

### 1. 当前瓶颈主要不是逻辑推理

日报任务的困难集中在来源真实性、事件去重、条数、长度、中文完整句和字段归属。这些约束中多数由
本地代码确定性执行更可靠。现有 GLM Non-think 样本已经以 5,245 ms、210 completion tokens 生成
7 条可发布结果；Qwen3.5-35B 的 thinking 样本则用了 70,406 ms、7,010 completion tokens。
二者不是同模型 A/B，不能直接算质量收益，但足以说明默认 Think 会引入显著预算风险。

### 2. reasoning 与最终正文竞争输出预算

DeepSeek V4 的完整生产提示词在默认 Think 下达到 2,001 completion tokens 后以
`finish_reason=length` 结束，没有完整最终正文；延长 HTTP timeout 不会让已经结束的响应继续生成。
若必须开 Think，应提高**该模型独立的**输出预算并重新验证，不能提高所有 provider 的全局上限。

### 3. thinking 不修复协议和 Schema

Kimi 曾出现 provider route 动态不可用、Hy3 返回多文档 envelope、Qwen Instruct 的 Schema 冲突探针为空
choices，这些都发生在提示词质量之外。Think 本身不会修复 HTTP 路由、响应 framing 或 provider 对
`response_format` 的实现。

### 4. 隐藏推理不能成为发布依赖

项目不保存完整 reasoning，也不把它写入公开日报。这样既避免泄漏内部推理/输入细节，也使重放和
发布只依赖稳定的最终契约。若 provider 只返回 reasoning，没有 `content`，必须 fail-closed。

## 什么情况下允许开 thinking

某个模型只有同时满足以下门槛，才能从实验升级为日报 Think 候选：

1. **任务门槛**：先定义 Non-think 的具体失败，例如跨来源事件聚类准确率不足；不能用“可能更聪明”
   作为开启理由。
2. **协议门槛**：精确 `(provider, base_url, model)` 的 `enable_thinking=true` 被接受，且至少一个
   对照请求证明 reasoning 长度或 token 明显变化。
3. **隔离门槛**：reasoning 与最终 `message.content` 分离；正文不存在 `<think>`、多个 JSON 或
   reasoning-only。
4. **完整性门槛**：7–10 条生产规模下 `finish_reason=stop`，没有 empty choices、截断或多文档。
5. **契约门槛**：最终正文通过唯一 JSON、字段 allowlist、`article_id` 来源绑定和全部质量规则。
6. **收益门槛**：在相同日期快照、提示词、采样配置下与 Non-think 做配对 A/B；至少连续 5 个日期，
   由重复率、错误来源率、事实支持率和人工可读性证明有实际增益。
7. **预算门槛**：p95 延迟、completion/reasoning tokens、单次费用和失败回退仍落在 run deadline 与
   provider budget 内；Think 失败不得阻止已验证 Non-think fallback。
8. **运维门槛**：capability 写明验证时间、样本数、thinking 参数和模型级输出预算；过期后回到
   shadow，不自动沿用。

这组门槛适合复杂事件聚类或证据冲突判断。普通标题改写、固定长度中文摘要、编号和 Markdown 渲染
不满足开启理由。

## 推荐目标架构

### 模型职责

模型只做三件事：

1. 从候选中选择可被输入支持的不同事件；
2. 返回原样 `article_id`；
3. 为每个事件生成一条完整中文事实句，并给一个互动问题。

最小模型输出保持现状即可：

```json
{
  "items": [
    {
      "article_id": "a1",
      "summary": "一条由对应标题或描述直接支持的完整中文事实句。"
    }
  ],
  "discussion_topic": "你最关注哪条AI新闻？"
}
```

不要让模型输出序号、Markdown、URL、展示标题、provider/model、抓取时间或发布状态。它们要么来自
可信本地数据，要么属于展示层。

### 代码职责

代码继续独占以下决定：

- 候选 ID 分配、最大候选数和最大日报条数；
- 只接受唯一 JSON 根对象和 allowlist 字段；
- `article_id -> 原标题/URL` 的可信回填；
- 未知 ID、错 URL、空项、超限、截断和 refusal 的阻断；
- 30–80 字、单句、句末标点、冒号/省略号等公开质量规则；
- 编号、Markdown、互动话题默认值和 HTML 构建；
- attempt artifact、provider fallback 和 publication 原子切换。

如果以后增加“主体配额、事件簇去重、AI 相关度阈值”，也应优先在模型前后的代码层实现；模型可以
提供候选判断，但不能拥有最终发布权。

## 当前实现缺口

现有架构方向正确，但在正式支持 Think 前还有四个缺口：

1. `LLMModelCapability` 只有一个通用 `thinking_control_parameter/value`，能表达简单布尔开关，不能
   清晰表达 `unsupported`、`forced`、`optional`、High/Max 或 `thinking_budget`。
2. Qwen3.5 两个 capability 没有显式 thinking 策略；当前请求会依赖 provider 默认值。已有 artifact
   证明它们可能产生大量 reasoning，这种隐式默认不适合长期生产。
3. artifact 能记录 `reasoning_length` 和 provider 返回的 `reasoning_tokens`，但部分 provider 不回传
   后者；成本门禁需要同时以 completion tokens、reasoning 长度和延迟做保守判断。
4. live smoke 可以切换 `--enable-thinking`，但尚未自动生成同模型 Think/Non-think 配对报告，也没有
   事实支持率、重复率和人工评分聚合。

建议后续仅在要开展 Think A/B 时增加显式能力字段，例如：

```yaml
thinking:
  mode: optional          # unsupported / forced / optional
  control_parameter: enable_thinking
  enabled_value: true
  disabled_value: false
  budget_parameter: thinking_budget
  budget_tokens: 4096
```

这只是目标表达。字段名和嵌套位置必须由目标 endpoint 的 live probe 决定，不能把 Qwen、DeepSeek、
ModelScope、自托管 vLLM 和 SiliconFlow 的参数形状互相复制。

## 验证方案

### Think / Non-think 配对探针

同一个模型、日期快照和实验提示词分别执行，显式限制每条命令只发一次请求：

```bash
.venv/bin/python scripts/llm_contract_smoke.py \
  --live \
  --data data/2026-07-14.json \
  --models '<精确模型ID>' \
  --request-mode prompt_only \
  --enable-thinking \
  --request-budget 1

.venv/bin/python scripts/llm_contract_smoke.py \
  --live \
  --data data/2026-07-14.json \
  --models '<精确模型ID>' \
  --request-mode prompt_only \
  --no-enable-thinking \
  --request-budget 1
```

比较 `elapsed_ms`、`reasoning_length`、completion/reasoning tokens、`finish_reason`、item count、
diagnostics 和 publishable。完整响应与 reasoning 不落盘。

### Structured Outputs 独立探针

Schema 必须另外验证，不能复用 Think 成功作为证据：

```bash
.venv/bin/python scripts/llm_contract_smoke.py \
  --live \
  --models '<精确模型ID>' \
  --request-mode json_schema \
  --schema-conflict \
  --request-budget 2
```

只有日报正例 `publishable` 且冲突负例为 `enforced`，才允许考虑把 `request_mode` 改为
`json_schema`。即使升级，也保留全部本地校验。

### 生产前验收

至少使用 5 个不同日期的冻结候选快照，每日做配对请求。建议硬门槛：

- 生产规模完整正文成功率 100%；
- contract/provenance/quality 全部通过且无兼容修复 diagnostics；
- 未知来源 ID、重复事件和无来源事实为 0；
- Think 相对 Non-think 在预先定义的质量指标上有一致增益；
- p95 能进入模型级 timeout/provider budget，且不会挤占整个 20 分钟 run deadline；
- 失败时按既有策略 fallback，不能把 reasoning 或 offline 结果冒充在线模型正文。

## 最终决策

当前生产配置维持：

- `ZhipuAI/GLM-5.2`：`enable_thinking=false`、`prompt_only`；
- `Qwen3.5`：不作为隐式 Think 生产默认；若作为 secondary，先补显式开关和配对证据；
- `Qwen3-235B-A22B-Instruct-2507`：按官方能力只使用 Non-think；
- DeepSeek V4、Hy3：保持实验/禁用结论；Kimi K2.7 仅进入显式 shadow，不改默认 fallback；
- SiliconFlow Kimi K2.6：维持安全默认，不推断 thinking 或 Structured Outputs 能力。

最终日报继续采用“LLM 生成最小 JSON 草稿 + 本地代码确定性定稿”。只有未来证据证明某个复杂的
语义步骤在 Think 下稳定变好，才为该模型、该 endpoint 单独开启；不做全局 `think=true`。

## 关联历史文档

- [LLM API 兼容性与输出契约改造计划](llm-api-compatibility-plan.md)
- [LLM API 兼容性运行手册](../../operations/llm-api-compatibility.md)
- [LLM 执行架构](../llm-execution.md)
- [DeepSeek-V4-Pro 日报契约系统评估](deepseek-v4-pro-feasibility.md)
- [Kimi K2.7 与 Hy3 日报契约可行性实验](kimi-k27-hy3-feasibility.md)
- [日报正式与灰度产物质量审计](../../quality/daily-product-quality-audit.md)
