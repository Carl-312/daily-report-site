# Daily Report Site

AI 驱动的技术新闻日报生成器，自动聚合、摘要并发布每日科技资讯。

## 特性

- **自动化工作流**：GitHub Actions 定时抓取、生成、部署，零人工干预
- **多源聚合**：AIBase、TechCrunch、The Verge、Syft 等主流科技媒体
- **Tavily 科技新闻补全**：可选的 post-fetch enrichment，用于保留 source 结果、标注验证置信度，并补入可信科技新闻
- **智能摘要**：ModelScope API（Kimi-K2.5）+ SiliconFlow 备用，支持离线模式
- **轻量架构**：主分支仅保留 7 天数据，历史归档至 Release，站点构建隔离至 `dist/`
- **质量保障**：CI 自动执行 Ruff 检查和 pytest 测试

## 快速开始

**环境要求**：Python 3.12

```bash
# 安装依赖
pip install -r requirements-dev.txt

# 配置 API Key（可选，不配置则使用离线模式）
cp .env.example .env
# 编辑 .env 填入 MODELSCOPE_API_KEY 或 SILICONFLOW_API_KEY

# 运行完整流程
python main.py run

# 离线模式（无需 API Key）
python main.py run --offline

# 显式启用 Tavily 科技新闻补全（默认关闭）
TAVILY_API_KEY=... python3 main.py fetch --enrichment on
TAVILY_API_KEY=... python3 main.py run --offline --enrichment on

# 安全关闭 Tavily 增强
python3 main.py fetch --enrichment off
python3 main.py run --offline --enrichment off

# 本地预览
python -m http.server 8000 --directory dist
```

**Windows PowerShell**：
```powershell
.\run_daily.ps1          # 完整流程
.\run_daily.ps1 -Offline # 离线模式
.\run_daily.ps1 -NoCommit # 不提交 Git
```

## 自动化部署

**CI 检查**（`.github/workflows/ci.yml`）：
- 触发：`push` / `pull_request`
- 执行：Ruff 代码检查 + pytest 测试

**每日发布**（`.github/workflows/deploy.yml`）：
- 触发：每天 00:36 UTC（北京时间 08:36）或手动触发
- 说明：刻意避开整点，降低 GitHub Actions `schedule` 在高峰期延迟触发的概率
- 流程：抓取新闻 → AI 摘要 → 构建站点 → 归档历史 → 部署 Pages
- 数据保留：main 分支保留最近 7 天，超期数据归档至 GitHub Release
- Tavily：该生产发布 workflow 的定时任务不默认开启 Tavily；手动 `enable_tavily=true` 可临时启用

**Tavily 灰度日报**（`.github/workflows/tavily-gray.yml`）：
- 触发：每天 12:56 UTC（北京时间 20:56）或手动选择受控实验
- 定时 main 运行：强制 `--enrichment on`，仅在 safety gate 证明 `final_count >= source_valid_count` 时回写 `data/` / `content/`
- 手动实验运行：只上传 7 天 artifact，不回写仓库
- 数据保留：回写前复用保留脚本，main 分支仍只保留最近 7 天

详见 [handbook/deployment/](handbook/deployment/) 目录。

## 项目结构

```
daily-report-site/
├── .github/workflows/   # CI 与部署工作流
├── sources/             # 新闻源适配器（aibase, techcrunch, theverge, syft）
├── prompts/             # AI 摘要提示词模板
├── scripts/             # 归档与清理脚本
├── tests/               # pytest 测试
├── handbook/            # 详细文档
├── content/             # Markdown 产物（最近 7 天）
├── data/                # JSON 数据（最近 7 天）
├── dist/                # 站点构建输出（Git 忽略）
├── main.py              # CLI 入口
├── build.py             # 静态站点生成器
├── summarizer.py        # AI 摘要模块
├── config.py            # 配置管理
└── config.yaml          # 项目配置
```

## 文档

- [ARCHITECTURE.md](ARCHITECTURE.md) - 系统架构与数据流
- [CONTRIBUTING.md](CONTRIBUTING.md) - 开发规范
- [handbook/guides/configuration.md](handbook/guides/configuration.md) - 配置说明
- [handbook/guides/tavily-integration.md](handbook/guides/tavily-integration.md) - Tavily 使用、诊断和灰度说明
- [handbook/guides/extending-sources.md](handbook/guides/extending-sources.md) - 扩展新闻源
- [handbook/deployment/](handbook/deployment/) - 部署指南

## License

MIT
