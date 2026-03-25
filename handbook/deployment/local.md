# 本地运行指南

## 前置要求

- `Python 3.12`
- Git
- Windows PowerShell 或 Bash

推荐先对齐项目环境：

```bash
mise install
mise use -g python@3.12
```

## 安装依赖

运行时：

```bash
pip install -r requirements.txt
```

开发、测试和格式化：

```bash
pip install -r requirements-dev.txt
```

## 配置环境变量

在仓库根目录准备 `.env`：

```bash
MODELSCOPE_API_KEY=sk-your-api-key
MODELSCOPE_MODEL=moonshotai/Kimi-K2.5
```

没有 API Key 时可直接使用离线模式。

## 运行方式

完整流程：

```bash
python main.py run
```

离线模式：

```bash
python main.py run --offline
```

分步执行：

```bash
python main.py fetch
python main.py summarize
python main.py build
```

Windows PowerShell：

```powershell
.\run_daily.ps1
.\run_daily.ps1 -Offline
.\run_daily.ps1 -NoCommit
```

## 本地预览

站点构建输出位于 `dist/`：

```bash
python -m http.server 8000 --directory dist
```

访问 <http://localhost:8000>。

## 当前目录职责

```text
data/       最近 7 天 JSON
content/    最近 7 天 Markdown
dist/       当前站点构建输出
handbook/   手写文档
```

注意：

- `dist/` 不进入 Git
- `data/` / `content/` 超过 7 天会在部署流程中归档并清理
- 当前站点默认只展示仓库保留窗口内的近期日报

## 本地质量检查

```bash
ruff check .
ruff format --check .
pytest
```

## 相关文档

- GitHub Actions：[`github-actions.md`](github-actions.md)
- GitHub Pages：[`github-pages.md`](github-pages.md)
- 配置说明：[`../guides/configuration.md`](../guides/configuration.md)
