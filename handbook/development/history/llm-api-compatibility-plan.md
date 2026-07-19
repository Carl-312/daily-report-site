# LLM API 兼容性与输出契约改造计划（历史）

- 状态：实施中；`feat/llm-api-compatibility` 已完成协议/attempt 核心与首轮 live 验证，长期质量样本和小流量观察仍待后续完成
- 创建日期：2026-07-14
- 范围：提示词、OpenAI-compatible Chat Completions、JSON 契约、响应解析、中文质量、条数、字数、标点、来源映射、模型回退和回归验证
- 生产边界：本计划不授权降低现有发布质量门槛；Phase 0–2 仅增加证据、分类和影子判定
- 安全边界：不记录或输出密钥；离线、人工复核和合成 fixture 不得标记为真实 API 成功

## 结论

当前摘要链路已经具备两个正确的基础：生产在线模式在模型失败时保持 fail-closed，且
`required_ai`、`offline`、人工复核结果有独立 provenance。主要问题不在于“质量要求过高”，
而在于网络、鉴权、provider 路由、响应协议、正文提取、JSON 结构和编辑质量被压缩成相近的
异常语义。

这会产生两类风险：

1. HTTP/API 已完成但没有可发布正文时，被笼统记录成 `SummaryQualityError` 或 provider 失败。
2. 模型返回了可用中文正文，却因未展示的英文 `title`、29 字完整句、合法冒号、额外无害字段
   等实现细节被误拒绝。

推荐顺序是先建立分层 attempt 证据和 provider capability 探针，再以影子模式比较候选解析与
质量规则。只有真实样本证明事实准确率、重复率和可读性不下降后，才允许逐项调整非必要格式
门槛。

## 目标与非目标

### 目标

1. 将一次模型尝试拆分为传输、HTTP、envelope、正文提取、JSON 契约、来源映射和编辑质量七层结果。
2. 即使所有 provider 都失败，也保留可脱敏、可重放、可聚合的 attempt 证据。
3. 支持不同 OpenAI-compatible provider 的推理字段、正文形态、结构化输出能力和错误差异。
4. 保留来源映射、公开内容安全、事实完整性和 AI provenance 等真正的质量底线。
5. 用多个真实模型、冻结响应 fixture 和编辑质量样本共同验证兼容性改动。
6. 让生产发布只消费已验证的最终正文，不将 reasoning、离线或人工内容冒充为模型输出。

### 非目标

- 本计划不引入自动“修好”事实内容的第二个 LLM。
- 不把 provider 返回 HTTP 200、接受 `response_format` 或列出模型 ID 视为能力已验证。
- 不在常规单元测试或每次 CI 中消费真实模型额度。
- 不允许解析器从多个 JSON 对象中猜选一个结果。
- 不因兼容性改造降低 `article_id`、本地 URL 映射或发布 provenance 的约束。

## 当前实现边界

摘要链路的主要位置如下：

| 位置 | 当前职责 | 审计结论 |
| --- | --- | --- |
| [`prompts/daily.md`](../../../prompts/daily.md) | 要求模型只返回 JSON，并描述条数、中文、字数、标点和来源规则 | 同时包含质量目标与具体渲染实现约束 |
| [`summarizer.py`](../../../summarizer.py) | provider 回退、请求、正文提取、JSON 解析和首次质量校验 | 多层失败共用相近异常；只读取 `choices[0].message.content` |
| [`utils/summary_contracts.py`](../../../utils/summary_contracts.py) | Pydantic 模型、可见字符规则、来源复核和确定性 Markdown 渲染 | 本地 Schema 严格，但没有发送给 provider |
| [`main.py`](../../../main.py) | 在线/离线策略、持久化、发布前复核 | 在线失败后拒绝自动离线替代；显式离线仍可发布并保留 policy |
| [`scripts/modelscope_smoke.py`](../../../scripts/modelscope_smoke.py) | ModelScope 最小连通性和错误分类 | 只验证主模型有非空正文，不验证日报契约 |
| [`scripts/agihunt_trending_gray.py`](../../../scripts/agihunt_trending_gray.py) | 隔离的 AI/offline/reviewed 灰度和 provenance 检查 | 已明确禁止把 offline/reviewed 标为 AI |

当前 Pydantic `SummaryDraft` 生成的 Schema 具有以下特征：

