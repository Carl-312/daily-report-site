# GitHub Actions 自动化配置

当前仓库将质量检查与部署拆成两个独立 workflow。

## 工作流概览

```text
.github/workflows/
├── ci.yml
└── deploy.yml
```

## `CI`

用途：只负责质量检查，不混入部署逻辑。

- 触发：`push`、`pull_request`
- Python：`3.12`
- 安装：`pip install -r requirements-dev.txt`
- 执行：
  - `ruff check .`
  - `ruff format --check .`
  - `pytest`

建议将其设为分支保护必过项。

## `Daily Report Deploy`

用途：生成日报、归档历史产物、清理热数据并部署 Pages。

- 触发：`workflow_dispatch`、定时任务
- 手动输入：`skip_generate` 可只重建站点；`enable_tavily` 可对单次手动运行启用 Tavily enrichment；`enable_agihunt` 可对单次非生产运行启用 AGIHunt shadow source；`publish` 明确控制是否发布生产版本
- 定时：GitHub Actions cron 使用 UTC，当前配置为 `36 0 * * *`，对应北京时间 `08:36`
- 说明：刻意避开整点，降低 GitHub Actions `schedule` 在高峰期延迟触发的概率
- Python：`3.12`
- 安装：`pip install -r requirements.txt`
- 关键步骤：
  1. 运行 `python main.py run` 或 `python main.py run --offline`
  2. `skip_generate=true` 时改为运行 `python main.py build`
  3. 摘要阶段必须满足独立新闻条数上限与来源 `article_id` 契约；失败时不生成越界或无输入映射的日报，同一来源可支撑多条独立新闻
  4. 非 `main` 分支，或 `main` 上手动 `publish=false`，上传 `daily-report-preview-<run_id>`，不回写、不归档、不发布 Pages
  5. 仅当 `main` 且为定时任务或手动 `publish=true` 时，执行归档、清理并提交保留后的 `data/` / `content/`
  6. 仅在上述生产模式且 Pages 已启用时，使用 `actions/upload-pages-artifact@v3` 和独立 `deploy` job 发布

## 必要配置

### Secret

如果要启用 AI 摘要，请配置：

| Name | Value |
| --- | --- |
| `MODELSCOPE_API_KEY` | ModelScope API Key |
| `SILICONFLOW_API_KEY` | SiliconFlow API Key（可选，用作 LLM 备用供应商） |
| `AGIHUNT_API_KEY` | AGIHunt Agent API Key（只在 `enable_agihunt=true` 时注入） |

两个 secret 都未配置时，部署 workflow 会自动退回离线模式。

`MODELSCOPE_SECONDARY_MODEL` 是非密钥配置，默认已使用 `moonshotai/Kimi-K2.7-Code`，通常不需要配置为 secret。

AGIHunt 的 source 默认关闭。手动灰度时设定 `enable_agihunt=true` 会传入
`--agihunt on`；如果 `AGIHUNT_API_KEY` 缺失，workflow 会立即失败而不是将
配置错误伪装为空来源。此开关不会改变定时生产任务的默认来源集合。

### 2026-07-14 AGIHunt shadow 状态

