# LLM 执行架构修复方案

- 状态：已实施并完成确定性回归验证；可选 buffered stream 未启用
- 创建日期：2026-07-14
- 实施日期：2026-07-14
- 范围：摘要请求的交付模式、时间与 token 预算、同模型重试、attempt 证据和 provider fallback
- 不变边界：本地 JSON、来源绑定、编辑质量和发布门禁保持 fail-closed
- 发布边界：本文不授权把 `deepseek-ai/DeepSeek-V4-Pro` 加入生产 fallback

## 实施结果

- 公开摘要接口已移除伪 `stream` 参数，只保留私下收齐完整响应的 `non_stream` collector。
- `LLMExecutionPolicy` 已把输出 token、单次 timeout、provider 总预算、尝试次数和退避拆开；
  现有生产模型显式保持 `max_attempts=1`，迁移不会暗增真实调用。
- 应用层执行循环会先原子持久化每个 HTTP attempt，再按分类和双层时间预算决定是否重试；
  `empty_choices` 最多额外调用一次，`incomplete_output` 不原样重试。
- attempt artifact schema 已升级，包含序号、同模型尝试号、重试关联与决策、交付模式、有效
  timeout/token 预算、provider/run deadline 和最终选中 attempt。
- `buffered_stream` 仍是保留枚举，当前没有 collector；配置后会 fail-closed，不会自动进入生产。
- 冻结协议 fixture、执行策略单元测试、provider fallback/重试集成测试和既有 publication 回归
  共同覆盖本方案的确定性验收边界。

## 决策摘要

当前问题不是 `enable_thinking=false + stream=false` 这组选择本身错误，而是执行接口没有把
交付方式、时间预算、输出预算和重试策略表达成彼此独立、可审计的概念。

本轮修复采用以下决策：

1. 近期生产摘要只保留真实的原子非流式路径，移除没有生效的公开 `stream` 参数和当前未使用的
   `_summarize_stream()`。未来若确有 provider 证据需要流式传输，再以
   `buffered_stream` 能力重新引入；流式内容只在内存聚合，绝不边生成边发布。
2. 将 `max_output_tokens` 与 `attempt_timeout_seconds` 分开配置。前者限制模型能生成多少 token，
   后者限制系统愿意等待一次网络调用多久；二者不得互相替代。
3. SDK 继续使用 `max_retries=0`，避免不可见的重复调用。由应用层执行有界、分类、逐次留痕的
   同模型重试；每个真实 HTTP 请求都是一条独立 attempt。
4. `empty_choices` 只允许同模型额外重试一次。重复为空后立即进入下一个 provider，不等待原响应，
   也不循环到运行截止时间。
5. `finish_reason=length` 不执行原样重试。它表示输出预算已耗尽，应调整 reasoning 模式、模型级
   token 预算或任务规模，而不是延长等待时间。

## 修复前架构债务

### 1. `stream` 是伪参数

[`summarizer.summarize_result()`](../../summarizer.py) 声明 `stream: bool = True`，但函数入口立即
执行 `del stream`，请求参数随后固定为 `stream=False`。`main.py` 仍传入 `stream=True`，调用方
看到的接口语义和实际网络行为相反。

文件中保留的 `_summarize_stream()` 也不能直接启用：它只拼接并打印 `delta.content`，没有形成与
非流式路径等价的 raw envelope 校验、reasoning 隔离、`finish_reason`、usage、response hash 和
完整 `CompletionTelemetry`。简单切换到它会降低现有协议证据与隐私边界。

### 2. 时间预算与输出预算被运维讨论混为一谈

修复前请求值来自两个不同位置：

- `cfg.max_output` 决定 `max_tokens` 或 `max_completion_tokens` 的值；
- `LLMModelCapability.timeout_seconds` 或 `llm.default_timeout_seconds` 决定网络等待上限。

二者在修复前代码里已经是不同参数，但配置命名、attempt 证据和运行说明没有把差异表达完整，容易形成
“多等一会儿就能得到剩余正文”的错误判断。

