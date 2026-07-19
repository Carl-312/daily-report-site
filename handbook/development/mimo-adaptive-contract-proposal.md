# MiMo 分级验收契约建议

- 状态：独立分支实验通过，尚未接入生产链
- 日期：2026-07-15
- 目标：提高 MiMo 系列完整日报的可用率，同时不降低来源真实性和公开内容安全门禁

## 分支实验结论

实验分支：`experiment/mimo-adaptive-contract-20260715`

使用 `data/2026-07-14.json` 中 14 条昨日新闻，对 `mimo-v2.5` 和 `mimo-v2.5-pro` 各执行
3 次 Non-think JSON Mode 调用。同一响应同时经过现有 atomic gate 和建议的 adaptive gate，未通过
重试、修改提示词或增加请求来制造对照差异。

| 模型 | 完成请求 | atomic 可发布 | adaptive 可发布 |
| --- | ---: | ---: | ---: |
| `mimo-v2.5` | 3 | 0 | 3 |
| `mimo-v2.5-pro` | 3 | 0 | 3 |
| 合计 | 6 | 0 | 6 |

6 次响应共收到 60 个 item：10 个因长度问题被显式隔离，3 个因超过 10 条上限被确定性封顶，最终
保留 47 个。每次 adaptive 结果均保留 7–10 条，并再次通过现有长度、单句、中文、无链接和来源 ID
门禁。

所有响应的 `finish_reason` 均为 `stop`，reasoning tokens 均为 0。单次 completion 仅使用
267–477 tokens，相对 4,000 token 预算的最高利用率约 11.9%；平均延迟约 6.4 秒。因此本轮进一步
确认，MiMo 的主要问题是少数 item 的编辑规则波动，而不是 token 截断。

量化上有明显改善，但**尚不能据此进入生产**。本次输入的 14 条新闻只有英文标题，没有 description；
人工复核发现个别合格摘要加入了“潜在风险”“引发伦理讨论”等标题未明确提供的解释性措辞。分级
验收没有扩大这类问题，但当前本地门禁也无法判断语义是否超出来源。后续仍需使用带 description 的
跨日样本验证事实忠实度。

可复核产物：

- [live 对照产物](mimo-adaptive-contract-live-artifact-20260715.json)：请求遥测、两套门禁结果、隔离
  诊断及 adaptive 合格成品；不含密钥、reasoning 原文或被拒绝摘要原文。
- `scripts/mimo_adaptive_contract_experiment.py`：显式 `--live`、请求预算和安全产物边界。
- `tests/test_mimo_adaptive_contract_experiment.py`：恢复、覆盖阈值、封顶、未知来源和链接泄露测试。

## 最值得改的一点

把当前“任意一条编辑质量不合格就拒绝整批响应”的原子验收，改为**分级验收**：协议、来源和
公开安全问题仍然整批失败；长度、单句、冒号等单条编辑问题只隔离对应 item；隔离后达到日报覆盖
阈值才允许发布。

这比继续增大 token 上限更值得优先验证。MiMo 的 7 次完整日报实验没有出现响应截断、非法 JSON、
未知 `article_id` 或来源错误，失败集中在少数 24–29 字摘要，以及一次输出 14 条。Think 模式把延迟
提高到约 52–54 秒并消耗数千 reasoning tokens，仍未修复这些问题。它反映的是指令遵循波动，而
不是输出 token 不够。

## 建议语义

一次模型响应按三层处理：

| 层级 | 典型问题 | 处理方式 |
| --- | --- | --- |
| 响应级硬门禁 | 非法或多个 JSON、响应截断、缺少最终正文 | 整批失败 |
| 信任级硬门禁 | 未知 `article_id`、公开链接或内部 ID 泄露、来源绑定异常 | 整批失败 |
| item 级编辑门禁 | 少于 30 或多于 80 个可见字符、冒号、省略号、非完整单句、重复项 | 隔离该 item 并记录原因 |

隔离后采用统一的发布阈值：

- 输入候选不少于 10 条时，至少保留 7 条合格 item；
- 输入不足 10 条时，至少保留 1 条，且不得超过当前 `max_summary_items`；
- 合格 item 超过上限时，按模型原始顺序保留前 `max_summary_items` 条，记录
  `items_capped`，不把超额本身视为整批协议错误；
- 未达到阈值时，本次 provider attempt 仍失败，进入既有 fallback，不发布半成品；
- 不在本地续写、截断或改写模型文本，避免产生无法由来源直接审计的新事实。

这里的“隔离”必须是显式、可审计的。attempt artifact 至少记录原始条数、合格条数、隔离条数、
每个隔离项的索引和错误码，但继续不保存响应原文或 reasoning 原文。例如：

```json
{
  "received_items": 8,
  "accepted_items": 7,
  "quarantined_items": 1,
  "diagnostics": ["quality_length:item=8:visible=25"]
}
```

## 为什么不先改 token 规则

`max_completion_tokens` / `max_output_tokens` 是传输预算，不是摘要字数规则。只有出现
`finish_reason=length`、JSON 尾部缺失或正文被截断时，才应提高它。MiMo 本轮能完整返回 JSON，且
短摘要是在预算内主动结束；增加预算不会迫使模型把 25 字写到 30 字，反而可能增加输出条数和成本。

因此 token 上限应继续保持 endpoint/model 级配置，并补充观测：记录 `finish_reason`、completion
tokens 与预算利用率。只有跨样本出现真实截断，才单独调整 MiMo capability，不能把全局上限一起
放宽。

## 对现有代码的最小落点

若决定进入下一阶段，建议只调整 `summarizer.py` 的质量评估边界，不改变公开 `SummaryResult`：

1. JSON 解析后先执行响应级和信任级硬门禁；
2. `evaluate_editorial_quality()` 保持返回逐条 issue，不再由任意 blocking quality issue 立即拒绝整批；
3. 新增纯函数按 item index 隔离编辑问题、去重并应用数量上限；
4. 对过滤后的 `SummaryDraft` 再执行覆盖阈值和现有 `validate_summary_result()`；
5. attempt artifact 增加结构化计数，确保灰度阶段可以比较“原始整批成功率”和“分级验收成功率”。

这项策略应先作为 MiMo shadow policy 显式开启，不能仅根据模型名称隐式触发。验证证明它没有损害
其他 provider 后，再决定是否成为通用契约。

## 验收标准

先离线重放固定响应，再做跨日 live shadow：

- 信任级错误的整批拦截率必须保持 100%；
- 发布结果必须为 7–10 条，且每条继续通过现有 30–80 字、单句、中文、无链接门禁；
- 每个被隔离或因超额未采用的 item 都有无原文的结构化诊断；
- MiMo Non-think 在至少 5 个不同日期的完整日报中，分级验收发布率达到 80% 以上；
- 不因启用该策略增加第二次模型调用，也不启用昂贵且本轮无收益的 thinking。

若达不到这些标准，保留当前 fail-closed 行为，MiMo 继续只作为隔离研究对象。

## 依据

- [MiMo 日报契约可行性实验](history/xiaomi-mimo-daily-feasibility.md)
- [LLM 执行架构](llm-execution.md)
- [小米 MiMo OpenAI 兼容接口](https://mimo.mi.com/docs/api/chat/openai-api)
- [小米 MiMo Structured Outputs](https://mimo.mi.com/docs/en-US/quick-start/usage-guide/text-generation/structured-output)

Context7 在本次调研中返回 `fetch failed`，上述 API 信息沿用同日官方文档核验与 live 实验记录。