- 顶层只允许 `items`、`discussion_topic`，`additionalProperties=false`。
- 每条 item 必须同时包含 `article_id`、`title`、`summary`。
- item 同样设置 `additionalProperties=false`。
- 该 Schema 仅用于 `model_validate_json()`；当前请求没有 `response_format`。

因此，现状是“prompt-only JSON + 严格本地解析”，不是 provider 原生 Structured Outputs。

## 成功与失败的分层语义

不得继续用一个布尔值同时表示 API 成功和内容可发布。目标状态流为：

```text
传输连接
  → HTTP / 鉴权 / 配额 / provider 路由
  → OpenAI-compatible envelope
  → choices 与最终正文提取
  → JSON 结构契约
  → article_id 与本地来源映射
  → 中文、条数、字数、标点、重复和事实质量
```

| 层 | 成功条件 | 典型失败码 | 是否允许进入下一层 |
| --- | --- | --- | --- |
| transport | 请求得到 HTTP 响应 | `network_dns`、`network_proxy`、`timeout` | 否 |
| HTTP/provider | 2xx 且不是鉴权、配额或路由错误 | `authentication`、`rate_limit`、`provider_unavailable`、`http_5xx` | 否 |
| envelope | 恰好一个合法响应文档，字段形态可识别 | `protocol_invalid_json`、`protocol_multi_document`、`protocol_wrong_content_type` | 否 |
| extraction | 至少一个 choice，存在非空最终正文 | `empty_choices`、`missing_message`、`reasoning_only`、`refusal`、`incomplete_output` | 否 |
| contract | 最终正文能解析为要求的 JSON 结构 | `contract_invalid_json`、`contract_shape` | 否 |
| provenance | 每条 ID 存在，URL 由本地输入绑定 | `unknown_article_id`、`source_url_mismatch` | 否 |
| quality | 公开正文满足发布质量规则 | `quality_chinese`、`quality_length`、`quality_sentence`、`quality_duplicate`、`quality_grounding` | 是，可发布 |

建议同时保留以下派生布尔值，避免继续使用含糊的“API 成功”：

- `transport_completed`
- `provider_accepted`
- `final_text_received`
- `contract_valid`
- `quality_valid`
- `publishable`

## 2026-07-14 真实 API 证据

### 测试条件

- endpoint：当前配置的 ModelScope OpenAI-compatible `/v1/chat/completions`
- 输入：`data/2026-07-14.json` 中的 14 条文章，经当前 `compress_articles()` 处理
- prompt：当前 `prompts/daily.md`
- 通用参数：`temperature=0.2`、`max_tokens=2000`、`stream=false`
- 环境：仅确认 ModelScope 凭据可用；SiliconFlow 未配置，因此未计为本轮实测
- 安全：不输出密钥、Authorization header 或完整错误 header

### 模型响应矩阵

| 模型 | HTTP/协议 | 正文形态 | 本地结果 | 分类 |
| --- | --- | --- | --- | --- |
| `ZhipuAI/GLM-5.2`，`enable_thinking=false` | 200；单一 JSON；`choices=1` | content 725 字符；reasoning 为空；`finish_reason=stop` | 7 条通过；随后生产函数复测为 8 条 `required_ai` 通过 | 完整成功，存在正常非确定性 |
| `Qwen/Qwen3.5-397B-A17B` | 200；单一 JSON；`choices=1` | reasoning 15214、content 1193；耗时 79.9 秒 | 8 条通过 | 推理/最终正文分离成功；延迟和用量需护栏 |
| `Qwen/Qwen3.5-35B-A3B` | 200；单一 JSON；`choices=1` | reasoning 16624、content 1230；耗时 69.7 秒 | 8 条通过 | 同上 |
| `Qwen/Qwen3-235B-A22B-Instruct-2507` | 200；合法 JSON；`choices=1` | 7 条中文摘要，title 保留英文原文 | 中文比例 0.23，被拒绝；摘要单独计算为 0.799 | API/协议成功，本地质量失败 |
| `deepseek-ai/DeepSeek-V4-Pro` | 200；合法 envelope；`choices:null` | 无最终正文 | 未进入 JSON 质量校验 | `empty_choices` |
| `moonshotai/Kimi-K2.5` | 400；`has no provider supported` | 无正文 | 未进入协议/质量层 | `provider_unavailable` |
| `Tencent-Hunyuan/Hy3` | 200；拼接 97 个 JSON 文档 | 前 96 个 `choices:null`，最后一个有 choice | 单文档 JSON 解析必然失败 | `protocol_multi_document` |
| `MiniMax/MiniMax-M3` | 200；`choices:null` | 无正文 | 未进入本地质量层 | `empty_choices` |
| `stepfun-ai/Step-3.7-Flash` | 200；`choices:null` | 无正文 | 未进入本地质量层 | `empty_choices` |
| `ZhipuAI/GLM-5.1` | 400；无 provider | 无正文 | 未进入本地质量层 | `provider_unavailable` |
| `ZhipuAI/GLM-4.7-Flash` | 200；`choices:null` | 无正文 | 未进入本地质量层 | `empty_choices` |