[DeepSeek-V4-Pro 实验](deepseek-v4-pro-feasibility.md) 已给出反例：thinking 请求在 41.956 秒时
返回 2,001 completion tokens 和 `finish_reason=length`。此时 HTTP 响应已经结束，继续等到
180 秒不会产生新 token。相反，Non-think 的完整响应通常只需约 6–10 秒。

### 3. `retryable` 只有记录语义，没有执行语义

[`utils/llm_compat.py`](../../utils/llm_compat.py) 能对部分异常生成 `retryable`，attempt artifact
也会保存该字段；但 [`summarizer.py`](../../summarizer.py) 对每个 provider 只调用一次，请求失败
后直接进入下一个 provider。`create_client()` 同时固定 `max_retries=0`，因此修复前没有任何同模型
重试。

禁用 SDK 隐式重试是正确边界，缺少的是应用层执行器。DeepSeek 实验中同一请求先在 417ms 返回
HTTP 200 + 空 `choices`，人工复验又在 8.176 秒返回完整正文，说明 `empty_choices` 至少需要一次
有界重试机会；等待第一份已经结束的 HTTP 响应没有意义。

## 目标架构

摘要链路应拆成四个边界：

```text
模型协议能力
  └─ 参数名、thinking 控制、响应形态、可用交付模式
       ↓
模型执行策略
  └─ 输出 token、单次超时、provider 总预算、最大尝试次数、可重试错误
       ↓
Completion 收集器
  └─ non_stream；未来可选 buffered_stream
       ↓
统一解析与发布门禁
  └─ envelope → extraction → contract → provenance → quality
```

协议能力描述 provider/model/endpoint 被真实探针证明支持什么；执行策略描述本项目愿意为一次日报
付出多少时间、token 和请求次数。两者可以组合，但不能继续由一个全局 `max_output` 和一个含糊的
`stream` 布尔值代替。

### 模型执行策略

建议新增独立的 `LLMExecutionPolicy`，并由每个模型 capability 引用：

```python
class LLMExecutionPolicy(BaseModel):
    delivery_mode: Literal["non_stream", "buffered_stream"] = "non_stream"
    max_output_tokens: int | None = Field(default=None, ge=1)
    attempt_timeout_seconds: float | None = Field(default=None, gt=0, le=600)
    provider_budget_seconds: float | None = Field(default=None, gt=0, le=1200)
    max_attempts: int = Field(default=1, ge=1, le=3)
    retry_backoff_seconds: float = Field(default=1, ge=0, le=30)
    retryable_codes: tuple[str, ...] = ()
```

字段语义：

| 字段 | 单位 | 作用 | 不负责什么 |
| --- | --- | --- | --- |
| `delivery_mode` | 枚举 | 选择完整响应或私下聚合 SSE | 不改变发布门禁 |
| `max_output_tokens` | token | 限制 reasoning 与最终正文所用的模型输出预算 | 不控制网络等待时间 |
| `attempt_timeout_seconds` | 秒 | 限制单次 HTTP 请求的等待上限 | 不保证模型一定生成完整正文 |
| `provider_budget_seconds` | 秒 | 限制同模型所有尝试、退避的总耗时 | 不替代整个 run deadline |
| `max_attempts` | 次 | 限制首次请求加重试的总调用次数 | 不表示 SDK 内部重试次数 |
| `retryable_codes` | reason code | 明确当前模型允许重试的失败类别 | 不允许绕过本地质量门禁 |

`max_tokens_parameter` 仍属于协议能力，因为不同接口使用不同参数名；`max_output_tokens` 属于执行
策略，因为它是传给该参数的值。未配置模型级值时可以暂时回退到现有全局默认值，以便无行为变化
迁移，但最终生产模型应显式记录自己的输出预算。

建议的配置形态如下，仅表达目标 Schema，不代表 DeepSeek 已获生产准入：

