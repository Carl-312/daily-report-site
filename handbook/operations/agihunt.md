# AGIHunt 主来源灰度运行手册

AGIHunt 通过官方 Agent API 提供日报覆盖信息和频道原帖候选。当前接入仍是关闭态：`config.yaml` 中的 `sources.agihunt` 必须保持 `false`，只在显式灰度运行中使用 `--agihunt on`。

## 安全边界

- 只调用 `https://agihunt.info/agent/v1` 的官方端点；不抓取 HTML、sitemap 或未公开接口。
- `AGIHUNT_API_KEY` 只来自本地 `.env` 或 GitHub Actions Secret，绝不写入 YAML、fixture、缓存、manifest、日志或日报产物。
- 设备授权需要维护者在网页上确认；不要在 CI 或定时任务中启动授权流程。
- 适配器不使用 LLM 决定候选。日报 Markdown 只作覆盖诊断；可发布条目必须保留频道 API 返回的原帖 URL。

现有摘要器已经把 ModelScope `moonshotai/Kimi-K2.7-Code` 放在主模型之后的第二候选位置。它只在需要生成日报摘要时参与模型回退，不参与 AGIHunt 抓取、筛选或事实扩展。

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
- 每个接受候选的频道、频道内名次、热度、作者、API 日期和日报链接 provenance。

缺少 key、401、426、非法频道或非法日期不能被视作“没有新闻”；source outcome 必须为 `failed` 或 `degraded`，并保留上一版公开 edition。

## GitHub 灰度

1. 在仓库 Settings → Secrets and variables → Actions 中由维护者添加 `AGIHUNT_API_KEY`。
2. 从功能分支手动触发 **Daily Report Deploy**，或在 `main` 上保持 `publish=false`。
3. 设定 `enable_agihunt=true`、`enable_tavily=false`、`publish=false`。工作流会传入 `--agihunt on`，只上传 preview artifact，不会回写仓库或发布 Pages。
4. workflow 会运行 `scripts/agihunt_gray_health.py`；通过后下载
   `daily-report-preview-<run_id>`，检查 `data/`、`content/`、`.runs/`（含
   `agihunt-gray-health.json`）和生成的 `dist/`。

单次灰度健康的最低条件：AGIHunt source 没有认证/兼容性错误、物理请求数不超过 5、所有最终链接是 HTTP(S) 原帖链接、日报 Markdown 显示 `AGI HUNT · agihunt.info` 归因、摘要 URL 与输入候选 URL 一致，且 staged publication 正常完成。自动 health gate 会检查这些可机器验证的条件；人工仍需检查选题质量。`enable_agihunt=true` 但 Secret 缺失时 workflow 会明确失败，不会产生误导性的健康产物。

完成单次接线验证后，仍需至少连续 7 天 `publish=false` shadow，比较频道覆盖、独立故事数、实体集中度、时效、链接可用性和人工重要新闻命中率。只有这段证据满足[接入规划](../development/agihunt-primary-source-plan.md)的 Phase 2 通过条件，才可以把 `sources.agihunt` 改为 `true` 并考虑生产启用。

## 回滚

- 本地或灰度立即使用 `--agihunt off`。
- 生产配置保持或恢复 `sources.agihunt: false`；次级来源会继续运行。
- AGIHunt source 的短暂失败只会使本轮标为 degraded；staged publication 门禁仍保护上一版公开 edition。
