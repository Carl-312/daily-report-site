# 日报正式与灰度产物质量审计

状态：开放问题<br>
审计执行日期：2026-07-13<br>
证据范围：2026-07-04 至 2026-07-13 的 main 正式产物，以及 2026-07-04 至 2026-07-10 的 Tavily Gray Actions artifact。

本文记录已经由 GitHub 产物验证的质量风险、边界和后续验收标准。它不是 Tavily 默认开启的批准记录，也不替代每次运行的 manifest、日志或发布决策。

## 结论摘要

当前问题不只是偶发的选题集中：

1. 正式候选高度依赖单一来源，容易让同一公司或叙事占满日报。
2. LLM 摘要没有和输入文章一一绑定，曾将一篇新闻拆成多条发布。
3. 固定凑满 10 条的提示词会把泛科技内容写入 AI 日报。
4. Tavily 灰度验证的是离线 enrichment，不是正式 LLM 成稿；它既不能证明摘要多样性，也没有达到补量门槛。

因此，在没有候选集选择契约和摘要可追溯校验前，不能把“Actions 成功”理解为“日报内容质量通过”。

## 已验证证据

### 正式产物的来源集中

审计范围内的 main 数据文件共记录 91 条候选：

| 来源 | 条数 | 占比 |
| --- | ---: | ---: |
| TechCrunch | 90 | 98.9% |
| AIBase | 1 | 1.1% |
| The Verge | 0 | 0% |

这说明在该观察窗口中，配置为启用不等于来源实际有产出。它不单独证明 The Verge 的抓取故障，但正式产物已经出现实质性的单一来源依赖。

