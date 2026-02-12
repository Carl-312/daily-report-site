# GitHub Actions 自动化配置

配置 GitHub Actions 实现每日自动生成和部署。

---

## 🎯 目标

- ✅ 每天定时抓取新闻并生成日报
- ✅ 自动提交生成的 Markdown 和 HTML 文件
- ✅ 部署到 GitHub Pages

---

## 📦 所需文件

项目已包含以下工作流文件:

```
.github/
└── workflows/
    └── daily-report.yml   # 主工作流
```

---

## ⚙️ 配置步骤

### 1. 配置 Secret

GitHub Actions 需要 API Key 才能调用 ModelScope 服务。

**步骤**:
1. 打开仓库页面
2. 点击 **Settings** → **Secrets and variables** → **Actions**
3. 点击 **New repository secret**
4. 添加以下 Secret:

| Name | Value |
|------|-------|
| `MODELSCOPE_API_KEY` | 从 [ModelScope 控制台](https://modelscope.cn/my/myaccesstoken) 获取的 API Key |

> ⚠️ **重要**: Secret 一旦保存无法查看，请妥善备份

### 2. 启用 Actions 权限

GitHub Actions 需要写入权限才能提交文件。

**步骤**:
1. 打开 **Settings** → **Actions** → **General**
2. 滚动到 **Workflow permissions**
3. 选择 **Read and write permissions**
4. 勾选 **Allow GitHub Actions to create and approve pull requests**
5. 点击 **Save**

**截图参考**:
```
Workflow permissions
○ Read repository contents and packages permissions
● Read and write permissions
☑ Allow GitHub Actions to create and approve pull requests
```

### 3. 验证工作流文件

查看 `.github/workflows/daily-report.yml`:

```yaml
name: Daily Report Generator

on:
  schedule:
    # 每天 01:00 UTC (北京时间 09:00)
    - cron: '0 1 * * *'
  workflow_dispatch:  # 允许手动触发

permissions:
  contents: write
  pages: write
  id-token: write

jobs:
  generate-and-deploy:
    runs-on: ubuntu-latest
    
    steps:
      - name: Checkout repository
        uses: actions/checkout@v4
      
      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          cache: 'pip'
      
      - name: Install dependencies
        run: pip install -r requirements.txt
      
      - name: Run daily report
        env:
          MODELSCOPE_API_KEY: ${{ secrets.MODELSCOPE_API_KEY }}
          MODELSCOPE_MODEL: moonshotai/Kimi-K2.5
        run: python main.py run
      
      - name: Commit changes
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add data/ content/ docs/
          git diff --staged --quiet || git commit -m "Daily report: $(date +'%Y-%m-%d')"
          git push
      
      - name: Upload Pages artifact
        uses: actions/upload-pages-artifact@v3
        with:
          path: docs/
      
      - name: Deploy to GitHub Pages
        uses: actions/deploy-pages@v4
```

---

## 🔄 工作流详解

### 触发条件

```yaml
on:
  schedule:
    - cron: '0 1 * * *'  # 每天 01:00 UTC
  workflow_dispatch:      # 手动触发
```

**时区转换**:
- `0 1 * * *` = UTC 01:00 = 北京时间 09:00
- `0 17 * * *` = UTC 17:00 = 北京时间 01:00 (次日)

### 环境准备

```yaml
- name: Setup Python
  uses: actions/setup-python@v5
  with:
    python-version: '3.11'
    cache: 'pip'  # 启用依赖缓存
```

**缓存机制**: 
- 首次运行: 安装所有依赖 (~30s)
- 后续运行: 使用缓存 (~5s)

### 核心步骤

```yaml
- name: Run daily report
  env:
    MODELSCOPE_API_KEY: ${{ secrets.MODELSCOPE_API_KEY }}
  run: python main.py run
```

**环境变量注入**: Secret 通过 `env` 传递，不会在日志中暴露

### 提交变更

```yaml
- name: Commit changes
  run: |
    git config user.name "github-actions[bot]"
    git config user.email "github-actions[bot]@users.noreply.github.com"
    git add data/ content/ docs/
    git diff --staged --quiet || git commit -m "Daily report: 2026-01-21"
    git push
```

**智能提交**: 
- `git diff --staged --quiet || git commit`: 仅在有变更时提交
- 避免空提交导致工作流失败

---

## 🚀 测试工作流

### 手动触发

1. 打开 **Actions** 标签页
2. 选择 **Daily Report Generator** 工作流
3. 点击 **Run workflow**
4. 选择分支 (通常是 `main`)
5. 点击绿色的 **Run workflow** 按钮

### 查看运行日志

1. 点击正在运行或已完成的工作流
2. 查看各个步骤的日志:
   - **Install dependencies**: 依赖安装
   - **Run daily report**: 主逻辑输出
   - **Commit changes**: Git 操作
   - **Deploy to GitHub Pages**: 部署状态

**示例日志**:
```
Run python main.py run
🚀 Daily Report - 2026-01-21
==================================================

📡 Fetching news...
   AIBase: 8 articles
   TechCrunch: 5 articles
   The Verge: 6 articles

🔄 Deduplicating 19 articles...
   Remaining: 14 unique articles

💾 Saved JSON: data/2026-01-21.json

🤖 Generating summary...
   Streaming from ModelScope API...
   ✅ Received 1234 chars

📝 Saved Markdown: content/2026-01-21.md

🏗️ Building HTML site...
   Processed 10 articles
   Generated index.html
   Generated archive.html

==================================================
✅ Done!
```

---

## 🐛 故障排查

### ❌ 错误: "API Key not found"

**原因**: Secret 未配置或名称错误

**解决**:
1. 检查 Secret 名称是否为 `MODELSCOPE_API_KEY`
2. 验证 Secret 值是否正确
3. 重新运行工作流

### ❌ 错误: "Permission denied (push)"

**原因**: Actions 写入权限未启用

**解决**:
1. 前往 **Settings** → **Actions** → **General**
2. 启用 **Read and write permissions**

### ❌ 错误: "No changes to commit"

**原因**: 当天已生成日报，没有新变更

**不是错误**: 
- 工作流设计为幂等 (idempotent)
- 多次执行相同日期不会重复提交

### ❌ 工作流未自动运行

**可能原因**:
1. Cron 表达式错误
2. 仓库超过 60 天未活跃 (GitHub 会暂停工作流)
3. Actions 被禁用

**解决**:
```yaml
# 检查 Cron 表达式 (使用 https://crontab.guru/)
- cron: '0 1 * * *'  # 正确
- cron: '0 1 * * 1-5'  # 仅工作日
```

### 🔍 调试技巧

**启用调试日志**:
```yaml
- name: Run daily report
  env:
    MODELSCOPE_API_KEY: ${{ secrets.MODELSCOPE_API_KEY }}
    ACTIONS_RUNNER_DEBUG: true  # 启用调试
  run: python main.py run
```

**条件跳过步骤**:
```yaml
- name: Commit changes
  if: github.event_name == 'schedule'  # 仅 Cron 触发时提交
  run: |
    git add .
    git commit -m "Daily report"
    git push
```

---

## ⏱️ 自定义运行时间

**修改 Cron 表达式**:

```yaml
on:
  schedule:
    # 每天 UTC 00:00 (北京时间 08:00)
    - cron: '0 0 * * *'
    
    # 每天 UTC 12:00 (北京时间 20:00)
    - cron: '0 12 * * *'
    
    # 仅工作日 UTC 01:00
    - cron: '0 1 * * 1-5'
    
    # 每 6 小时一次
    - cron: '0 */6 * * *'
```

**在线工具**: [Crontab Guru](https://crontab.guru/)

---

## 📊 监控和通知

### GitHub Actions 邮件通知

默认情况下，工作流失败时 GitHub 会发送邮件通知。

**自定义通知**:
- **Settings** → **Notifications** → **Actions**
- 选择通知频率:
  - Only failures
  - All workflow runs
  - None

### Slack/Discord 集成 (可选)

```yaml
- name: Notify on failure
  if: failure()
  uses: 8398a7/action-slack@v3
  with:
    status: ${{ job.status }}
    webhook_url: ${{ secrets.SLACK_WEBHOOK }}
```

---

## 🔐 安全最佳实践

### ✅ DO

- ✅ 使用 Repository Secrets 存储 API Key
- ✅ 定期轮换 API Key (每 90 天)
- ✅ 限制 Actions 权限为最小必需

### ❌ DON'T

- ❌ 在工作流文件中硬编码 API Key
- ❌ 使用 `echo ${{ secrets.MODELSCOPE_API_KEY }}`
- ❌ 启用不必要的权限 (如 `contents: write` 用于只读任务)

---

## 📈 优化建议

### 1. 减少运行时间

**启用缓存**:
```yaml
- name: Cache pip dependencies
  uses: actions/cache@v3
  with:
    path: ~/.cache/pip
    key: ${{ runner.os }}-pip-${{ hashFiles('requirements.txt') }}
```

### 2. 并发控制

**防止重复运行**:
```yaml
concurrency:
  group: daily-report
  cancel-in-progress: true  # 取消旧运行
```

### 3. 条件部署

**仅在有变更时部署**:
```yaml
- name: Deploy to GitHub Pages
  if: steps.commit.outputs.changes == 'true'
  uses: actions/deploy-pages@v4
```

---

## 🔗 相关资源

- [GitHub Actions 文档](https://docs.github.com/en/actions)
- [Cron 表达式生成器](https://crontab.guru/)
- [ModelScope API 文档](https://modelscope.cn/docs)

---

## 🚀 下一步

- [配置 GitHub Pages 部署](github-pages.md)
- [查看故障排查手册](../guides/troubleshooting.md)

---

**Last Updated**: 2026-01-21