受控负向探针另行确认：

- 使用无效测试 token 访问真实 endpoint，得到 HTTP 401 / `AuthenticationError`。
- 使用不可达本地地址，得到 `APITimeoutError`，归类为网络/超时而不是 provider 或质量错误。
- `/models` 返回 55 个 ID，但多个目录内模型实际无 provider 或返回 `choices:null`；目录存在不代表路由可用。

### Structured Outputs 能力探针

不能仅以 HTTP 接受请求字段判断 provider 能力：

| 模型/模式 | 真实结果 | 结论 |
| --- | --- | --- |
| GLM-5.2 + `json_object` | HTTP 200，`choices:null` | 当前 endpoint/model 组合不能默认启用 |
| GLM-5.2 + `json_schema` | HTTP 200，`choices:null` | 同上 |
| Qwen3 Instruct + `json_schema` 正常请求 | 返回符合样例的 `{"ok": true}` | 只能证明一次正例，不证明强制执行 |
| Qwen3 Instruct + 冲突 Schema | 仍返回 `{"ok":"yes","extra":1}` | provider 接受字段但未强制 Schema |
| Qwen3 Instruct + `json_object`，要求输出 `NOT_JSON` | 返回 JSON 字符串 `"NOT_JSON"` | 只保证可解析 JSON，不保证顶层对象 |

无论是否使用 SDK 的 Structured Outputs helper，本地 Pydantic 校验都必须保留。能力探针应验证
“错误指令下仍服从 Schema”，而不只是测试一个模型本来就可能正确回答的 happy path。

### 历史产物边界

仓库中的 `data/2026-07-14.json` 记录过 ModelScope 失败和 SiliconFlow 成功，但不能作为当前
prompt 或本轮 provider 的实时证据：

- 当前 prompt SHA-256：`11cd56e029ffeea98986c9795f1f05863dc269b9ee205f701ad79909af107de7`
- 历史产物 prompt 指纹：`6cc852476f726c006141e825c7520a5e250b7979941f5b4eb2836cbef359235c`
- 当前压缩输入指纹：`640fc3649314cb321c0e1fffc5d997e6d8575bcc8de67f60d07a1e9a4da68c27`
- 历史产物输入指纹：`57125e149f1f1ab6589fea339f0a3891590a1f693b0391bacf15df773973736f`

四者不匹配，因此历史结果只能证明历史运行的 provenance，不能证明当前提示词或当前契约通过。

## `feat/llm-api-compatibility` 实施记录

本分支保持生产 fail-closed、article ID/URL 本地绑定和 offline/reviewed provenance 不变，已
落地以下范围：

1. 新增传输、HTTP、envelope、正文提取、contract、provenance、quality 七层互斥 reason
   code，并让连接 smoke、完整 contract smoke 和生产摘要共用分类。
2. 使用 SDK raw response 在解析前拒绝错误 Content-Type 和拼接多文档；支持 content string、
   text blocks、refusal、`finish_reason` 和独立 reasoning 字段。
3. 模型能力按 `(provider, base_url, model)` 配置；模型名不再隐式开启 thinking 或
   Structured Outputs。未经冲突负例证明的 `json_schema` 无法在生产配置启用。
4. 模型输出改为最小 `article_id + summary`；未知字段只记录名称后丢弃，内部 title 和 URL
   始终从本地输入绑定。兼容 contract 有 `compatible_output_contract` 回滚开关。
