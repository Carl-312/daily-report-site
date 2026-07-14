# LLM API 兼容性运行手册

本项目把“请求成功”和“日报可发布”拆成独立事实。生产链路只发布通过最终
JSON、来源绑定和编辑质量门禁的 `message.content`；`reasoning_content`、refusal、
离线结果和人工复核结果都不能冒充模型正文。

## 三类验证入口

### 最小连接 smoke

```bash
python main.py test
python scripts/modelscope_smoke.py
```

两个入口都要求至少一个非空 choice 和非空最终正文。全部 provider 失败时退出码为
`1`，缺少凭据同样失败，不能只看控制台是否打印过 HTTP 200。

### 完整日报契约 live smoke

真实调用必须显式传 `--live` 并给出请求预算：

```bash
python scripts/llm_contract_smoke.py \
  --live \
  --data data/2026-07-14.json \
  --models ZhipuAI/GLM-5.2 Qwen/Qwen3.5-35B-A3B \
  --request-budget 2
```

该命令逐模型运行完整日报 prompt、本地 JSON allowlist、`article_id` 绑定和当前发布质量
门禁。结果写入被 Git 忽略的 `.runs/llm-contract-smoke-*.json`，只保留长度、哈希、
usage、reason code 和 request-id，不保存完整正文或 reasoning。

### Structured Outputs 冲突探针

Provider 接受 `response_format` 不代表真正执行 Schema。下例每个模型需要两次请求：一次
完整日报契约，一次故意要求错误类型和额外字段的冲突用例。

```bash
python scripts/llm_contract_smoke.py \
  --live \
  --models Qwen/Qwen3-235B-A22B-Instruct-2507 \
  --request-mode json_schema \
  --schema-conflict \
  --request-budget 2
```

只有 `contract=publishable` 且 `schema=enforced` 才能形成启用证据。`not_enforced` 表示接口
接受了字段但没有强制 Schema；此时生产配置必须继续使用 `prompt_only`，本地校验仍会
拦截不合格输出。

Live smoke 不进入常规 pytest/CI，也不得用 offline 或 reviewed 结果替代失败的 live
结果。脚本返回非零即表示本轮选择的模型矩阵没有全部通过。

## Capability 配置

非密钥能力位于 `config.yaml` 的 `llm.capabilities`。匹配键是
`(provider, base_url, model)`，同名模型在不同 endpoint 上不会共享结论。

```yaml
llm:
  default_timeout_seconds: 180
  capability_ttl_hours: 168
  attempts_filename: summary-attempts.json
  compatible_output_contract: true
  capabilities:
    - provider: modelscope
      base_url: https://api-inference.modelscope.cn/v1
      model: ZhipuAI/GLM-5.2
      request_mode: prompt_only
      thinking_control_parameter: enable_thinking
      thinking_control_value: false
      max_tokens_parameter: max_tokens
      timeout_seconds: 120
```

约束如下：

- 未匹配模型使用 `prompt_only`，不会按模型名猜测 thinking 或 Structured Outputs 参数。
- `compatible_output_contract` 控制唯一 JSON 前后缀、未知字段丢弃、可选 model title 和本地
  默认互动话题；需要紧急回退时设为 `false`，恢复严格 legacy contract。
- `json_object` 只有在 `supports_json_object=true` 时才能配置。
- `json_schema` 必须同时满足 `supports_json_schema=true` 和
  `enforces_json_schema=true`，否则配置加载直接失败。
- `/models` 目录结果和一次 happy path 不能更新 capability；需要正例、冲突负例、时间和
  样本数。
- API key 只来自环境变量，不能写入 capability、日志或 attempt artifact。

## Attempt artifact

正常 `run` / `summarize` 会在本次私有 run workspace 写入
`summary-attempts.json`。每个 provider 无论失败还是 fallback 成功都会留下独立记录，典型
字段包括：

```text
provider / model / endpoint_label / request_mode
transport_status / http_status / request_id
failure_stage / failure_code / retryable
choices_count / content_length / reasoning_length / finish_reason
prompt_tokens / completion_tokens / reasoning_tokens / total_tokens
response_sha256 / contract_valid / provenance_valid / quality_valid / publishable
```

所有 provider 失败时，artifact 会在最终异常抛出前原子写入；公开日报和上一版 publication
不会被覆盖。artifact 不含 API key、Authorization header、完整异常 header、正文或完整
reasoning。

## 分层定位

| `failure_stage` | 常见 `failure_code` | 含义与处理 |
| --- | --- | --- |
| `transport` | `network_dns`、`network_proxy`、`network_connection`、`timeout` | 尚未取得可用 HTTP 响应；检查 DNS、代理、连通性和模型 timeout |
| `http` | `authentication`、`rate_limit`、`provider_unavailable`、`bad_request`、`http_5xx` | endpoint 已响应；检查凭据、额度、模型路由或 provider 状态 |
| `envelope` | `protocol_invalid_json`、`protocol_multi_document`、`protocol_wrong_content_type`、`protocol_shape` | HTTP body 不是单一可识别 Chat Completions 文档；不得取“最后一个 JSON” |
| `extraction` | `empty_choices`、`missing_message`、`empty_content`、`reasoning_only`、`refusal`、`incomplete_output` | 没有可发布最终正文；reasoning 永远不能 fallback 成正文 |
| `contract` | `contract_invalid_json`、`contract_multiple_json`、`contract_shape` | 最终正文不是唯一日报 JSON 或必要字段类型错误 |
| `provenance` | `unknown_article_id`、`source_url_mismatch` | 模型 ID 无法与本地输入安全绑定；硬阻断 |
| `quality` | `quality_chinese`、`quality_length`、`quality_sentence`、`quality_public_safety` | JSON 和来源有效，但不满足当前公开编辑门禁 |

模型返回的未知业务字段只进入 `diagnostics` 并被丢弃；模型 `title` 不进入 renderer，最终
私有标题和 URL 始终按 `article_id` 从本地输入绑定。缺失互动话题使用固定本地问题并留下
`discussion_topic_defaulted` 诊断。

## 回滚

兼容层异常时，先把 `compatible_output_contract` 设为 `false`，再把对应 capability 的
`request_mode` 设回 `prompt_only`，移除未经验证的 thinking/参数覆盖，并通过
`MODELSCOPE_SECONDARY_MODEL` 选择已验证模型。不要关闭本地 contract、来源或质量校验，
也不要把失败运行自动改成 offline 发布。
