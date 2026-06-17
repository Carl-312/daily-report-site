# Daily Report Site

AI 驱动的技术新闻日报生成器，自动聚合、摘要并发布每日科技资讯。

## 特性

- **自动化工作流**：GitHub Actions 定时抓取、生成、部署，零人工干预
- **多源聚合**：AIBase、TechCrunch、The Verge、Syft 等主流科技媒体
- **Tavily 隔离灰度**：默认关闭的 post-fetch enrichment，只通过独立 Tavily Gray workflow 做受控验证
- **智能摘要**：ModelScope API（Kimi-K2.5）+ SiliconFlow 备用，支持离线模式
- **轻量架构**：主分支仅保留 7 天数据，历史归档至 Release，站点构建隔离至 `dist/`
- **质量保障**：CI 自动执行 Ruff 检查和 pytest 测试

## 当前项目上下文

- 生产日报路径是 `Daily Report Deploy`：抓取新闻、生成摘要、构建站点、归档旧数据并发布 Pages。
- Tavily 不是默认新闻源，也不在生产 deploy workflow 中灰度开启；`config.yaml` 仍保持 `enrichment.enabled: false`。
- GitHub Actions 上唯一保留的 Tavily 灰度入口是 `Tavily Gray Daily`，它运行 `python3 main.py run --offline --enrichment on`，只上传 gray artifact，不提交、不发布、不部署。
- 最近一次有效 Tavily gray 样本确认 key 已恢复，但结果仍是 `8 / 10`，还不支持默认开启；下一轮测试必须一次只改一个变量。
- `data/` 和 `content/` 只保留最近 7 天，超期内容归档到 GitHub Release `daily-report-archive`。

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

# 本地显式启用 Tavily enrichment（默认关闭；GitHub 灰度只走 Tavily Gray Daily）
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
- Tavily：`Daily Report Deploy` 不再提供 Tavily 灰度开关；只保留独立的 `Tavily Gray Daily`

**Tavily 隔离灰度**（`.github/workflows/tavily-gray.yml`）：
- 触发：每天 12:56 UTC（北京时间 20:56）或手动触发
- 运行：`python3 main.py run --offline --enrichment on`
- 输出：`gray/tavily/YYYY-MM-DD/` artifact，包含 `scorecard.json`、`scorecard.md`、`enrichment-summary.json` 和配置 diff
- 边界：只验证 Tavily 策略，不提交内容、不发布 Pages、不改变生产默认配置

详见 [handbook/deployment/](handbook/deployment/) 目录。

## 项目结构

```
daily-report-site/
├── .github/workflows/   # CI、生产部署与 Tavily 隔离灰度
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
- [handbook/guides/tavily-gray-next-steps.md](handbook/guides/tavily-gray-next-steps.md) - Tavily 当前灰度状态与下一轮测试策略
- [handbook/guides/extending-sources.md](handbook/guides/extending-sources.md) - 扩展新闻源
- [handbook/deployment/](handbook/deployment/) - 部署指南

## License

MIT
