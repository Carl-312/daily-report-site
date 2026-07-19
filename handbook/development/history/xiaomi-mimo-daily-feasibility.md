# 小米 MiMo 日报契约可行性实验（历史）

- 实验日期：2026-07-15
- endpoint：`https://api.xiaomimimo.com/v1`
- 模型：`mimo-v2.5`、`mimo-v2.5-pro`
- 鉴权：`.env` 中的 `MIMO_API_KEY`，仅记录非敏感加载状态
- 结论：OpenAI 协议可用，但当前不适合进入日报 primary、fallback 或正式 shadow

## 结论

MiMo 官方 API 与 OpenAI Chat Completions 兼容，当前密钥和 endpoint 可正常使用。两个模型都能在
Non-think 下快速返回非空最终正文，`mimo-v2.5` 的 3 条最小日报也能通过 JSON、来源绑定与中文质量
门禁。

然而，完整生产日报共执行 7 次，结果为 **0/7 可发布**：

- `mimo-v2.5` Non-think 三次分别出现摘要不足 30 字、输出 14 条超过上限、硬约束后仍有短摘要；
- `mimo-v2.5-pro` Non-think 两次均有 24–29 字的短摘要；
- 两个模型开启 thinking 后仍然失败，且延迟增加到约 52–54 秒、额外消耗 3,558–4,706 个
  reasoning tokens；
- 所有失败都被现有本地 contract/quality gate 正确拦截，没有降低门禁或发布不合格结果。

因此，MiMo 具备基础 API 和 JSON 能力，但对本项目“7–10 条、每条 30–80 字、完整单句、禁用冒号”
的组合约束遵循不够稳定。当前只能作为隔离的提示词研究对象，不应加入生产候选链。

## 官方能力映射

| 项目 | 官方能力 | 本轮用法 |
| --- | --- | --- |
| 协议 | OpenAI-compatible `/v1/chat/completions` | OpenAI Python SDK，`max_retries=0` |
| 鉴权 | `api-key` 或 `Authorization: Bearer` | Bearer `MIMO_API_KEY` |
| 当前文本模型 | `mimo-v2.5`、`mimo-v2.5-pro` | 两者均验证 |
| 旧模型 | MiMo V2 系列已于 2026-06-30 下线 | 未测试旧 ID |
| JSON | 两个模型支持 `response_format={"type":"json_object"}` | 完整实验均启用 JSON Mode |
| thinking | 默认 enabled，可显式 disabled | 分别验证 Non-think 与 Think |
| token 参数 | `max_completion_tokens` | Non-think 3,000；Think 8,000 |
| 采样 | Think 下 temperature/top_p 会被强制使用推荐值 | Non-think `temperature=0.2`；Think 不传采样参数 |

官方资料：

- [OpenAI Chat Completions 兼容接口](https://mimo.mi.com/docs/api/chat/openai-api)
- [模型能力与限制](https://mimo.mi.com/docs/en-US/quick-start/model)
- [Structured Outputs](https://mimo.mi.com/docs/en-US/quick-start/usage-guide/text-generation/structured-output)
- [Deep Thinking](https://mimo.mi.com/docs/en-US/quick-start/usage-guide/other/deep-thinking)
- [限流说明](https://mimo.mi.com/docs/en-US/api/guidance/rate-limit)
- [API 定价](https://mimo.mi.com/docs/en-US/pricing)

官方当前价格显示，`mimo-v2.5` 国内输入缓存未命中/输出分别为 ¥1/¥2 每 MTok，Pro 为 ¥3/¥6
每 MTok。费用并不是本轮阻塞点；主要问题是完整日报契约成功率。

## Live 结果

完整响应和 reasoning 原文均未保存，只记录长度、usage、哈希和本地门禁结果。

| # | 模型 / 模式 | 场景 | 耗时 | 结果 |
| ---: | --- | --- | ---: | --- |
| 1 | V2.5 / Non-think | 最小 `OK` | 3.6 秒 | 成功；254 tokens |
| 2 | Pro / Non-think | 最小 `OK` | 1.3 秒 | 成功；258 tokens |
| 3 | V2.5 / Non-think | 3 条最小日报 | 4.3 秒 | 3 条全部通过；1,676 tokens |
| 4 | V2.5 / Non-think | 完整生产提示词 | 8.2 秒 | `quality_length` |
| 5 | V2.5 / Non-think | 完整生产提示词复验 | 9.4 秒 | 输出 14 条，`contract_shape` |
| 6 | Pro / Non-think | 完整生产提示词 | 5.5 秒 | 两条仅 29/25 字 |
| 7 | V2.5 / Non-think | 恰好 8 条、35–50 字硬约束 | 7.6 秒 | 第 9 条仅 27 字 |
| 8 | Pro / Non-think | 同一硬约束 | 4.8 秒 | 两条仅 29/24 字 |
| 9 | V2.5 / Think | 同一硬约束 | 54.0 秒 | 29 字且含冒号；4,706 reasoning tokens |
| 10 | Pro / Think | 同一硬约束 | 51.6 秒 | 第 8 条仅 25 字；3,558 reasoning tokens |

完整日报统计：

| 模型 | Non-think | Think | 合计可发布 |
| --- | ---: | ---: | ---: |
| `mimo-v2.5` | 0/3 | 0/1 | 0/4 |
| `mimo-v2.5-pro` | 0/2 | 0/1 | 0/3 |
| 总计 | 0/5 | 0/2 | 0/7 |

## 失败层级分析

本轮没有鉴权、HTTP、无 choice、非法 JSON、未知 `article_id` 或来源 URL 失败。问题集中在生成后的
本地契约层：

1. **条数不稳定。** 普通版曾把 14 个候选全部输出，违反最大 10 条；即使追加“恰好 8 条”，仍
   输出到第 9 条。
2. **长度自检不可靠。** 多次输出 24–29 字摘要，距离 30 字门槛只差少量字符，但重复出现说明
   不是一次偶发。
3. **thinking 没有改善。** 两个模型都增加了大量 reasoning token 和约 6–11 倍延迟，最终仍被相同
   质量门禁拦截。
4. **Pro 没有形成质量优势。** Pro 更快，但完整契约成功率与普通版相同，不能用更高单价换取准入。

## 项目适用性判断

| 维度 | 判断 |
| --- | --- |
| OpenAI API 接入 | 通过 |
| 密钥与 endpoint | 通过 |
| 非空最终正文 | 通过 |
| JSON Mode | 通过 |
| reasoning/content 隔离 | 通过；Non-think 为 0，Think 正确分栏 |
| 最小日报契约 | 通过 |
| 完整日报契约 | 不通过，0/7 |
| 延迟 | Non-think 很好；Think 对日报不划算 |
| 成本 | 较低，不是主要风险 |
| 当前准入 | 不进入 primary、fallback 或正式 shadow |

不建议为适配 MiMo 而把最小摘要长度降到 24 字、放宽最大条数，或在本地静默丢弃不合格项；这些
做法会降低所有 provider 共用的读者质量与来源门禁。若以后继续研究，应使用隔离的 provider-specific
提示词或显式二次修复实验，并要求至少连续 5 个不同日期完整契约 100% 通过后再评估准入。

本轮没有修改 `config.yaml`、默认 provider 顺序或 `.env`。
