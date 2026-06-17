# GitHub Actions 自动化配置

当前仓库将质量检查、生产部署和 Tavily 隔离灰度拆成三个 workflow。

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
- 手动输入：`skip_generate` 可只重建站点；`publish` 可控制是否提交生成内容并发布 Pages
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

## 必要配置

### Secret

如果要启用 AI 摘要，请配置：

| Name | Value |
| --- | --- |
| `MODELSCOPE_API_KEY` | ModelScope API Key |

未配置时，部署 workflow 会自动退回离线模式。

如果要运行独立的 `Tavily Gray Daily`，需额外配置：

| Name | Value |
| --- | --- |
| `TAVILY_API_KEY` | Tavily Search API Key |

该 secret 只由独立的 `.github/workflows/tavily-gray.yml` 使用。`Daily Report Deploy` 不再注入 `TAVILY_API_KEY`，也不再提供 Tavily 手动灰度开关。不要把真实 secret 写进文档、测试、fixture 或示例提交。

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

`workflow_dispatch` 在非 `main` 分支上仍可用于手动验证生成流程，但不会回写仓库、上传归档或发布 Pages。

手动触发 `Daily Report Deploy` 时只验证生成、归档和发布路径，不会显式启用 Tavily。

## `Tavily Gray Daily`

用途：唯一保留的 GitHub Actions Tavily 灰度入口。

- Workflow：`.github/workflows/tavily-gray.yml`
- 触发：`workflow_dispatch`、定时任务
- 命令：`python3 main.py run --offline --enrichment on`
- 行为：不提交、不发布、不部署，只上传 `gray/tavily/YYYY-MM-DD/` artifact
- Key：缺少 `TAVILY_API_KEY` 时 workflow 直接失败，避免把无 key 样本误判为策略质量

灰度 artifact 重点检查：

- `enabled` / `applied` / `skip_reason` / `error`
- `verify_calls` / `refill_calls` / `fallback_calls` / `total_calls`
- `preserved_error_count` / `final_count` / `stop_reason`
- `verify_runs[*].request_outcome` 与 refill runs 的 `request_outcome`
- `scorecard.json` / `scorecard.md`
- `logs/gray-experiment-overrides.json`
- `logs/gray-config-diff.patch`

## 手动验证建议

合并前建议分别手动触发一次：

1. `CI`
2. `Daily Report Deploy`

重点检查：

- `dist/` 是否成功上传为 Pages artifact
- Release `daily-report-archive` 是否出现 tar.gz 资产
- `main` 上是否只保留最近 7 天的 `data/` / `content/`
- `Daily Report Deploy` 日志中不应出现 `--enrichment on`
- Tavily 验证只通过 `Tavily Gray Daily` artifact 复盘

## 相关文档

- GitHub Pages：[`github-pages.md`](github-pages.md)
- 本地运行：[`local.md`](local.md)
- Tavily 接入总览：[`../guides/tavily-integration.md`](../guides/tavily-integration.md)