```yaml
llm:
  capabilities:
    - provider: modelscope
      base_url: https://api-inference.modelscope.cn/v1
      model: deepseek-ai/DeepSeek-V4-Pro
      request_mode: prompt_only
      thinking_control_parameter: enable_thinking
      thinking_control_value: false
      max_tokens_parameter: max_tokens
      execution:
        delivery_mode: non_stream
        max_output_tokens: 2000
        attempt_timeout_seconds: 60
        provider_budget_seconds: 125
        max_attempts: 2
        retry_backoff_seconds: 1
        retryable_codes:
          - timeout
          - network_connection
          - rate_limit
          - http_5xx
          - empty_choices
```

上述 60/125 秒只适合作为下一轮 DeepSeek shadow 的起始值。生产值必须来自多日延迟分布，不能由
当前 6 个实验样本直接升级为 SLA。

## 交付模式修复

### 第一阶段：让接口忠于当前行为

当前日报要求拿到唯一、完整 JSON 后才能做本地校验，因此近期选择 `non_stream`：

1. 从 `summarize_result()`、`summarize()` 及其调用方移除 `stream` 参数。
2. 删除 `del stream`、调用方的 `stream=True/False` 和未使用的 `_summarize_stream()`。
3. 将 `_summarize_sync()` 重命名为表达协议结果的 `_request_non_stream_completion()`。
4. 更新 [`handbook/reference/api.md`](../reference/api.md)，不再对外宣称可选择流式输出。

这一步不改变实际生产网络请求，属于行为保持型接口修复。

### 第二阶段：仅在有证据时增加 `buffered_stream`

如果 Hy3 等 provider 的 live probe 证明标准 SSE 明显优于非流式响应，再新增
`BufferedStreamCollector`。它必须满足：

- 不向控制台打印 delta，不泄露内部 `article_id` 或未校验正文；
- 聚合所有 `delta.content`，reasoning 单独计量且永不提升为正文；
- 收集最终 `finish_reason`、usage、request-id 和可安全记录的响应 hash；
- 只有收到正常结束信号后才产生 `CompletionResult`；
- 断流、缺失结束信号和 token 截断均返回不可发布失败；
- 与非流式路径共用同一 contract、provenance、quality 和 publication gate。

流式传输只改变“响应怎样到达”，不能改变“何时允许发布”。

## 双预算修复

每次请求在发送前计算三个时间边界：

```text
attempt_deadline = min(
    now + execution.attempt_timeout_seconds,
    provider_started_at + execution.provider_budget_seconds,
    run.deadline_at,
)
```

响应一旦结束就立即解析，不增加 `sleep(180)`，也不轮询同一个 Chat Completions 响应。只有真正
返回任务 ID 的异步 job API 才适合“稍后提取”；当前同步 `/chat/completions` 不具备这一语义。

输出预算按以下规则处理：

1. `finish_reason=stop`：进入正文提取和本地门禁。
2. `finish_reason=length/max_tokens/max_output_tokens`：记录 `incomplete_output`，不原样重试。
3. thinking 消耗输出预算且正文未完成：优先使用经验证的 Non-think；若任务必须 thinking，则只提高
   该模型的 `max_output_tokens`，并重新验证成本、延迟和正文完整性。
4. 不允许为了某个 thinking 模型直接提高所有模型的全局输出上限。
5. 超时只代表本次调用没有在时间预算内完成，不能推断 token 是否充足。

## 应用层重试

### 执行顺序

建议把 provider 内部尝试提取为独立执行器，例如 `utils/llm_execution.py`。伪代码如下：

```python
for provider in providers:
    provider_deadline = bounded_provider_deadline(provider.policy, run_deadline)

    for attempt_number in range(1, provider.policy.max_attempts + 1):
        timeout = bounded_attempt_timeout(provider.policy, provider_deadline)
        attempt = request_once(provider, timeout)
        persist_attempt(attempt)

        if attempt.publishable:
            return selected_result(attempt)

        if not should_retry(attempt, attempt_number, provider.policy, provider_deadline):
            break

        bounded_backoff(provider.policy, provider_deadline)

raise AllProvidersFailed(all_attempts)
```

