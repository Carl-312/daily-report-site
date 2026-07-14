# AGIHunt 主来源灰度运行手册

AGIHunt 通过官方 Agent API 提供日报覆盖信息和频道原帖候选。当前接入仍是关闭态：`config.yaml` 中的 `sources.agihunt` 必须保持 `false`，只在显式灰度运行中使用 `--agihunt on`。

## 当前验证状态（2026-07-14）

- 本地授权样本已完成第 1/2 天：`/channels`、日报和 `models` 频道共 3 次串行物理请求，
  去敏记录健康；确认了 12 个频道 slug、条目的关键字段、ISO 8601 UTC
  `published_at` 与数值型 `hot`。日报仍只作覆盖诊断。
- [GitHub shadow 第 1 天](https://github.com/Carl-312/daily-report-site/actions/runs/29301983421)
  在 `enable_agihunt=true`、`enable_tavily=false`、`publish=false` 下通过；artifact 的
  `agihunt-gray-health.json` 为 `healthy: true`，source 为 `ok`，接受 13 个候选、使用 5
  次请求，且没有发布 Pages 或回写生成内容。
- `AGIHUNT_API_KEY` 已成功用于本地检查和 Actions shadow，但文档不记录其值。仍需第 2 天
  样本与连续 7 天 shadow，才可考虑把 `sources.agihunt` 改为 `true` 或生产启用。
- 早期摘要运行没有满足 ModelScope Kimi 要求：当时 endpoint/token 对 Kimi K2.7 Code 返回
  “无可用 provider”，因此安全回退到 SiliconFlow。即使使用[官方模型页](https://www.modelscope.cn/models/moonshotai/Kimi-K2.7-Code/summary)
  所列的 `moonshotai/Kimi-K2.7-Code:Moonshot` 也未通过。维护者随后将第二候选改为
  `Tencent-Hunyuan/Hy3`；[run `29305758611`](https://github.com/Carl-312/daily-report-site/actions/runs/29305758611)
  实际尝试后同样得到空摘要和 `SummaryQualityError`，最终仍安全回退到 SiliconFlow。该
  模型尚未通过验证，且本次同日模型试验不计入新的 shadow 通过日。
- 上述早期 `--summary-mode ai` 验证没有产出可验证 AI 摘要：配置的主模型端点
  返回“无可用 provider”，备用端点返回空 `choices`。两者均不能形成通过本地契约的
  `required_ai` 结果，因此不得记录为模型或提示词通过。
- 后续 ModelScope 连通修复已用 `ZhipuAI/GLM-5.2` 和 `enable_thinking=false` 完成
  14 篇真实输入验证：响应包含非空 `choices`，7 条摘要通过完整合同。这个新结果证明当前
  摘要 API 路径可用，但不会把早期 `editorial_review` 产物追溯改写为 AI 结果。
- 最新健康产物位于
  `tmp/agihunt-trending-gray-2026-07-14-prompt-examples-reviewed-replay-v1/`。它明确记录
  `summary_mode: reviewed`、摘要 `policy: offline`、`provider: editorial_review` 和
  `publish: false`；10/10 条摘要均为 35–41 个可见字符。该产物只证明人工复核文本、
  本地契约与隔离渲染链路健康，不是 AI 摘要证据。

## 安全边界

- 只调用 `https://agihunt.info/agent/v1` 的官方端点；不抓取 HTML、sitemap 或未公开接口。
- `AGIHUNT_API_KEY` 只来自本地 `.env` 或 GitHub Actions Secret，绝不写入 YAML、fixture、缓存、manifest、日志或日报产物。
- 默认仅从环境读取 HTTP(S) proxy / `NO_PROXY` 以适配受控网络；不会使用环境 netrc
  默认认证。需要强制直连时可设 `agihunt.use_environment_proxy: false`。
- 设备授权需要维护者在网页上确认；不要在 CI 或定时任务中启动授权流程。
- 适配器不使用 LLM 决定候选。日报 Markdown 只作覆盖诊断；可发布条目必须保留频道 API 返回的原帖 URL。

`Tencent-Hunyuan/Hy3` 的非流式响应已确认违反单 JSON 响应协议，因此已从摘要器默认
回退链移除。ModelScope 模型选择只影响日报摘要，不参与 AGIHunt 抓取、筛选或事实扩展。

## Phase 0 最小在线检查

用户完成设备授权并将 key 安全放入本地 `.env` 后，先运行：

```bash
python scripts/agihunt_live_smoke.py --confirm-live-request --channel models
```

该命令不会启动设备授权，也不会打印 key。它按顺序最多发出三次物理请求：
`/channels`、当日 `/report`、一个频道的 `/items`；重试同样计入三次上限。结果仅将
字段形状、时间格式、域名、哈希和请求统计写至
`.runs/agihunt-phase0-YYYY-MM-DD.json`，不保留标题、正文、作者、完整原帖 URL 或
日报 Markdown。若十分钟缓存使本次没有物理请求，记录会明确判为非 live evidence；
不要为了重跑而绕过缓存，等待新日期或缓存 TTL 后再执行。连续两天保存该记录并人工
核对后，再固定频道与候选规则。

## Trending 能力与隔离灰度

官方 Agent skill v1.2.2 没有公开全局 `Trending` 端点，也没有为频道条目声明
`limit`、`cursor` 或 `page` 参数；不得猜测或探测这些路由/参数。已验证的日趋势等价输入是
各频道的 `GET /channel/{slug}/items?day=YYYY-MM-DD&sort=hot`：每个频道返回 top-100，
由本地确定性策略筛选。当前四频道各保留前 6 条作为去重缓冲，最终最多输出 20 条独立
候选，仍只消耗日报加四频道的 5 次请求预算。

需要一次完整、非生产的本地验证时，执行：

```bash
python scripts/agihunt_trending_gray.py \
  --confirm-live-request \
  --summary-mode ai \
  --output-root tmp/agihunt-trending-gray-YYYY-MM-DD
```

该命令始终以 `publish=false` 的隔离目录运行，不修改生产 `data/`、`content/`、`dist/`、
`.publication/` 或 Pages。默认使用确定性离线摘要；涉及提示词修改时传入 `--summary-mode ai`，
以验证配置的模型实际遵守摘要契约。`ai` 模式只接受 `policy: required_ai` 的结果；空
`choices`、离线结果或人工复核结果都会失败，不能借用 `ai` 标签。人工复核回放必须保持
`summary_mode: reviewed`、非 AI policy 和明确的 `editorial_review` provenance。它会写入：

- `agihunt-trending-candidates.private.json`：标题、摘要、发布时间、原帖 URL、
  `channel_hot` / 频道 provenance、请求计数，以及 Trending、分页和日期能力边界；
- `agihunt-trending-verification.json`：灰度健康、候选数量、`publish=false` 状态、每条摘要
  35–50 个可见字符的优先目标、30 字最低要求、80 字完整单句上限（无冒号、无省略号、
  无截断）、摘要 provenance，以及读者 HTML 中未暴露原帖 URL 或 `article_id` 的检查结果。

## 本地 shadow

在授权并安全配置 `AGIHUNT_API_KEY` 后，先执行非发布抓取：

```bash
python main.py fetch --agihunt on --enrichment off
```

需要检查完整的离线生成链路时：

```bash
python main.py run --offline --agihunt on --enrichment off
```

单次运行最多发出 5 次串行网络请求（日报、三个核心频道和一个补充频道；受控重试也计入此预算）。同 URL 十分钟内应命中临时缓存。运行清单位于 `.runs/<date>/<run-id>/manifest.json`，其中 `sources.agihunt` 应记录：

- `network_requests`、`cache_hits`、原始条目和接受条目数；
- `report_not_ready`、限流、配额或 schema 失败的明确 reason code；
- 每个接受候选的 `channel_hot` retrieval、频道、频道内名次、热度、作者、API 日期和日报链接 provenance。

缺少 key、401、426、非法频道或非法日期不能被视作“没有新闻”；source outcome 必须为 `failed` 或 `degraded`，并保留上一版公开 edition。

## GitHub 灰度

1. 在仓库 Settings → Secrets and variables → Actions 中由维护者添加 `AGIHUNT_API_KEY`。
2. 从功能分支手动触发 **Daily Report Deploy**，或在 `main` 上保持 `publish=false`。
3. 设定 `enable_agihunt=true`、`enable_tavily=false`、`publish=false`。工作流会传入 `--agihunt on`，只上传 preview artifact，不会回写仓库或发布 Pages。
4. workflow 会运行 `scripts/agihunt_gray_health.py`；通过后下载
   `daily-report-preview-<run_id>`，检查根目录的去敏
   `agihunt-gray-health.json`、`data/`、`content/` 和生成的 `dist/`。`.runs/`
   保持隐藏且不上传，以免将运行中间物带入 artifact。

单次灰度健康的最低条件：AGIHunt source 没有认证/兼容性错误、物理请求数不超过 5、所有最终链接是 HTTP(S) 原帖链接、日报 Markdown 显示 `AGI HUNT · agihunt.info` 归因、摘要 URL 与输入候选 URL 一致，且 staged publication 正常完成。自动 health gate 会检查这些可机器验证的条件；人工仍需检查选题质量。`enable_agihunt=true` 但 Secret 缺失时 workflow 会明确失败，不会产生误导性的健康产物。

完成单次接线验证后，仍需至少连续 7 天 `publish=false` shadow，比较频道覆盖、独立故事数、实体集中度、时效、链接可用性和人工重要新闻命中率。只有这段证据满足[接入规划](../development/agihunt-primary-source-plan.md)的 Phase 2 通过条件，才可以把 `sources.agihunt` 改为 `true` 并考虑生产启用。

## 回滚

- 本地或灰度立即使用 `--agihunt off`。
- 生产配置保持或恢复 `sources.agihunt: false`；次级来源会继续运行。
- AGIHunt source 的短暂失败只会使本轮标为 degraded；staged publication 门禁仍保护上一版公开 edition。
