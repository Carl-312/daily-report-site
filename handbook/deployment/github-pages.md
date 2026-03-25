# GitHub Pages 部署指南

项目默认通过 GitHub Actions 部署 GitHub Pages，不再使用 `main/docs` 目录模式。

## 当前部署方式

- 构建输出目录：`dist/`
- 部署上传方式：`actions/upload-pages-artifact`
- Pages 来源：`GitHub Actions`

这意味着：

- `dist/` 只作为临时构建产物存在
- `dist/` 不进入 Git
- `main` 分支不再承担静态站点长期存储职责

## 配置步骤

### 1. 启用 Pages

进入 `Settings -> Pages`，将 `Source` 设为 `GitHub Actions`。

### 2. 运行部署 workflow

执行 `Daily Report Deploy` 后，workflow 会：

1. 生成日报
2. 构建 `dist/`
3. 在 `main` 分支上上传 `dist/` 为 Pages artifact
4. 在 `main` 分支上由 `deploy-pages` 发布

### 3. 验证结果

部署成功后访问：

- 用户仓库：`https://<username>.github.io/daily-report-site/`
- 组织仓库：`https://<org>.github.io/daily-report-site/`

## 站点内容边界

当前站点只依赖仓库内保留的 `content/` 构建，因此默认展示最近 7 天窗口内的内容。

更久的历史数据会进入 GitHub Release assets，而不是继续保留在 `main` 或站点目录中。

如果未来需要“站点可浏览全历史”，建议额外引入归档索引或对象存储读取逻辑。

如果你在非 `main` 分支上手动触发 workflow，它可以用于验证构建是否成功，但不会真的发布 Pages。

## 常见误区

- 不要再把 `docs/` 当成 Pages 根目录
- 不要把 `dist/` 提交到 Git
- 不要把手写文档放回 `dist/` 或其他构建目录

## 相关文档

- GitHub Actions：[`github-actions.md`](github-actions.md)
- 本地运行：[`local.md`](local.md)