每次失败先持久化，再决定是否重试；进程在退避或第二次请求前退出时，第一条失败证据仍然存在。

### 重试决策表

| 失败类别 | 同模型重试 | 规则 |
| --- | --- | --- |
| `timeout`、`network_connection` | 是 | 最多一次，且必须保留 provider 与 run 剩余预算 |
| `rate_limit`、HTTP 408/409/5xx | 有条件 | `Retry-After` 能放入剩余预算时最多一次 |
| `empty_choices` | 是 | 仅 HTTP 已完成且无正文时重试一次；再次为空立即 fallback |
| `network_dns`、`network_proxy` | 默认否 | 通常是环境问题，避免重复消耗 provider 预算 |
| `authentication`、`bad_request`、`provider_unavailable` | 否 | 配置、凭据或路由问题不会因等待自动修复 |
| `protocol_invalid_json`、`protocol_multi_document` | 否 | 属于接口兼容问题，应切换已验证交付模式或 provider |
| `incomplete_output` | 否 | 需要改变 token/reasoning/任务策略，原样重试没有系统性收益 |
| `refusal`、`reasoning_only` | 否 | 不把 reasoning 当正文，也不盲目重复收费 |
| `contract`、`provenance`、`quality` | 否 | 同请求盲重试不代替提示词修复、纠错策略或人工评估 |

`retryable=true` 表示“允许策略考虑重试”，不表示“必须重试”。最终决策还必须同时满足允许的
reason code、`max_attempts`、provider 总预算和 run deadline。

SDK 的 `max_retries=0` 保持不变。这样真实调用次数、计费风险、延迟和 artifact 条目可以一一对应。
如果 provider 支持幂等键，可以作为后续单独能力验证；在此之前必须假设每次重试都会重新生成并
可能再次计费。

## Attempt 证据升级

修复前 `SummaryAttempt` 在没有同模型重试时近似表示“一次 provider 尝试”。引入重试后，必须明确
一条 attempt 就是一次真实 HTTP 请求，并增加以下非敏感字段：

```text
sequence
provider_attempt_number / provider_max_attempts
retry_of_sequence / retry_decision
delivery_mode
attempt_timeout_seconds / max_output_tokens
```

成功 artifact 还应记录 `selected_attempt_sequence`。已有 provider、model、失败层、reason code、
usage、reasoning 长度、正文长度、response hash 和质量布尔值继续保留。不得新增完整 prompt、正文、
reasoning、Authorization header 或 API key。

## 实施阶段

### Phase 1：接口语义收敛

- 修改 `summarizer.py`、`main.py` 及测试，删除公开 `stream` 参数和死代码。
- 维持生产请求实际 `stream=false`，不改变模型顺序、prompt 或发布行为。
- 更新 API reference 与运行手册。

### Phase 2：模型级执行策略

- 在 `config.py` 增加 `LLMExecutionPolicy` 及边界校验。
- 让模型级 `max_output_tokens` 覆盖全局兼容默认值。
- 分别记录单次超时、provider 总预算与整个 run deadline。
- 配置缺失时保持 `max_attempts=1`，保证迁移阶段没有隐式新增调用。

### Phase 3：可观测的同模型重试

- 新增纯策略函数 `should_retry()` 与 provider 执行循环。
- 将 `empty_choices` 标记为可由策略考虑重试，但仍受 `max_attempts` 限制。
- 每个 HTTP 请求独立写入 attempt artifact。
- 重试耗尽后沿用当前 provider fallback 与生产 fail-closed 行为。

### Phase 4：可选 buffered stream