`AGIHUNT_API_KEY` 已配置为 Actions Secret 并成功用于非发布 shadow。最新的
[run `29301983421`](https://github.com/Carl-312/daily-report-site/actions/runs/29301983421)
使用 `enable_agihunt=true`、`enable_tavily=false`、`publish=false`，通过生成与 health
gate；preview artifact 根目录的 `agihunt-gray-health.json` 记录 `healthy: true`、
source `ok`、13 个接受候选、5 次物理请求和 `publication_status: published`。该
`published` 仅表示 staged publication 成功；本次 run 没有提交内容、部署 Pages 或运行
发布 job。

此结果是 7 天观察的第 1 天。当前 ModelScope endpoint/token 不支持 Kimi K2.7 Code
provider，摘要安全回退到 SiliconFlow；在得到 provider 已启用的 ModelScope 凭据前，不能
把 Kimi 模型要求标记为已验证，也不能据此提前合并或生产启用 AGIHunt。

如果要手动灰度验证 Tavily enrichment，可额外配置：

| Name | Value |
| --- | --- |
| `TAVILY_API_KEY` | Tavily Search API Key |

该 secret 只在手动触发 `Daily Report Deploy` 且 `enable_tavily=true` 时注入。未配置时，手动开启 Tavily 的运行仍会完成，并在日志中提示回退到去重后的原始文章。不要把真实 secret 写进文档、测试、fixture 或示例提交。

### Workflow 权限

进入 `Settings -> Actions -> General`，将 `Workflow permissions` 设为：

- `Read and write permissions`

因为部署 workflow 需要：

- 推送清理后的 `data/` / `content/`
- 创建或更新 GitHub Release assets
- 部署 GitHub Pages

### GitHub Pages

进入 `Settings -> Pages`，`Source` 选择 `GitHub Actions`。

## 保留策略说明

- `main` 仅保留最近 7 天的 `data/` 与 `content/`
- 更早的数据先打包为 `daily-report-YYYY-MM-DD.tar.gz`
- 归档上传到 Release `daily-report-archive`
- 上传成功后才执行清理，避免先删后丢

当前最小方案只对 `data/` / `content/` 做长期归档；站点本身只展示仓库保留窗口内的内容。

`workflow_dispatch` 在非 `main` 分支上仍可用于手动验证生成流程，但只上传预览 artifact，不会回写仓库、上传归档或发布 Pages。`publish=false` 即使在
`main` 上也保持预览模式。

### 2026-07-10 灰度证据

成功预览 run `29076119648` 的输入为 `skip_generate=true`、`publish=false`、
`enable_tavily=false`；`generate-and-deploy` 成功，`deploy` 跳过，预览 artifact
为 `daily-report-preview-29076119648`。artifact 保留 2026-07-04 至 2026-07-09
内容与 `dist/`，不含 `content/2026-07-10.md`、`data/2026-07-10.json` 或
`dist/2026-07-10.html`。PR #8 仍为 OPEN/Draft（head
`gsd/daily-news-reliability`，base `main`）；本次 run 未发布 Pages，生产 URL 未变。

手动触发时保持 `enable_tavily=false` 会沿用默认路径，不显式启用 Tavily；设为 `true` 时运行 `python main.py run --enrichment on`，用于验证生产 runner 的 Tavily 接线。

Tavily 灰度限制：

- 定时任务不会因为存在 `TAVILY_API_KEY` secret 就自动启用 Tavily。
- `skip_generate=true` 只执行 `python main.py build`，不会验证 enrichment。
- 非 `main` 分支可用于手动验证命令和日志，但不会回写生成的 `data/` / `content/`，也不会发布 Pages。
- 单次 live 结果只能作为接线样本，不作为默认开启或修改 `trusted_domains` 的稳定证据。
- 如果 Tavily timeout、HTTP error、connection error 或 key 缺失，预期行为是 fail-open：主流程继续完成，已有 deduped articles 尽量保留，失败原因写入 JSON 诊断。

手动灰度后检查当天 `data/YYYY-MM-DD.json` 的 `enrichment` 字段：

- `enabled` / `applied` / `skip_reason` / `error`
- `verify_calls` / `refill_calls` / `fallback_calls` / `total_calls`
- `preserved_error_count` / `final_count` / `stop_reason`
- `verify_runs[*].request_outcome` 与 refill runs 的 `request_outcome`

### 2026-07-13 摘要契约预览证据

提交 `adc9bf0` 的 [preview run `29238871654`](https://github.com/Carl-312/daily-report-site/actions/runs/29238871654)
使用 `skip_generate=false`、`enable_tavily=false`、`publish=false`。2 条去重后候选生成 2 条摘要，
`a1/a2` 的来源契约校验通过，artifact 成功生成，`deploy` job 跳过；该 run 未回写仓库或发布
GitHub Pages。它验证的是摘要边界和灰度生成链路，不代表 Tavily 开启或生产发布已验收。

## 手动验证建议

合并前建议分别手动触发一次：

1. `CI`
2. `Daily Report Deploy`

重点检查：

- `dist/` 是否成功上传为 Pages artifact
- Release `daily-report-archive` 是否出现 tar.gz 资产
- `main` 上是否只保留最近 7 天的 `data/` / `content/`
- 手动设置 `enable_tavily=true` 时，日志是否显示 `--enrichment on`
- `data/YYYY-MM-DD.json` 是否包含可复盘的 `enrichment` 诊断
- `data/YYYY-MM-DD.json` 中 `summary.items[*].article_id` 是否均来自 `articles`，且数量不超过 `max_summary_items`
- 聚合来源是否能拆出多条有独立标题和摘要的新闻，同时没有重复事实
- AGIHunt gray 时 `scripts/agihunt_gray_health.py` 已通过，preview artifact 根目录的
  去敏 `agihunt-gray-health.json` 显示健康；health gate 已核对 manifest 与 provenance
  中的频道和原帖 URL，且 `publish=false` artifact 没有发布 Pages

## 相关文档

- GitHub Pages：[`github-pages.md`](github-pages.md)
- 本地运行：[`local.md`](local.md)
- Tavily 接入总览：[`tavily.md`](tavily.md)
