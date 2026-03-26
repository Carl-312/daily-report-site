# Daily Report Site

基于 AI 的新闻日报自动生成器，支持本地运行、GitHub Actions 自动生成，以及 GitHub Pages 静态部署。

## 核心特性

- 多源聚合：支持 AIBase、TechCrunch、The Verge、Syft 等来源。
- 双模式摘要：可走 ModelScope API，也可离线生成基础摘要。
- 独立质量检查：`CI` workflow 固定在 `Python 3.12` 上执行 Ruff 与 pytest。
- 轻量主分支：`main` 仅保留最近 7 天的 `data/` 与 `content/`。
- 构建输出隔离：站点统一输出到 `dist/`，不再和工程文档混放。

## 快速开始

项目统一使用 `Python 3.12`。

```bash
mise install
mise use -g python@3.12
pip install -r requirements-dev.txt
```

运行完整流程：

```bash
python main.py run
```

离线模式：

```bash
python main.py run --offline
```

本地预览站点：

```bash
python -m http.server 8000 --directory dist
```

Windows PowerShell 也可以直接使用：

```powershell
.\run_daily.ps1
.\run_daily.ps1 -Offline
.\run_daily.ps1 -NoCommit
```

## 自动化工作流

- `CI`: `.github/workflows/ci.yml`
  - `push` / `pull_request` 触发
  - 安装 `requirements-dev.txt`
  - 运行 `ruff check .`
  - 运行 `ruff format --check .`
  - 运行 `pytest`
- `Daily Report Deploy`: `.github/workflows/deploy.yml`
  - 手动、定时触发
  - 定时任务使用 UTC，当前配置为 `0 14 * * *`，对应北京时间 `22:00`
  - 生成日报并构建 `dist/`
  - 仅在 `main` 分支上执行归档、裁剪、回写与 Pages 发布
  - 将超过 7 天的 `data/` / `content/` 打包上传到 GitHub Release assets
  - 清理超期文件后再提交保留结果
  - 将 `dist/` 作为 Pages artifact 部署

当前站点默认只展示仓库保留窗口内的近期日报，更早历史通过 Release assets 下载。

详细说明见 [handbook/deployment/github-actions.md](handbook/deployment/github-actions.md)、[handbook/deployment/github-pages.md](handbook/deployment/github-pages.md) 和 [handbook/project-rollout.md](handbook/project-rollout.md)。

## 目录结构

```text
daily-report-site/
├── .github/workflows/      # CI 与部署工作流
├── handbook/               # 手写工程文档
├── content/                # 最近 7 天 Markdown 产物
├── data/                   # 最近 7 天 JSON 产物
├── dist/                   # 站点构建输出（Git 忽略）
├── scripts/                # 归档/保留等自动化脚本
├── tests/                  # pytest 测试
├── build.py                # 静态站点生成器
├── main.py                 # CLI 入口
├── config.py               # 配置加载
└── config.yaml             # 项目配置
```

## 文档入口

- 开发规范：[CONTRIBUTING.md](CONTRIBUTING.md)
- 本地运行：[handbook/deployment/local.md](handbook/deployment/local.md)
- GitHub Actions：[handbook/deployment/github-actions.md](handbook/deployment/github-actions.md)
- GitHub Pages：[handbook/deployment/github-pages.md](handbook/deployment/github-pages.md)
- 配置说明：[handbook/guides/configuration.md](handbook/guides/configuration.md)
- 扩展新闻源：[handbook/guides/extending-sources.md](handbook/guides/extending-sources.md)
- 故障排查：[handbook/guides/troubleshooting.md](handbook/guides/troubleshooting.md)
- API 参考：[handbook/api/README.md](handbook/api/README.md)
- 架构说明：[ARCHITECTURE.md](ARCHITECTURE.md)

## License

MIT
