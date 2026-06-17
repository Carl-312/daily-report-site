# GitHub Actions 自动化配置

当前仓库将质量检查与部署拆成两个独立 workflow。

## 工作流概览

```text
.github/workflows/
├── ci.yml
├── deploy.yml
└── tavily-gray.yml
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
- 手动输入：`skip_generate` 可只重建站点；`enable_tavily` 可对单次手动运行启用 Tavily enrichment
- 定时：GitHub Actions cron 使用 UTC，当前配置为 `36 0 * * *`，对应北京时间 `08:36`
- 说明：刻意避开整点，降低 GitHub Actions `schedule` 在高峰期延迟触发的概率
- Python：`3.12`
- 安装：`pip install -r requirements.txt`
- 关键步骤：
  1. 运行 `python main.py run` 或 `python main.py run --offline`
  2. 构建 `dist/`
  3. 仅在 `main` 分支上执行 `python scripts/manage_retention.py bundle --keep-days 7`
  4. 仅在 `main` 分支上上传归档到 GitHub Release `daily-report-archive`
  5. 仅在 `main` 分支上执行 `python scripts/manage_retention.py prune --keep-days 7`
  6. 仅在 `main` 分支上提交保留后的 `data/` / `content/`
  7. 仅在 `main` 分支上上传 `dist/` 为 Pages artifact 并发布

该 workflow 的定时任务仍不显式启用 Tavily；只有手动触发且设置
`enable_tavily=true` 时才会追加 `--enrichment on`。

## `Tavily Gray Daily`

用途：每天运行受控 Tavily 灰度，上传诊断 artifact，并在 `main` 的定时运行中把灰度生成的
`data/YYYY-MM-DD.json` 与 `content/YYYY-MM-DD.md` 保存为仓库内最终报告。

- 触发：`workflow_dispatch`、定时任务
- 手动输入：`experiment` 只允许 `baseline`、`budget_9`、`domain_priority_media`
- 定时：GitHub Actions cron 使用 UTC，当前配置为 `56 12 * * *`，对应北京时间 `20:56`
- Python：`3.12`
- 安装：`pip install -r requirements.txt`
- 关键步骤：
  1. 写入受控灰度实验 override
  2. 执行 `python3 main.py run --offline --enrichment on`
  3. 收集 `report.json`、`report.md`、summary、scorecard 和日志
  4. 上传 Tavily gray artifact，保留 7 天
  5. 仅在 `main` 分支的定时运行中执行 `python scripts/manage_retention.py prune --keep-days 7`
  6. 仅在 `main` 分支的定时运行中提交保留后的 `data/` / `content/`

手动灰度实验不会回写仓库，避免 `budget_9` 或 `domain_priority_media` 的单次实验结果被误保存为最终报告。

## 必要配置

### Secret

如果要启用 AI 摘要，请配置：

| Name | Value |
| --- | --- |
| `MODELSCOPE_API_KEY` | ModelScope API Key |

未配置时，部署 workflow 会自动退回离线模式。

如果要手动灰度验证 Tavily enrichment，可额外配置：

| Name | Value |
| --- | --- |
| `TAVILY_API_KEY` | Tavily Search API Key |

该 secret 有两个用途：

- 手动触发 `Daily Report Deploy` 且 `enable_tavily=true` 时注入；未配置时，手动开启 Tavily 的运行仍会完成，并在日志中提示回退到去重后的原始文章。
- `Tavily Gray Daily` 每日灰度需要该 secret；缺失时灰度 workflow 会失败，避免把未验证的灰度结果保存为最终报告。

不要把真实 secret 写进文档、测试、fixture 或示例提交。

### Workflow 权限

进入 `Settings -> Actions -> General`，将 `Workflow permissions` 设为：

- `Read and write permissions`

因为部署 workflow 需要：

- 推送清理后的 `data/` / `content/`
- 创建或更新 GitHub Release assets
- 部署 GitHub Pages

`Tavily Gray Daily` 的 `main` 定时运行也需要推送清理后的 `data/` / `content/`。

### GitHub Pages

进入 `Settings -> Pages`，`Source` 选择 `GitHub Actions`。

## 保留策略说明

- `main` 仅保留最近 7 天的 `data/` 与 `content/`
- 更早的数据先打包为 `daily-report-YYYY-MM-DD.tar.gz`
- 归档上传到 Release `daily-report-archive`
- 上传成功后才执行清理，避免先删后丢

当前最小方案只对 `data/` / `content/` 做长期归档；站点本身只展示仓库保留窗口内的内容。

`workflow_dispatch` 在非 `main` 分支上仍可用于手动验证生成流程，但不会回写仓库、上传归档或发布 Pages。

手动触发时保持 `enable_tavily=false` 会沿用默认路径，不显式启用 Tavily；设为 `true` 时运行 `python main.py run --enrichment on`，用于验证生产 runner 的 Tavily 接线。

Tavily 灰度限制：

- `Daily Report Deploy` 定时任务不会因为存在 `TAVILY_API_KEY` secret 就自动启用 Tavily。
- `Tavily Gray Daily` 定时任务会显式运行 `--enrichment on`，但只有 `main` 的定时运行会回写最终报告。
- `Tavily Gray Daily` 手动实验只上传 artifact，不回写生成的 `data/` / `content/`。
- `skip_generate=true` 只执行 `python main.py build`，不会验证 enrichment。
- 非 `main` 分支可用于手动验证命令和日志，但不会回写生成的 `data/` / `content/`，也不会发布 Pages。
- 单次 live 结果只能作为接线样本，不作为默认开启或修改 `trusted_domains` 的稳定证据。
- 如果 Tavily timeout、HTTP error、connection error 或 key 缺失，预期行为是 fail-open：主流程继续完成，已有 deduped articles 尽量保留，失败原因写入 JSON 诊断。

手动灰度后检查当天 `data/YYYY-MM-DD.json` 的 `enrichment` 字段：

- `enabled` / `applied` / `skip_reason` / `error`
- `verify_calls` / `refill_calls` / `fallback_calls` / `total_calls`
- `preserved_error_count` / `final_count` / `stop_reason`
- `verify_runs[*].request_outcome` 与 refill runs 的 `request_outcome`

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

## 相关文档

- GitHub Pages：[`github-pages.md`](github-pages.md)
- 本地运行：[`local.md`](local.md)
- Tavily 接入总览：[`../guides/tavily-integration.md`](../guides/tavily-integration.md)