5. fallback 成功和全部失败都会在 run workspace 原子写入脱敏
   `summary-attempts.json`；正文、完整 reasoning、密钥和 Authorization header 不进入该
   artifact。
6. `main.py test`、最小 smoke 和 live contract runner 均以非零退出码反映失败；live runner
   必须显式 `--live` 和请求预算。
7. 冻结协议 fixture 明确标记为 `synthetic`，不能冒充 live 证据。

当前 prompt/input 指纹：

- prompt SHA-256：`8da86eb039da18ae4e4758868a1eefc3c15e82988b378bce54a4a7d958033878`
- 压缩输入 SHA-256：`640fc3649314cb321c0e1fffc5d997e6d8575bcc8de67f60d07a1e9a4da68c27`

本分支的去敏 live 结果保存在被 Git 忽略的 `.runs/llm-contract-smoke-branch-*.json`：

| 模型/模式 | 结果 | 分层证据 |
| --- | --- | --- |
| GLM-5.2 / prompt-only，旧措辞两次 | HTTP、envelope、contract、provenance 均通过；quality 拒绝 | 第二次明确为第 4 条 29 字、第 9 条 25 字；没有降级 30 字门槛 |
| GLM-5.2 / prompt-only，强化硬边界后 | 7 条 publishable | content 545；reasoning 0；`stop`；总 tokens 1760 |
| Qwen3.5 35B / prompt-only | 7 条 publishable | content 771；reasoning 18495；仅 content 进入 contract；总 tokens 8712 |
| Qwen3 Instruct / json-schema 正例 | 7 条 publishable | endpoint 接受字段并返回合格日报，但只构成正例 |
| Qwen3 Instruct / schema 冲突负例 | 不通过 enforcement 探针 | HTTP 200 但 `choices:null`，归类 `empty_choices`；生产继续 `prompt_only` |

实现后确定性回归由 161 个扩展到 195 个测试（最终数字以分支交付审计为准）。Phase 3 要求的
20 个真实摘要样本、人工盲审，以及 Phase 4 的连续多日/小流量观察没有在本分支中伪造为
完成；这些仍是合并任何进一步质量放宽前的门槛。

## 约束审计

### 必须保留的底线

| 约束 | 结论 | 原因 |
| --- | --- | --- |
| 已知 `article_id` | 保留硬门槛 | 防止模型发明来源或越界引用 |
| URL 本地绑定 | 保留硬门槛 | 模型不应决定或返回发布 URL |
| 非空最终正文 | 保留，但归类到 extraction | reasoning 或空 choice 不能发布 |
| 单一、无歧义 JSON 根 | 保留硬门槛 | 不从多个对象中猜选结果 |
| 有来源时至少一条、不得超过上限 | 保留硬门槛 | 防止空日报和越界输出 |
| 公开正文中文可读 | 保留质量门槛 | 日报产品定位为简体中文 |
| 不公开 URL、内部 ID | 保留硬门槛 | 维持当前 reader-safe 输出边界 |
| 完整、非截断事实 | 保留质量门槛 | 省略号或 token 截断不能成为成稿 |
| AI/offline/reviewed provenance | 保留硬门槛 | 防止离线或人工结果冒充 API 成功 |
| 本地最终校验 | 永久保留 | OpenAI-compatible provider 不保证执行相同协议 |

### 需要影子评估、可能放宽或移出硬门槛的约束

| 当前约束 | 问题 | 候选策略 |
| --- | --- | --- |
| `title` 必填且必须中文 | renderer 不展示 title；真实 Qwen 中文正文因英文内部 title 被拒绝 | 从 model-facing Schema 移除 title，或设为可选诊断字段 |
| 中文比例基于 `title + summary` 全局计算 | 非公开英文 title 可拖垮整批；单条英文过多又可能被其他条目掩盖 | 只评价公开 summary，并逐条记录比例/中文字符数 |
| 30 字硬下限 | 完整的 29 字新闻与明显残缺结果被同类拒绝 | 35–50 保留为目标；短结果先进入 shadow 告警和人工评分 |
| 全面禁止 `:`/`：` | 会拒绝“公司表示：……”等自然表达 | 区分标题式冒号和句内合法标点，或在本地安全规范化 |
| 必须恰好一句 | 两个短完整句可能更清楚；`。”` 会被误判为未结束 | 支持句末闭合引号/括号；影子比较一至两句质量 |
| 任意额外字段都失败 | `confidence`、provider note 或多余 `url` 可安全丢弃 | allowlist 提取已知字段，未知字段写入告警而不信任 |
| `discussion_topic` 缺失则整批失败 | 互动话题不承载来源事实 | 本地生成固定默认问题，并记录模型字段缺失 |
| 只允许纯 JSON 或完整 fence | 有些模型会加一句模板文字 | 仅兼容“恰好一个 JSON 对象 + 无害前后缀”，仍拒绝多对象 |

