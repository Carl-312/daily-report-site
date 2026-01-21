# 故障排查手册

Daily Report Site 常见问题和解决方案。

---

## 🔍 诊断流程

遇到问题时，按以下顺序检查:

1. ✅ **环境配置**: 检查 Python 版本、依赖安装
2. ✅ **配置文件**: 验证 `config.yaml` 和 `.env`
3. ✅ **网络连接**: 测试新闻源和 API 可达性
4. ✅ **日志输出**: 查看详细错误信息
5. ✅ **权限问题**: 检查文件/目录权限、Git 权限

---

## 🐛 常见问题

### 1. 依赖相关

#### ❌ ModuleNotFoundError: No module named 'xxx'

**症状**:
```
ModuleNotFoundError: No module named 'requests'
```

**原因**: 依赖未安装或虚拟环境未激活

**解决**:

```bash
# 安装依赖
pip install -r requirements.txt

# 如果使用虚拟环境
python -m venv venv
.\venv\Scripts\activate  # Windows
# source venv/bin/activate  # Linux/macOS
pip install -r requirements.txt
```

#### ❌ 版本冲突: ERROR: pip's dependency resolver...

**症状**:
```
ERROR: pip's dependency resolver does not currently take into account all the packages that are installed.
```

**解决**:

```bash
# 升级 pip
python -m pip install --upgrade pip

# 清理缓存重新安装
pip cache purge
pip install -r requirements.txt
```

---

### 2. API 相关

#### ❌ API 调用失败 (401 Unauthorized)

**症状**:
```
🤖 Generating summary...
   ❌ API Error: 401 Unauthorized
```

**原因**: API Key 无效或未配置

**解决**:

1. **检查 `.env` 文件**:
   ```bash
   # .env
   MODELSCOPE_API_KEY=sk-your-actual-key-here
   ```

2. **验证 API Key**:
   ```bash
   python main.py test
   ```

