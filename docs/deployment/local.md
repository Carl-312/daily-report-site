# 本地部署指南

快速在本地环境运行 Daily Report Site。

---

## 📋 前置要求

- **Python**: 3.10 或更高版本
- **Git**: 用于克隆仓库
- **PowerShell**: Windows 环境 (或 Bash for Linux/macOS)

---

## 🚀 快速开始

### 1. 克隆仓库

```bash
git clone https://github.com/your-username/daily-report-site.git
cd daily-report-site
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

**依赖列表**:
- `requests`: HTTP 请求
- `beautifulsoup4`: HTML 解析
- `pyyaml`: 配置文件解析
- `markdown`: Markdown 转 HTML
- `python-dotenv`: 环境变量管理
- `Levenshtein`: 文本相似度计算

### 3. 配置环境变量

复制示例配置:
```bash
copy .env.example .env  # Windows
# cp .env.example .env  # Linux/macOS
```

编辑 `.env` 文件:
```bash
# ModelScope API Key (可选，用于 AI 摘要)
MODELSCOPE_API_KEY=sk-your-api-key-here
MODELSCOPE_MODEL=ZhipuAI/GLM-4.7
```

> 💡 **提示**: 如果没有 API Key，可以使用 **离线模式** (见下文)

**获取 API Key**:
1. 访问 [ModelScope 控制台](https://modelscope.cn/my/myaccesstoken)
2. 注册/登录账号
3. 创建 API Token
4. 复制到 `.env` 文件

### 4. 配置新闻源 (可选)

编辑 `config.yaml`:
```yaml
sources:
  aibase: true       # 中文 AI 资讯
  techcrunch: true   # 英文科技新闻
  theverge: true     # 英文科技新闻
  syft: false        # 自建 Syft 实例 (需额外配置)

limits:
  max_articles: 14   # 每天最多文章数
```

---

## 🎯 运行方式

### 方式一: 使用自动化脚本 (推荐)

**PowerShell (Windows)**:
```powershell
# 标准模式 (使用 AI 摘要)
.\run_daily.ps1

# 离线模式 (无需 API Key)
.\run_daily.ps1 -Offline

# 仅生成但不提交到 Git
.\run_daily.ps1 -NoCommit
```

**脚本功能**:
- ✅ 自动检查环境
- ✅ 运行完整流程 (fetch → summarize → build)
- ✅ 自动提交到 Git (可选)
- ✅ 错误处理和日志

### 方式二: 使用 Python CLI

**完整流程**:
```bash
# AI 模式
python main.py run

# 离线模式
python main.py run --offline
```

**分步执行**:
```bash
# 1. 仅抓取新闻
python main.py fetch

# 2. 仅生成摘要 (从已抓取的 JSON)
python main.py summarize

# 3. 仅构建 HTML
python main.py build
```

**测试 API 连接**:
```bash
python main.py test
```

---

## 🌐 本地预览

启动 HTTP 服务器:

```bash
# 进入生成目录
cd docs

# Python 内置服务器
python -m http.server 8000
```

访问: [http://localhost:8000](http://localhost:8000)

**替代方案**:
```bash
# 使用 PHP (如果已安装)
php -S localhost:8000

# 使用 Node.js (如果已安装 http-server)
npx http-server -p 8000
```

---

## 📁 目录结构

运行后的完整目录:

```
daily-report-site/
├── .env                    # 环境变量 (不提交到 Git)
├── config.yaml             # 配置文件
├── main.py                 # CLI 入口
├── build.py                # 静态站点生成器
├── sources/                # 新闻源模块
│   ├── __init__.py
│   ├── aibase.py
│   ├── techcrunch.py
│   └── theverge.py
├── utils/                  # 工具函数
│   ├── dedupe.py
│   ├── fileops.py
│   └── datetime.py
├── prompts/
│   └── daily.md            # AI Prompt 模板
├── data/                   # 生成的 JSON 文件
│   └── 2026-01-21.json
├── content/                # 生成的 Markdown 文件
│   └── 2026-01-21.md
└── docs/                   # 生成的静态站点
    ├── index.html
    ├── archive.html
    ├── 2026-01-21.html
    └── style.css
```

---

## 🔧 常见问题

### Q1: 提示 "ModuleNotFoundError"
**原因**: 依赖未安装  
**解决**:
```bash
pip install -r requirements.txt
```

### Q2: API 调用失败 (status 401)
**原因**: API Key 无效  
**解决**:
1. 检查 `.env` 中的 `MODELSCOPE_API_KEY`
2. 验证 Key 是否正确复制
3. 使用 `python main.py test` 测试连接

### Q3: 离线模式生成的内容质量差
**原因**: 离线模式只做简单格式化  
**建议**:
- 申请免费的 ModelScope API Key
- 或使用其他兼容 OpenAI API 的服务

### Q4: 抓取的文章数量少于预期
**可能原因**:
- 新闻源当天发布文章较少
- 网络问题导致部分请求失败
- `max_articles` 设置过小

**解决**:
```yaml
# config.yaml
limits:
  max_articles: 20  # 增加限制
```

### Q5: Git 提交失败 (Permission denied)
**原因**: 
- 未配置 Git 用户信息
- SSH Key 未设置

**解决**:
```bash
# 配置用户信息
git config --global user.name "Your Name"
git config --global user.email "your.email@example.com"

# 或使用 -NoCommit 参数跳过提交
.\run_daily.ps1 -NoCommit
```

---

## 🛠️ 开发模式

### 启用详细日志

```python
# main.py (在文件开头添加)
import logging
logging.basicConfig(level=logging.DEBUG)
```

### 调试单个新闻源

```python
# test_source.py
from sources.aibase import fetch

articles = fetch()
for article in articles:
    print(article)
```

### 自定义 Prompt

编辑 `prompts/daily.md`:
```markdown
你是一个专业的科技新闻编辑，负责撰写每日资讯摘要。

任务要求:
1. 将提供的新闻列表整理为 Markdown 格式
2. 按重要性排序，优先展示 AI 和前沿科技相关内容
3. 每条新闻包含标题、链接和 50 字内总结
4. 使用友好、专业的语气
...
```

---

## 🚀 下一步

- [配置 GitHub Actions 自动化](github-actions.md)
- [部署到 GitHub Pages](github-pages.md)
- [添加自定义新闻源](../guides/extending-sources.md)

---

**Last Updated**: 2026-01-21