### 当前缺失的质量保障

1. prompt 在条件满足时要求 7–10 条，本地校验却只要求至少一条；`expected_items` 实际只作上限。
2. 允许重复 `article_id`，但没有完全重复或近似重复摘要检查。
3. `article_id` 只提供引用完整性，不证明摘要事实真的由对应 title/description 支持。
4. 没有对 `finish_reason=length`、content filter、refusal 或 reasoning-only 建立专门发布阻断。
5. `validation_passed` 默认值为 `true`，不是校验函数计算出的事实。

## 阻断点与优先级

### P0：真实性与可观察性

1. 所有失败层级必须有独立稳定分类；禁止继续用 `SummaryQualityError` 表示空 choices 或协议故障。
2. 所有模型失败时也必须持久化脱敏 attempts，不能只留下最终异常字符串。
3. `python main.py test` 必须根据连接结果返回非零退出码；不能让 shell 成功掩盖所有 provider 失败。
4. reasoning 只能用于长度和存在性诊断，绝不能作为 fallback 正文发布。
5. live、offline、reviewed、synthetic fixture 必须在 artifact 中显式标注，不能跨类型汇总成功率。

### P1：协议兼容性

1. 将 provider/model capability 从硬编码判断迁移为配置和经验证的探针结果。
2. 支持单一 fenced JSON、provider 额外字段、正文内容块、refusal 和 finish reason。
3. 拒绝 Hy3 式多文档响应；不得为了“兼容”而取最后一个 JSON。
4. `response_format` 采用逐模型能力协商，并用冲突用例验证是否真正强制。
5. 对 `max_tokens`、completion usage、reasoning usage 和总耗时分别设置预算。

### P1：质量误杀与质量缺口

1. 中文比例改为基于公开 summary 的逐条 shadow 指标。
2. 未展示的 title 不再决定整批可发布性。
3. 字数、冒号、句数和闭合引号建立候选规则对照，不直接改生产阈值。
4. 增加条数下限诊断、重复摘要和来源支持检查。

### P2：维护性

1. 清理 `summarize_or_offline` 等与实际 fail-closed 行为不一致的命名/docstring。
2. 将连接 smoke、完整 contract smoke 和编辑质量 benchmark 分成三个入口。
3. 让 provider attempt、summary result 和 run manifest 使用一致的 reason code 枚举。

## 目标设计

### Attempt 结果

建议新增不可变、可序列化的 attempt 记录，字段至少包括：

```text
provider
model
endpoint_label
request_mode              # prompt_only / json_object / json_schema
started_at / elapsed_ms
transport_status
http_status
request_id
failure_stage
failure_code
retryable
choices_count
content_type
content_length
reasoning_length
finish_reason
prompt_tokens
completion_tokens
total_tokens
response_sha256
contract_valid
quality_valid
```

限制：

- 不持久化 API key、Authorization header、带认证信息的 URL 或完整异常 header。
- 默认不在公共 artifact 中保存完整 reasoning。
- 完整模型正文仅允许进入私有、短保留期的审计 fixture；公共日志只记录长度和哈希。
- request-id 可以保存，但不得被当作成功条件。

### Provider capability

每个 `(provider, base_url, model)` 组合维护独立能力记录：

```text
supports_chat_completions
supports_json_object
supports_json_schema
enforces_json_schema
thinking_control_parameter
reasoning_field
content_shape
max_tokens_parameter
timeout_seconds
last_verified_at
verification_sample_count
```

能力记录有 TTL，模型或 provider 路由变化后必须重新探测。`/models` 只用于发现候选，不能直接
把 `supports_chat_completions` 设为 true。

### Parser

