# Daily Report Site

📰 AI 新闻日报自动生成器 - 本地 + GitHub 双模式

---

## 🚀 本地运行

```powershell
# 标准模式（需 ModelScope API Key）
.\run_daily.ps1

# 离线模式（无需 API）
.\run_daily.ps1 -Offline

# 跳过 Git 提交
.\run_daily.ps1 -NoCommit
```

**预览**: `cd docs && python -m http.server 8000`

---

## ⚙️ GitHub 自动化配置

### 1. 配置 Secret
`Settings → Secrets → Actions → New secret`

| Name | Value |
|------|-------|
| `MODELSCOPE_API_KEY` | 从 `.env` 获取 |

### 2. 启用权限
`Settings → Actions → General → Workflow permissions`
- ✅ Read and write permissions
- ✅ Allow Actions to create/approve PRs

### 3. 启用 Pages
`Settings → Pages → Source` 选择 `GitHub Actions`

**自动运行**: 每天 09:00 (北京时间)

---

## 📁 核心文件

```
├── run_daily.ps1      # 本地运行脚本
├── main.py            # 主入口
├── config.yaml        # 配置文件
├── content/           # Markdown 源
├── docs/              # HTML 输出
└── .github/workflows/ # 自动化
```

---

## 🛠️ 命令参考

```bash
# 安装依赖
pip install -r requirements.txt

# 完整流程
python main.py run

# 分步执行
python main.py fetch      # 抓取
python main.py summarize  # 总结
python main.py build      # 构建
```

---

## ⚙️ 配置

**环境变量** (`.env`):
```bash
MODELSCOPE_API_KEY=sk-xxx...
MODELSCOPE_MODEL=ZhipuAI/GLM-4.7
```

**新闻源** (`config.yaml`):
```yaml
sources:
  aibase: true
  techcrunch: true
  theverge: true
```

---

## 🔧 故障排查

| 问题 | 方案 |
|------|------|
| Actions 失败 | 检查 `MODELSCOPE_API_KEY` Secret |
| API 额度不足 | 用 `-Offline` 模式 |
| 权限错误 | 启用 Actions 写入权限 |

---

## 📝 License

MIT

