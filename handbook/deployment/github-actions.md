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

## 手动验证建议

合并前建议分别手动触发一次：

1. `CI`
2. `Daily Report Deploy`

重点检查：

- `dist/` 是否成功上传为 Pages artifact
- Release `daily-report-archive` 是否出现 tar.gz 资产
- `main` 上是否只保留最近 7 天的 `data/` / `content/`

## 相关文档

- GitHub Pages：[`github-pages.md`](github-pages.md)
- 本地运行：[`local.md`](local.md)