目标 parser 的处理顺序：

1. SDK/HTTP 层确认只有一个合法响应文档。
2. 明确检查 choices 是 list 且非空；区分 `null`、`[]` 和字段缺失。
3. 读取 refusal、finish reason、content、reasoning 字段；不把 reasoning 当最终内容。
4. 将字符串或支持的 content blocks 规范化为一个最终文本。
5. 从最终文本中接受纯 JSON、完整 fence，或恰好一个根对象的安全前后缀。
6. allowlist 提取业务字段；未知字段进入 diagnostics。
7. 先执行结构/来源校验，再执行编辑质量校验。

### Validator

校验职责拆为三组：

- `validate_contract`：JSON 类型、必要字段、item 数量上限。
- `validate_provenance`：article ID、URL 本地映射、无越界来源。
- `evaluate_editorial_quality`：中文、目标字数、完整句、重复、来源支持和互动话题。

每组返回全部 issue，而不是在第一个问题处停止。生产 gate 可以继续对现有 issue 集 fail-closed，
shadow runner 同时计算候选规则，便于比较而不立即改变发布行为。

## 分阶段实施

### Phase 0：冻结证据与基线

任务：

1. 将本轮响应转为去敏 fixture：成功正文、`choices:null`、400 provider、多 JSON、reasoning + content。
2. fixture 写明来源类型、采集时间、provider/model、请求模式、响应哈希和是否真实 live。
3. 建立当前 validator 与候选 validator 的双判定报告。
4. 把 `161 passed`、Ruff lint/format 作为实现前基线。

通过条件：

- 每个 fixture 都能明确回答它是 live、offline、reviewed 还是 synthetic。
- 仓库扫描确认 fixture 和日志没有密钥。
- 当前生产阈值和发布行为没有变化。

### Phase 1：错误分类与持久化

任务：

1. 新增 attempt contract 和 failure stage/code 枚举。
2. 将网络、鉴权、配额、provider、协议、empty choices、empty content 分开映射。
3. 即使所有 provider 失败，也在 run workspace 中写入脱敏 summary-attempt artifact。
4. 修正 `main.py test` 退出码；保留最小 smoke 的无正文日志策略。
5. 统一 console、manifest 和 JSON artifact 的脱敏函数。

通过条件：

- 每种 failure fixture 都产生稳定且互斥的分类。
- 失败运行不覆盖上一版公开日报。
- fallback 成功和全部失败都能审计每次尝试。
- 现有全量测试、Ruff 和发布回滚测试通过。

### Phase 2：兼容 parser 与 capability 探针

任务：

1. 实现最终正文 extractor，支持 content string/blocks、reasoning、refusal 和 finish reason。
2. 实现安全单 JSON 提取；继续拒绝多个响应文档。
3. 将 GLM thinking 控制迁移到 capability 配置。
4. 建立 prompt-only、json_object、json_schema 三种模式的负向能力探针。
5. 所有兼容解析先以 shadow 判定运行，不改变生产 gate。

通过条件：

- GLM prompt-only 不因添加 Structured Outputs 探针而改变生产请求。
- Qwen reasoning 与 content 均能记录长度，但仅 content 进入摘要解析。
- Hy3 多文档 fixture 始终为 protocol failure。
- provider 接受但不执行 Schema 时，本地 contract 能明确拦截。

### Phase 3：质量规则影子比较

任务：

1. 中文质量只基于公开 summary，逐条计算并保留当前全局算法作对照。
2. 35–50 继续作为目标区间；30/80 当前硬边界暂不改变。
3. 影子评估 29 字完整句、合法冒号、两句、句末引号和缺失互动话题。
4. 增加条数覆盖率、完全重复、近似重复和来源支持诊断。
5. 对每条当前拒绝/候选接受的差异进行人工盲审。

通过条件：

- 至少 20 个真实摘要样本覆盖英文标题密集、空 description、品牌英文密集和聚合来源。
- 候选规则没有降低事实准确率或增加重复率。
- 每一项拟放宽规则都有独立样本、指标和回滚开关。
- 未经单独批准，不改变生产 hard gate。

### Phase 4：小流量启用与多 provider 扩展

任务：