- 仅在 live probe 证明目标 provider 的 SSE envelope、结束信号、usage 和 reasoning 可完整聚合后实施。
- 先进入 smoke/shadow，不直接替换当前非流式生产路径。
- 若没有明确收益，本阶段可以永久不实施。

### Phase 5：灰度验证

- 用冻结 fixture 覆盖 retry、预算耗尽、断流和多文档响应。
- 用 `scripts/llm_contract_smoke.py` 对候选模型做显式请求预算的真实验证。
- DeepSeek 仍需满足其评估文档中的连续多日、严格无诊断准入条件后，才能讨论生产 fallback。

## 测试矩阵

### 确定性测试

1. 代码与公开 API 中不存在被忽略的 `stream` 参数。
2. `delivery_mode=non_stream` 只发起一次非流式请求并返回完整 `CompletionResult`。
3. 模型级 `max_output_tokens` 正确覆盖全局默认，且不会改变 timeout。
4. 调整 timeout 不会改变发送的 token 上限；调整 token 上限不会改变 attempt deadline。
5. 首次 `empty_choices`、第二次成功时，artifact 顺序为 `failed → ok`，真实调用数严格为 2。
6. 连续两次 `empty_choices` 后停止当前 provider，并进入下一个 provider。
7. `finish_reason=length`、401、400、协议多文档、contract 和 quality 失败均不做同模型原样重试。
8. timeout/5xx 只有在 provider 与 run 预算允许时才执行第二次请求。
9. `max_attempts=1` 完全复现当前无同模型重试行为。
10. SDK 始终为 `max_retries=0`，artifact 条目数与真实 HTTP 调用数一致。
11. 重试成功仍必须重新通过 contract、provenance、quality 和最终 publication gate。
12. artifact 与控制台不包含密钥、完整正文、完整 reasoning 或内部请求内容。

### Live shadow

至少记录以下指标，不把小样本比例解释成 SLA：

- 首次成功率、重试恢复率、重复失败率；
- 每模型 p50/p95 延迟和 provider 总耗时；
- completion/reasoning token 分布；
- `empty_choices`、`incomplete_output`、timeout、contract、quality 分类计数；
- 首次与重试结果的严格发布通过率；
- fallback 触发率和整次 run 剩余预算。

## 验收条件

本方案只有同时满足以下条件才算完成：

1. `stream` 在公开接口中要么被删除，要么被完整实现；不得继续接受后静默忽略。
2. attempt artifact 能独立解释“等了多久”和“允许生成多少 token”。
3. `finish_reason=length` 不因增加等待时间被误判为可恢复。
4. `empty_choices` 在启用策略时最多额外请求一次，重复失败后确定性 fallback。
5. 每一次真实调用都有独立、脱敏、原子持久化的 attempt 记录。
6. provider 级预算和整个 run deadline 能阻止重试无限推迟后续 fallback。
7. 现有本地来源绑定、质量门禁、失败保留上一版 publication 的行为全部回归通过。
8. 未经 live 准入的模型、交付模式和 token 上限不会因本次重构自动进入生产。

## 回滚策略

- 将所有模型 `max_attempts` 设为 `1`，即可关闭应用层重试而不删除分类和 artifact 字段。
- 将 `delivery_mode` 设为 `non_stream`，即可停用未来的 buffered stream collector。
- 删除模型级 `max_output_tokens` 时回退到现有全局默认值。
- 回滚执行策略不能关闭本地 contract、provenance、quality 或 publication gate。
- 本次设计不改变当前 provider 顺序，因此回滚不需要修改生产 fallback。

## 明确不采用的方案

- 不在 HTTP 响应结束后固定等待 180 秒再解析；响应不会在本地对象中继续生长。
- 不把 timeout 提高到 180 秒作为 token 截断修复。
- 不启用 SDK 自动重试并同时保留应用层重试，避免调用次数失真。
- 不把未完成的流式 JSON 输出到控制台或公开文件。
- 不通过无限重试掩盖持续 provider 故障、协议不兼容或提示词质量问题。
