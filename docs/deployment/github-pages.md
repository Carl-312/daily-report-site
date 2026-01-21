# GitHub Pages 部署指南

将生成的静态站点部署到 GitHub Pages。

---

## 🎯 部署方式

GitHub Pages 支持三种部署方式:

| 方式 | 适用场景 | 推荐度 |
|------|---------|--------|
| **GitHub Actions** | 自动化 CI/CD | ⭐⭐⭐⭐⭐ (推荐) |
| `gh-pages` 分支 | 传统项目 | ⭐⭐⭐ |
| `docs/` 目录 (main 分支) | 简单项目 | ⭐⭐ |

本项目默认使用 **GitHub Actions** 方式。

---

## 🚀 快速配置 (GitHub Actions)

### 1. 启用 GitHub Pages

**步骤**:
1. 打开仓库 **Settings** → **Pages**
2. 在 **Source** 下拉菜单中选择 **GitHub Actions**
3. 点击 **Save** (如果有)

**截图参考**:
```
Build and deployment
Source: [GitHub Actions ▼]

Your GitHub Pages site is being built from the gh-actions branch.
```

### 2. 验证部署

运行 GitHub Actions 工作流后:

1. 前往 **Actions** 标签页
2. 查看 **Deploy to GitHub Pages** 步骤
3. 等待部署完成 (通常 1-2 分钟)
4. 访问: `https://your-username.github.io/daily-report-site/`

**示例 URL**:
- 用户仓库: `https://username.github.io/daily-report-site/`
- 组织仓库: `https://org-name.github.io/daily-report-site/`

### 3. 配置自定义域名 (可选)

**前提**: 拥有自己的域名 (如 `example.com`)

**步骤**:
1. **DNS 配置** (在域名提供商后台):
   
   **A 记录** (Apex 域名 `example.com`):
   ```
   Type: A
   Name: @
   Value: 185.199.108.153
          185.199.109.153
          185.199.110.153
          185.199.111.153
   ```
   
   **CNAME 记录** (子域名 `www.example.com`):
   ```
   Type: CNAME
   Name: www
   Value: your-username.github.io
   ```

2. **GitHub 配置**:
   - 前往 **Settings** → **Pages**
   - 在 **Custom domain** 输入 `example.com`
   - 勾选 **Enforce HTTPS**
   - 点击 **Save**

3. **验证**:
   - GitHub 会自动验证 DNS
   - 等待 24-48 小时 DNS 传播
   - 访问 `https://example.com`

---

## 📁 替代方式: 使用 `docs/` 目录

如果不使用 GitHub Actions，可以直接从 `main` 分支的 `docs/` 目录部署。

### 配置步骤

1. **Settings** → **Pages** → **Source**
2. 选择 **Deploy from a branch**
3. Branch: `main`
4. Folder: `/docs`
5. 点击 **Save**

**优点**:
- 简单直接，无需工作流
- 适合手动生成站点

**缺点**:
- 需要手动运行 `python main.py run` 并提交
- 无法自动化

---

## 🔧 工作流集成

### 完整工作流 (已配置)

`.github/workflows/daily-report.yml`:

```yaml
jobs:
  generate-and-deploy:
    runs-on: ubuntu-latest
    
    steps:
      # ... (前面的步骤)
      
      - name: Upload Pages artifact
        uses: actions/upload-pages-artifact@v3
        with:
          path: docs/  # 指定站点目录
      
      - name: Deploy to GitHub Pages
        id: deployment
        uses: actions/deploy-pages@v4
```

**关键点**:
- `upload-pages-artifact`: 打包站点目录
- `deploy-pages`: 部署到 Pages

### 部署权限

确保工作流有 Pages 权限:

```yaml
permissions:
  contents: write  # 用于提交文件
  pages: write     # 用于部署 Pages
  id-token: write  # 用于 OIDC 认证
```

---

## 🌐 站点结构

部署后的站点结构:

```
https://your-username.github.io/daily-report-site/
├── index.html           # 首页
├── archive.html         # 归档页
├── 2026-01-21.html      # 每日文章
├── 2026-01-20.html
├── style.css            # 样式表
└── assets/              # 静态资源 (如果有)
```

**导航流程**:
1. 用户访问 `index.html` (首页)
2. 查看最新文章摘要
3. 点击标题进入 `YYYY-MM-DD.html` (详情页)
4. 通过 `archive.html` 查看历史文章

---

## 🎨 自定义主题

### 修改样式

编辑 `assets/style.css`:

```css
/* 自定义主色调 */
:root {
  --primary-color: #4CAF50;  /* 绿色 */
  --accent-color: #FF5722;   /* 橙色 */
  --bg-color: #f5f5f5;       /* 浅灰背景 */
}

/* 自定义导航栏 */
.navbar {
  background: linear-gradient(135deg, var(--primary-color), var(--accent-color));
}
```

**生效方式**:
1. 本地修改 `assets/style.css`
2. 提交到 Git
3. 等待 Actions 重新部署

### 添加 Logo

在 `build.py` 中修改模板:

```python
ARTICLE_TEMPLATE = """
<nav class="navbar">
  <div class="container">
    <a href="index.html" class="logo">
      <img src="assets/logo.png" alt="Logo" width="32">
      📰 Daily Report
    </a>
    ...
  </div>
</nav>
"""
```

---

## 🔍 SEO 优化

### 1. 添加 Meta 标签

在 `build.py` 的模板中:

```html
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  
  <!-- SEO Meta -->
  <meta name="description" content="每日 AI 科技新闻摘要，汇聚 AIBase、TechCrunch 等优质资讯源">
  <meta name="keywords" content="AI新闻,科技资讯,人工智能,TechCrunch,每日摘要">
  <meta name="author" content="Your Name">
  
  <!-- Open Graph (社交分享) -->
  <meta property="og:title" content="Daily Report - AI 新闻日报">
  <meta property="og:description" content="每日 AI 科技新闻摘要">
  <meta property="og:type" content="website">
  <meta property="og:url" content="https://your-username.github.io/daily-report-site/">
  <meta property="og:image" content="https://your-username.github.io/daily-report-site/assets/og-image.png">
  
  <title>Daily Report - AI 新闻日报</title>
</head>
```

### 2. 添加 Sitemap

创建 `docs/sitemap.xml`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>https://your-username.github.io/daily-report-site/</loc>
    <changefreq>daily</changefreq>
    <priority>1.0</priority>
  </url>
  <url>
    <loc>https://your-username.github.io/daily-report-site/archive.html</loc>
    <changefreq>daily</changefreq>
    <priority>0.8</priority>
  </url>
  <!-- 动态生成的文章 URL -->
</urlset>
```

### 3. 添加 robots.txt

创建 `docs/robots.txt`:

```
User-agent: *
Allow: /

Sitemap: https://your-username.github.io/daily-report-site/sitemap.xml
```

---

## 📊 Analytics 集成

### Google Analytics

在 `build.py` 模板中添加:

```html
<head>
  <!-- ... -->
  
  <!-- Google Analytics -->
  <script async src="https://www.googletagmanager.com/gtag/js?id=G-XXXXXXXXXX"></script>
  <script>
    window.dataLayer = window.dataLayer || [];
    function gtag(){dataLayer.push(arguments);}
    gtag('js', new Date());
    gtag('config', 'G-XXXXXXXXXX');
  </script>
</head>
```

**获取 Tracking ID**:
1. 访问 [Google Analytics](https://analytics.google.com/)
2. 创建新属性
3. 复制 `G-XXXXXXXXXX` ID

---

## 🐛 常见问题

### ❌ 404 错误: "There isn't a GitHub Pages site here"

**原因**:
1. Pages 未启用
2. 部署未完成

**解决**:
1. 检查 **Settings** → **Pages** → Source 是否选择 **GitHub Actions**
2. 查看 Actions 日志，确认部署成功
3. 等待 5-10 分钟后重试

### ❌ CSS 样式未加载

**原因**: 相对路径错误

**解决**:
```html
<!-- 错误 -->
<link rel="stylesheet" href="/style.css">

<!-- 正确 (GitHub Pages 子目录) -->
<link rel="stylesheet" href="style.css">
```

### ❌ 自定义域名 HTTPS 错误

**原因**: DNS 未正确配置

**解决**:
1. 使用 `dig example.com` 验证 A 记录
2. 使用 `dig www.example.com` 验证 CNAME
3. 等待 DNS 传播 (24-48 小时)
4. 勾选 **Settings** → **Pages** → **Enforce HTTPS**

### 🔍 调试技巧

**查看部署日志**:
1. **Actions** → 选择运行
2. 展开 **Deploy to GitHub Pages** 步骤
3. 查看错误信息

**本地预览**:
```bash
cd docs
python -m http.server 8000
# 访问 http://localhost:8000
```

---

## 📈 性能优化

### 1. 启用 CDN

GitHub Pages 默认使用 Fastly CDN，无需额外配置。

### 2. 压缩资源

**Minify CSS**:
```bash
# 使用 cssnano
npx cssnano style.css style.min.css
```

**在 build.py 中引用**:
```html
<link rel="stylesheet" href="style.min.css">
```

### 3. 图片优化

```bash
# 使用 ImageOptim 或在线工具压缩图片
# 推荐格式: WebP
```

---

## 🔐 安全最佳实践

### HTTPS 强制启用

**Settings** → **Pages** → **Enforce HTTPS** ✅

### Content Security Policy (可选)

在 `<head>` 中添加:

```html
<meta http-equiv="Content-Security-Policy" content="
  default-src 'self';
  script-src 'self' https://www.googletagmanager.com;
  style-src 'self' 'unsafe-inline';
  img-src 'self' data: https:;
">
```

---

## 🔗 相关资源

- [GitHub Pages 官方文档](https://docs.github.com/en/pages)
- [自定义域名配置](https://docs.github.com/en/pages/configuring-a-custom-domain-for-your-github-pages-site)
- [GitHub Actions 部署](https://github.com/actions/deploy-pages)

---

## 🚀 下一步

- [查看完整 API 文档](../api/README.md)
- [扩展新闻源教程](../guides/extending-sources.md)

---

**Last Updated**: 2026-01-21