1. 先启用 attempt 分类和兼容 parser，再单独评审质量规则变更。
2. 每个 provider/model 以 `publish=false` 连续验证，再进入小流量生产。
3. SiliconFlow 只有在实际凭据下取得新响应后才能标记为当前可用。
4. 监控成功层级、fallback 次数、总耗时、用量、质量拒绝率和人工质量。

通过条件：

- 连续 7 天没有将 offline/reviewed 记为 AI。
- 没有 reasoning 泄漏、未知来源、URL 映射错误或多 JSON 误接受。
- 发布质量不低于当前基线；异常时可通过 feature flag 立即回到当前 parser/gate。

## 回归测试矩阵

### 确定性 fixture

| 组 | 用例 | 预期 |
| --- | --- | --- |
| transport | DNS、代理、连接拒绝、timeout | 独立网络分类；无 HTTP 状态 |
| HTTP | 401、403、429、400 provider、500/502/503 | 鉴权、配额、provider、服务端错误互不混淆 |
| envelope | 非 JSON、两个 JSON、97 个 JSON、错误 Content-Type | protocol failure；不进入质量层 |
| choices | 缺字段、`null`、`[]`、一个 choice | 前三者分别记录形态并归为 empty/missing；最后继续 |
| message | content、reasoning-only、content blocks、refusal | 仅最终 content 可继续；其余有独立分类 |
| finish | stop、length、content_filter | length/filter 阻断发布并记录为 incomplete/refusal |
| JSON | 纯对象、fence、唯一对象前后缀、多个对象 | 前三类按策略解析；多个对象拒绝 |
| Schema | 缺字段、额外字段、错误类型、顶层标量 | 区分可忽略 extras 与不可恢复结构错误 |
| provenance | 未知 ID、URL 不匹配、重复 ID | 未知/不匹配阻断；重复进入独立内容重复检查 |
| quality | 英文内部 title、29 字、冒号、两句、闭合引号 | 同时输出 current/candidate 判定，不直接改门槛 |

### 真实模型

| Provider/模型 | 模式 | 最小样本 | 必须验证 |
| --- | --- | --- | --- |
| ModelScope GLM-5.2 | prompt-only、thinking off | 连续 5 次协议 smoke；20 个质量样本 | 非空 choice/content、来源映射、延迟、条数波动 |
| ModelScope GLM-5.2 | json_object/json_schema | 各 3 个正例 + 3 个冲突负例 | 在稳定非空前保持禁用；不得因 HTTP 200 标为支持 |
| ModelScope Qwen3.5 397B | prompt-only | 5 次协议、20 个质量样本 | reasoning/content 分离、总耗时、usage 与 max_tokens 差异 |
| ModelScope Qwen3.5 35B | prompt-only | 同上 | 同上，并比较模型规模下的质量差异 |
| ModelScope Qwen3 235B Instruct | prompt-only、JSON modes | 20 个质量样本 | 英文 title 不应单独掩盖中文摘要质量；Schema 冲突必须本地拦截 |
| ModelScope DeepSeek-V4-Pro | prompt-only | 5 次 smoke | `choices:null` 仍存在时保持不可用，不进入质量失败统计 |
| ModelScope Hy3 | non-streaming | 3 次 smoke | 多文档继续归类为 protocol failure |
| ModelScope Kimi-K2.5 | prompt-only | 3 次 smoke | 400 无 provider 保持 provider 分类 |
| SiliconFlow Kimi-K2.6 | prompt-only | 获得凭据后 5 次协议、20 个质量样本 | 在真实新响应前状态只能是 `not_run` |

真实 API 测试应使用手动 workflow 或明确的 `--live` 开关，并设置每日请求/费用上限。常规 CI 只运行
冻结 fixture；live 失败不应被离线结果自动替代成绿色。

### 编辑质量数据集

至少覆盖：

- 10 条以上候选且有 7 条以上独立事实。
- description 全部为空、部分为空、中文和英文混合。
- 英文品牌/模型名密集，但中文谓语完整。
- 同一事件多篇报道、同一公司不同事件。
- 一个聚合来源支持多个独立事实和重复 `article_id`。
- 29/30/35/50/80/81 个可见字符边界。
- 合法冒号、标题式冒号、两句、句末引号、真正截断省略号。
- 模型输出额外字段、代码围栏、单一前后缀和多对象。