- 证据：[2026-07-04 至 2026-07-12 的 main data 目录](https://github.com/Carl-312/daily-report-site/tree/main/data)
- 证据：[2026-07-11 正式候选](https://github.com/Carl-312/daily-report-site/blob/main/data/2026-07-11.json)

### 摘要重复和一条新闻拆分

2026-07-05 的正式数据只有 4 篇原始文章，其中只有 1 篇是 Mistral 介绍；正式 Markdown 却生成了 10 条，并把该 Mistral 新闻拆为前 3 条不同表述。该日报在 GitHub Actions 中显示成功，但内容不满足“每条摘要代表一个独立新闻”的读者预期。

- 证据：[2026-07-05 原始候选](https://github.com/Carl-312/daily-report-site/blob/main/data/2026-07-05.json)
- 证据：[2026-07-05 正式日报](https://github.com/Carl-312/daily-report-site/blob/main/content/2026-07-05.md)

2026-07-10 的正式成稿中，10 条里有 5 条围绕 OpenAI；其中 GPT-5.6 发布与 Copilot 采用属于高度关联话题。现有精确去重不能阻止这种“同一主体、多篇报道”的集中。

- 证据：[2026-07-10 正式日报](https://github.com/Carl-312/daily-report-site/blob/main/content/2026-07-10.md)

2026-07-12 的正式输入只有 4 篇候选，但成稿仍输出 10 条，重复问题再次出现且更容易逐条归因。4 篇输入被扩写为 9 条内容：OpenAI/ChatGPT 对应第 1-2 条，Even Realities 智能眼镜对应第 3-5 条，Reed Jobs 医疗创业对应第 6-7 条，智能冰沙机对应第 8-9 条；第 10 条是无法映射到单篇输入的泛化总括句。因此，10 条并不代表 10 个独立新闻，实际只覆盖 4 个输入故事，额外产生 5 条重复改写和 1 条无输入映射内容。

该日的 JSON 同时记录 `input_count=4`、`final_count=4`、`strict_final_count=4`，且 `enabled=false`；这说明重复不是 Tavily 补量造成的，而是在摘要阶段把少量候选强行扩展为固定数量。对应的定时 Actions 仍以成功结束，进一步证明当前成功状态没有覆盖内容质量门。

| 输入候选 | 成稿条目 | 审计判断 |
| --- | --- | --- |
| OpenAI bets on families as ChatGPT goes deeper into households | 1-2 | 同一家庭场景叙事被拆成两条 |
| Smart glasses without a camera? Even Realities bets productivity beats recording everyone | 3-5 | 同一产品发布和定位被拆成三条 |
| Reed Jobs would rather talk about curing cancer than his last name | 6-7 | 同一人物/创业故事被改写成两条 |
| This slushie machine was a lifesaver during NYC’s heat wave | 8-9 | 同一产品和热浪场景被改写成两条 |
| 无对应输入候选 | 10 | 泛化总结句，不能作为独立新闻发布 |

- 证据：[2026-07-12 候选 JSON](https://github.com/Carl-312/daily-report-site/blob/main/data/2026-07-12.json)
- 证据：[2026-07-12 正式日报](https://github.com/Carl-312/daily-report-site/blob/main/content/2026-07-12.md)
- 证据：[2026-07-12 定时 Actions run 29179226047](https://github.com/Carl-312/daily-report-site/actions/runs/29179226047)

### 根因与修复记录（2026-07-13）

根因不在抓取或 Tavily 补量，而在摘要边界没有把候选数当成硬上限：

1. `prompts/daily.md` 原先要求完整输出 10 条，并在信息不足时选择最接近的内容凑数。
2. `validate_summary_quality()` 只检查编号条目“至少达到”候选数，不拒绝超过候选数的输出。
3. `_parse_summary_result()` 对超出输入的条目自动生成 `article-N`，使无输入来源的模型内容进入正式渲染。

历史版本曾在“每个候选最多一条”和“聚合候选可拆多条”之间调整。2026-07-18 的来源集中问题证明把拆分判断交给模型会同时放大重复和来源偏差，因此当前契约重新收敛为确定性短名单：每个短名单 `article_id` 恰好输出一次，每日目标和上限由 `max_summary_items=10` 统一控制。

当前契约关闭“无输入映射”、重复绑定和 URL 伪造路径；聚合页若包含多个独立事件，应由抓取/预处理阶段拆成多个候选，再分别进入短名单，而不是让摘要模型自行扩写。

### 2026-07-13 生产页面撤换与最终重跑

2026-07-13 的定时生产 run `29223231724` 使用旧版本代码，将 1 条 TechCrunch 候选扩写为 10 条 robotaxi 改写；该 run 的 Actions 状态虽然成功，但页面质量不合格。修复版本通过 PR #8 合并后，第一次生产重跑 `29242010254` 已将 JSON/Markdown 收敛为 2 条，但产物审查又发现静态构建层把紧凑有序列表全部清空：`build.py` 的 `convert_ol_to_paragraphs()` 只匹配 `<li><p>...</p></li>`，而当前 Markdown renderer 输出的是 `<li>...</li>`。

第二个修复通过 PR #9 合并，新增普通列表和带 URL 列表的构建回归测试。最终生产 run `29242308496` 的 `generate-and-deploy` 与 Pages deploy 均成功，`data/2026-07-13.json` 记录 2 个输入、2 个摘要，`article_id` 为 `a1/a2`；线上页面实际呈现两条带源链接的摘要，没有第 10 条扩写，也没有空正文。

- 旧页面与最终页面：[2026-07-13 线上日报](https://carl-312.github.io/daily-report-site/2026-07-13.html)
- 旧问题 run：[定时生产 run 29223231724](https://github.com/Carl-312/daily-report-site/actions/runs/29223231724)
- 第一次替换 run：[生产 run 29242010254](https://github.com/Carl-312/daily-report-site/actions/runs/29242010254)
- 最终修复 run：[生产 run 29242308496](https://github.com/Carl-312/daily-report-site/actions/runs/29242308496)
- 构建修复：[PR #9](https://github.com/Carl-312/daily-report-site/pull/9)

### P0 实现记录（2026-07-13）

本轮已完成两个最小化护栏：

1. 输入去重：`utils/dedupe.py` 现在先规范化 URL，移除跟踪参数和片段，再保留高优先级候选；同时拦截明显的跨来源标题改写。它不依赖 LLM，也不改变真实新闻数量。
2. 摘要契约：摘要输入为每条候选注入短 `article_id`（如 `a1`）；模型输出必须带 `[aN]`，本地拒绝未知 ID、重复 ID、超出候选数、源 URL 不匹配或空摘要。Markdown 仍由本地 renderer 生成。
3. 发布前复核：`stage_and_publish_run()` 对已保存的 `SummaryResult` 再执行一次契约校验，校验失败即阻断 promotion。

这两个护栏解决的是“同一输入被拆成多条”和输入候选重复问题；不同输入之间的深层语义相似、主体配额和 AI 相关性仍不在本轮范围内。

- 回归验证：摘要契约阶段为 `85 passed`；最终构建修复后为 `86 passed`；Ruff lint/format 通过。

### AI 主题稀释

2026-07-11 的正式候选 14 条均来自 TechCrunch，标题中明确含有 AI 或 OpenAI 的只有 3 条。正式成稿仍输出 10 条，至少 7 条没有明确 AI 主题，例如火箭、流媒体层级、社交网络管理层和通用网络安全。

- 证据：[2026-07-11 正式候选](https://github.com/Carl-312/daily-report-site/blob/main/data/2026-07-11.json)
- 证据：[2026-07-11 正式日报](https://github.com/Carl-312/daily-report-site/blob/main/content/2026-07-11.md)

### 灰度不是有效的成稿 A/B 对照

已复核 7 个 Tavily Gray artifact：2026-07-04、07-05、07-07 的两次运行、07-08、07-09 和 07-10。所有 artifact 的 strict final_count 都低于 min_articles=10，范围为 0 至 6。

最新的 2026-07-10 灰度产物最终有 6 条，其中 4 条仍围绕 OpenAI，说明 Tavily 的当前灰度配置没有解决主体集中问题。

- 证据：[最新 2026-07-10 Tavily Gray run](https://github.com/Carl-312/daily-report-site/actions/runs/29103525886)
- 证据：[2026-07-09 Tavily Gray run](https://github.com/Carl-312/daily-report-site/actions/runs/29031035682)
- 证据：[灰度工作流](https://github.com/Carl-312/daily-report-site/blob/main/.github/workflows/tavily-gray.yml)

该灰度工作流运行 python main.py run --offline --enrichment on，而生产通常运行在线 LLM 摘要。灰度还在北京时间约 20:56 取数，正式定时任务目标时间约为 08:36；两者既不复用同一候选快照，也不走相同的摘要路径。因此它只能诊断 enrichment 召回和验证行为，不能作为正式成稿多样性、重复率或事实约束的 A/B 证据。

### 发布可靠性缺口

2026-07-06 的定时生产运行中，生成任务成功，但 GitHub Pages 的 deploy-pages 步骤返回 “Deployment failed, try again later”。该次没有自动重试，也没有在运行结果中记录最终公开站点是否仍为上一版。

- 证据：[2026-07-06 失败部署 run](https://github.com/Carl-312/daily-report-site/actions/runs/28768649798)

## 当前实现与问题的对应关系

| 观察到的问题 | 当前行为 | 风险 |
| --- | --- | --- |
| 少量候选也会发布 | v2 记录 `unique_story_count`，但当前仍未配置最小独立主题发布阈值 | 4 条独立候选仍可形成一次显示成功的正式日报 |
| 内容被凑到 10 条 | v2 优先只从相关性 ≥2 的候选选取；核心候选不足目标数时才回退完整代表集 | 极端低供给日仍可能回填相关性较弱内容，诊断可见但尚未阻断发布 |
| 4 条输入被扩展为 10 条输出 | 每个短名单 `article_id` 必须且只能输出一次 | 越界、重复或无输入映射结果会阻断发布 |
| 同一公司占比过高 | v2 主要主体最多 2 条、被提及主体最多 3 条；不足时按固定顺序放宽并记录 | 只有发生显式 `quota_relaxations` 才能超过上限 |
| 一篇新闻被写成多条 | 每个短名单 `article_id` 必须且只能输出一次，并绑定同源 URL | 聚合页需在模型前拆成独立候选，不能由模型自行扩写 |
| 灰度显示成功但数量不足 | scorecard 将不足量作为诊断结论，Actions 本身仍可成功 | 容易把“诊断跑完”误读为“策略通过” |

## 建议的最小修复顺序

### P0：在摘要前固定候选集（已完成）

已增加纯本地、可测试且可重放的选择阶段：

AI 相关性过滤 → 故事去重 → 主体或主题配额 → 按优先级选取最多 10 条。

当前版本不依赖额外模型。结构化目录覆盖中美前沿模型公司、基础设施公司及宽泛科技主体；识别稳定模型家族和未知数字版本，主要主体默认最多 2 条、被提及主体最多 3 条、同模型家族最多 1 条。跨语种同事件先聚类，所有其他候选已经用尽后才按固定次序放宽配额。

冻结的 2026-07-18 快照已把来源分布稳定为 6/2/2，折叠 Apple/OpenAI 诉讼和 Zoox 召回重复，并让 Kimi K3 等中国模型进入短名单；仍需用 2026-07-10 fixture 补充历史主体集中度验收。

### P0：强制每条摘要可回溯到输入来源（已完成）

要求模型返回带 article_id 的结构化条目，并在本地验证：

- 每个 article_id 都来自已选择候选集；
- article_id 必须来自已选择候选集；
- 摘要在证据充足时达到每日目标 10 条，且不大于 `max_summary_items=10`；
- 摘要不得将不存在的链接或标题映射为输入文章。

提示词中的“避免类似主题”只能改善倾向，不能替代这个确定性校验。当前实现使用短 ID 和确定性本地 renderer，未把模型 Markdown 直接作为发布契约。

### P0：把内容质量接入发布决策

质量门至少应检查：

- 独立 article_id 数量；
- 最大主体占比；
- AI 相关候选占比；
- 来源分布和空来源状态；
- 摘要与候选的一一映射。

若不足最小独立主题数，应明确记录 blocked 决策并保留上一份公开 edition，而不是用泛科技条目或重复改写凑数。最低阈值需要产品负责人确认；建议先以 6 个独立主题作为可灰度验证的起点。

### P1：让灰度能证明生产质量

灰度应复用同一份已冻结的正式候选 JSON，并运行与生产相同的选择和摘要契约。若不希望在灰度消耗在线 LLM，也必须在 artifact 中明确标识“未验证 LLM 成稿质量”，不能把结果称为正式 A/B。

scorecard 需要新增：

- unique_article_count；
- unique_topic_count；
- max_entity_share；
- duplicate_story_rejected_count；
- model_family_distribution；
- region_distribution；
- source_distribution；
- promotable 或 not_promotable 决策。

灰度 artifact 当前只保留 7 天。应把去敏后的 scorecard 和决策摘要长期保存到受版本控制的 benchmark，或延长 artifact 保留期，以便比较趋势。

### P1：补足 Pages 部署闭环

为 deploy-pages 的临时失败增加受控重试，并把部署 ID、最终部署状态和上一公开 edition 记录到运行 manifest。生成成功与公开站点成功必须是两个可区分的结论。

## 验收标准

以下条件满足前，不应宣称问题已解决：

1. 用 2026-07-05 和 2026-07-12 fixture 验证：每条输入最多生成 1 个不同 article_id 的摘要，不会把 4 条输入扩展为 10 条。
2. 用 2026-07-10 fixture 验证：10 条选择结果中任一主体不超过配置配额，且回填行为可解释。
3. 用 2026-07-11 fixture 验证：无明确 AI 相关性的候选不会仅为凑数进入 AI 日报。
4. 灰度和正式比较使用同一冻结输入，并在 artifact 中输出可机器读取的质量结论。
5. Pages 部署失败时，manifest 能证明上一公开 edition 保持可访问，并给出可操作的重试或恢复记录。

## 相关文档

- [GitHub Actions 部署与预览](../operations/github-actions.md)
- [Tavily 接入和诊断](../operations/tavily.md)
- [故障排查](../operations/troubleshooting.md)