3. **重新获取 API Key**:
   - 访问 [ModelScope](https://modelscope.cn/my/myaccesstoken)
   - 创建新 Token
   - 复制到 `.env`

#### ❌ API 调用超时 (Timeout)

**症状**:
```
requests.exceptions.ReadTimeout: HTTPSConnectionPool...
```

**原因**: 
- 网络不稳定
- API 服务响应慢

**解决**:

```python
# 在 summarizer.py 中增加超时时间
response = requests.post(
    url,
    headers=headers,
    json=payload,
    timeout=60,  # 从 30 增加到 60 秒
    stream=True
)
```

#### ❌ API 额度耗尽 (429 Too Many Requests)

**症状**:
```
🤖 Generating summary...
   ❌ API Error: 429 Too Many Requests
```

**解决**:

**临时方案** - 使用离线模式:
```bash
python main.py run --offline
```

**长期方案**:
1. 升级 API 套餐
2. 切换到其他兼容的 LLM 服务

---

### 3. 新闻源抓取

#### ❌ 某个新闻源返回 0 篇文章

**症状**:
```
📡 Fetching news...
   AIBase: 0 articles
   TechCrunch: 5 articles
```

**可能原因**:
1. 网站结构变化 (HTML 解析失效)
2. 网站访问限制
3. 网络问题

**解决**:

**调试单个源**:
```python
# test_source.py
from sources.aibase import fetch

articles = fetch()
print(f"Fetched {len(articles)} articles")
for article in articles[:3]:
    print(article)
```

**临时禁用失败的源**:
```yaml
# config.yaml
sources:
  aibase: false  # 暂时禁用
  techcrunch: true
  theverge: true
```

#### ❌ 请求被拦截 (403 Forbidden)

**症状**:
```
requests.exceptions.HTTPError: 403 Forbidden
```

**原因**: 网站检测到爬虫

**解决**:

添加 User-Agent:
```python
# sources/xxx.py
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}
response = requests.get(url, headers=headers)
```

---

### 4. 文件和路径

#### ❌ FileNotFoundError: [Errno 2] No such file or directory

**症状**:
```
FileNotFoundError: [Errno 2] No such file or directory: 'data/2026-01-21.json'
```

**原因**: 目录不存在

**解决**:

```bash
# 手动创建目录
mkdir data content docs

# 或修改代码自动创建
# utils/fileops.py
from pathlib import Path

def save_json(directory, filename, data):
    Path(directory).mkdir(parents=True, exist_ok=True)
    # ...
```

#### ❌ PermissionError: [Errno 13] Permission denied

**症状**:
```
PermissionError: [Errno 13] Permission denied: 'docs/index.html'
```

**原因**: 
- 文件被占用 (如浏览器正在预览)
- 权限不足

**解决**:

```bash
# 关闭占用文件的程序
# 或使用管理员权限运行

# Windows PowerShell (以管理员身份)
python main.py run
```

---

### 5. Git 相关

#### ❌ Git 提交失败: Permission denied

**症状**:
```
git@github.com: Permission denied (publickey).
```

**原因**: SSH Key 未配置

**解决**:

**方案 1**: 使用 HTTPS (简单)
```bash
# 修改远程仓库 URL
git remote set-url origin https://github.com/username/repo.git
```

**方案 2**: 配置 SSH Key
```bash
# 生成 SSH Key
ssh-keygen -t ed25519 -C "your.email@example.com"

# 添加到 GitHub
cat ~/.ssh/id_ed25519.pub
# 复制内容到 GitHub Settings → SSH Keys
```

#### ❌ Git 提交失败: Author identity unknown

**症状**:
```
fatal: empty ident name (for <>) not allowed
```

**解决**:

```bash
git config --global user.name "Your Name"
git config --global user.email "your.email@example.com"
```

#### ❌ 冲突: refusing to merge unrelated histories

**症状**:
```
fatal: refusing to merge unrelated histories
```

**解决**:

```bash
git pull origin main --allow-unrelated-histories
git push origin main
```

---

### 6. GitHub Actions

#### ❌ Actions 工作流失败: "API Key not found"

**症状**: 
- Actions 日志显示 `MODELSCOPE_API_KEY not found`

**解决**:

1. **检查 Secret 是否已添加**:
   - Settings → Secrets → Actions
   - 确认名称为 `MODELSCOPE_API_KEY`

2. **检查工作流配置**:
   ```yaml
   # .github/workflows/daily-report.yml
   - name: Run daily report
     env:
       MODELSCOPE_API_KEY: ${{ secrets.MODELSCOPE_API_KEY }}  # 正确
   ```

#### ❌ Actions 权限错误: "Permission denied (push)"

**症状**:
```
remote: Permission to username/repo.git denied
```

**解决**:

1. **Settings** → **Actions** → **General**
2. **Workflow permissions** → 选择 **Read and write permissions**
3. 勾选 **Allow GitHub Actions to create and approve pull requests**
4. 点击 **Save**

#### ❌ Actions 未自动运行

**症状**: Cron 定时任务未触发

**可能原因**:
1. Cron 表达式错误
2. 仓库超过 60 天未活跃
3. Actions 被禁用

**解决**:

**检查 Cron 表达式**:
```yaml
# 使用 https://crontab.guru/ 验证
on:
  schedule:
    - cron: '0 1 * * *'  # 每天 UTC 01:00
```

**重新激活**:
```bash
# 进行一次提交以激活仓库
git commit --allow-empty -m "Keep repo active"
git push
```

**手动触发测试**:
- Actions 标签页 → Run workflow

---

### 7. 站点生成

#### ❌ 生成的 HTML 样式错误

**症状**: 页面显示混乱，CSS 未加载

**原因**: CSS 路径错误

**解决**:

```python
# build.py - 检查模板中的路径
ARTICLE_TEMPLATE = """
<head>
  <!-- 错误: 绝对路径 -->
  <link rel="stylesheet" href="/style.css">
  
  <!-- 正确: 相对路径 -->
  <link rel="stylesheet" href="style.css">
</head>
"""
```

#### ❌ Markdown 渲染错误

**症状**: Markdown 未转换为 HTML

**解决**:

```bash
# 检查 markdown 库是否安装
pip install markdown

# 或升级到最新版
pip install --upgrade markdown
```

---

### 8. 配置错误

#### ❌ YAMLLoadWarning: calling yaml.load() without Loader

**症状**:
```
YAMLLoadWarning: calling yaml.load() without Loader is deprecated
```

**解决**:

```python
# config.py
import yaml

# 错误
data = yaml.load(f)

# 正确
data = yaml.safe_load(f)
```

#### ❌ UnicodeDecodeError: 'utf-8' codec can't decode

**症状**:
```
UnicodeDecodeError: 'utf-8' codec can't decode byte 0xff
```

**解决**:

```python
# 修改文件打开方式
with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
    content = f.read()
```

---

## 🛠️ 调试技巧

### 启用详细日志

```python
# main.py (在文件开头添加)
import logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
```

### 检查环境

```bash
# Python 版本
python --version  # 应 >= 3.10

# 已安装的包
pip list

# 验证配置
python -c "import yaml; print(yaml.safe_load(open('config.yaml')))"
```

### 逐步调试

```python
# test_debug.py
from sources import fetch_all
from config import get_config

cfg = get_config()

print("1. Testing configuration...")
print(f"   API Key: {cfg.api_key[:10]}...")

print("2. Testing news sources...")
articles = fetch_all(
    enabled_sources=cfg.sources,
    max_articles=cfg.max_articles,
)
print(f"   Fetched {len(articles)} articles")

print("3. Testing summarization...")
from summarizer import test_connection
test_connection()
```

---

## 📊 性能问题

### ❌ 运行速度慢

**症状**: 完整流程超过 60 秒

**分析**:
```bash
# 使用 time 命令测量
python main.py run

# 分步测量
python -m cProfile -s cumulative main.py run > profile.txt
```

**优化**:

**并发抓取**:
```python
from concurrent.futures import ThreadPoolExecutor

with ThreadPoolExecutor(max_workers=5) as executor:
    futures = [executor.submit(fetch_fn) for fetch_fn in fetch_functions]
    results = [f.result() for f in futures]
```

**减少文章数量**:
```yaml
# config.yaml
limits:
  max_articles: 10  # 从 14 减少到 10
```

---

## 🔗 获取帮助

### 自助资源

- **文档**: [docs/](../README.md)
- **示例**: `content/` 中的生成样本
- **测试**: `python main.py test`

### 社区支持

- **GitHub Issues**: 报告 Bug
- **GitHub Discussions**: 提问和讨论
- **Pull Requests**: 贡献代码

### 提交 Issue 时请提供

1. **错误描述**: 简短描述问题
2. **复现步骤**: 如何触发问题
3. **环境信息**:
   ```bash
   python --version
   pip list
   ```
4. **错误日志**: 完整的错误输出
5. **配置文件**: `config.yaml` (隐藏敏感信息)

---

## 📚 相关文档

- [配置文件详解](configuration.md)
- [扩展新闻源教程](extending-sources.md)
- [GitHub Actions 配置](../deployment/github-actions.md)
- [开发贡献指南](../../CONTRIBUTING.md)

---

**Last Updated**: 2026-01-21