人工评分至少记录事实支持、主体/动作/结果完整度、重复、中文自然度和是否可直接发布，不能只看
字符数。

## 计划文件改动地图

| 文件/模块 | 计划改动 |
| --- | --- |
| `utils/summary_contracts.py` | attempt/分类契约、分层 validator、候选质量报告 |
| `summarizer.py` | provider adapter、正文 extractor、安全 JSON parser、attempt 持久化输入 |
| `main.py` | 失败 artifact、CLI 退出码、明确 summary policy 编排 |
| `config.py` / `config.yaml` | provider/model capability 和超时/用量配置，密钥仍只来自环境 |
| `scripts/modelscope_smoke.py` | 保留最小连接 smoke；输出统一 reason code |
| `scripts/llm_contract_smoke.py` | 新增手动 live contract runner，显式预算和 `--live` 确认 |
| `tests/fixtures/llm-compat/` | 去敏真实响应、协议负例和元数据 |
| `tests/test_llm_protocol.py` | 传输、HTTP、envelope、choices、message 分类 |
| `tests/test_llm_contract.py` | JSON、provenance 和 current/candidate 质量规则 |
| `handbook/operations/` | 运行、失败分类、凭据、模型启用和回滚手册 |

## 风险与缓解

| 风险 | 缓解 |
| --- | --- |
| 放宽 extra 字段后吞掉 Schema 漂移 | 只 allowlist 提取已知字段；未知字段计数并保留诊断 |
| 从自由文本提取 JSON 接受恶意/含糊输出 | 只允许恰好一个根对象和无害前后缀；多个对象一律拒绝 |
| 误把 reasoning 当正文 | 数据模型分别存长度/存在性；renderer 只接受 final content |
| 质量规则调整导致日报变短或信息不足 | 先 shadow + 人工盲审；35–50 目标不变；逐项 feature flag |
| provider 声称支持 Schema但实际忽略 | 使用冲突负例验证；本地 Schema 永久保留 |
| 模型目录或能力缓存过期 | capability 有 TTL、样本数和 `last_verified_at` |
| fallback 增加延迟和费用 | 每次尝试、单模型和整次摘要分别设置 deadline/usage 上限 |
| 全部失败时丢失证据 | attempt artifact 在抛出最终异常前原子写入 run workspace |
| 日志泄露密钥或第三方正文 | 统一脱敏；公共日志只记录长度、分类、request-id 和哈希 |
| 来源 ID 正确但事实不受支持 | 新增实体/动作支持检查和人工质量集；不放宽 provenance gate |

## 完成定义

本计划只有在以下条件全部满足后才算完成：

- [ ] 网络、鉴权、配额、provider、协议、empty choices、reasoning-only、contract、provenance、quality 都有互斥错误码和测试。
- [ ] fallback 成功与全部失败均留下脱敏 attempt 记录。
- [ ] `main.py test` 和 live smoke 以正确退出码反映结果。
- [ ] GLM、Qwen、DeepSeek、Hy3、Kimi 的真实结果按本计划矩阵重新验证；未配置 provider 明确为 `not_run`。
- [ ] Structured Outputs 通过冲突负例验证，而不是只通过 happy path。
- [ ] reasoning 不进入 renderer、公开日志或 SummaryResult 正文。
- [ ] article ID、URL 本地绑定、AI/offline/reviewed provenance 和 fail-closed 发布行为保持不变。
- [ ] 候选质量规则至少有 20 个真实摘要样本和人工盲审，无事实质量下降。
- [ ] 任何生产门槛调整都经过独立评审、feature flag 和回滚验证。
- [ ] 全量 pytest、Ruff lint/format、发布回滚和私密信息扫描通过。
- [ ] 操作手册能从一次失败 run 明确回答失败发生在哪一层、是否调用过真实 API、是否有可发布 AI 正文。

## 参考资料

- [OpenAI Python SDK 错误处理](https://github.com/openai/openai-python#handling-errors)
- [OpenAI Python Structured Outputs parsing helpers](https://github.com/openai/openai-python/blob/main/helpers.md)
- [当前摘要与发布架构](../../architecture/system.md)
- [运行故障排查](../../operations/troubleshooting.md)
- [质量验收记录](../../quality/acceptance.md)
- [AGIHunt 主来源接入规划](agihunt-primary-source-plan.md)
