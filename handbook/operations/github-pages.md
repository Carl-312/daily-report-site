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

在 `main` 上执行生产模式的 `Daily Report Deploy` 后，workflow 会：

1. 生成日报
2. 构建 `dist/`
3. 仅在 publish mode 下，在 `main` 分支上上传选定的 `dist/` 为 Pages artifact
4. 由满足 `main`、`publish=true` 且 Pages 已启用条件的 `deploy` job 发布

非 `main` 分支以及手动非生产模式只上传
`daily-report-preview-<run_id>`，不会发布 Pages。

## 独立正式灰度

正式灰度不占用生产仓库的 Pages 配置。通过门禁的 preview `dist/` 会被推送到
`Carl-312/daily-report-site-gray` 的 `gh-pages` 分支，在
[`https://carl-312.github.io/daily-report-site-gray/`](https://carl-312.github.io/daily-report-site-gray/)
与生产站并行。手动 `run_mode=formal_gray` 与每日定时入口都会固定采用非生产、完整生成、
Tavily on、Trending on、Trending health 与完整 formal-gray health 硬门禁；后者阻止历史
data checkpoint 缺失、跨日重复、摘要映射异常，以及 enrichment 全失败后单一来源退化的产物。
它不调用生产 `deploy-pages` job。
每日 `14:05`（`Asia/Shanghai`）定时入口会自动执行同一套正式灰度门禁并更新该站点；
它不改变既有 `08:36` 生产定时发布或 `main` 上显式的手动 `run_mode=production` 边界。

当前在线灰度对应提交 `0cbaef3`、源运行
[`29818465019`](https://github.com/Carl-312/daily-report-site/actions/runs/29818465019) 和灰度 Pages 运行
[`29818600100`](https://github.com/Carl-312/daily-report-site-gray/actions/runs/29818600100)。
`gray-build.json` 是线上版本的权威追溯入口。

### 3. 验证结果

部署成功后访问：

- 用户仓库：`https://<username>.github.io/daily-report-site/`
- 组织仓库：`https://<org>.github.io/daily-report-site/`

## 站点内容边界

当前站点只依赖仓库内保留的 `content/` 构建，因此默认展示最近 7 天窗口内的内容。

更久的历史数据会进入 GitHub Release assets，而不是继续保留在 `main` 或站点目录中。

如果未来需要“站点可浏览全历史”，建议额外引入归档索引或对象存储读取逻辑。

如果你在非 `main` 分支上手动触发 workflow，它可以用于验证构建是否成功，但不会真的发布 Pages；`main` 上手动 `publish=false` 也遵循同一预览边界。

## 2026-07-10 灰度结果

成功预览 run `29076119648` 使用 `skip_generate=true`、`publish=false`、
`enable_tavily=false`，生成 artifact `daily-report-preview-29076119648`。
artifact 不含 `content/2026-07-10.md`、`data/2026-07-10.json` 或
`dist/2026-07-10.html`；这只证明灰度分支删除和重建结果，不是生产 Pages 发布。
PR #8 仍为 OPEN/Draft，线上 URL 未变。

## 2026-07-13 预览结果

[Preview run `29238871654`](https://github.com/Carl-312/daily-report-site/actions/runs/29238871654)
在灰度分支提交 `adc9bf0` 上以 `publish=false` 完成生成。2 条去重后候选生成 2 条摘要，
`article_id` 来源校验通过，artifact 成功上传；`deploy` job 跳过，生产 Pages 未改变。
这次运行只验证生成和摘要契约，不是生产部署验收。

## 常见误区

- 不要再把 `docs/` 当成 Pages 根目录
- 不要把 `dist/` 提交到 Git
- 不要把手写文档放回 `dist/` 或其他构建目录

## 相关文档

- GitHub Actions：[`github-actions.md`](github-actions.md)
- 本地运行：[`local.md`](local.md)
