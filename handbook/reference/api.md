# API 参考文档

本文档描述项目的主要模块接口和调用关系。

## CLI 入口

`main.py` 提供以下命令：

```bash
python main.py run
python main.py fetch
python main.py summarize
python main.py build
python main.py test
```

`run` 与 `fetch` 还支持 `--agihunt {auto,on,off}`。默认 `auto` 跟随
`config.yaml`（当前关闭）；`on` 仅用于已授权的 shadow，不会自动改变持久配置。

## 数据流

完整流程如下：

1. `fetch_batch()` 串行抓取新闻并记录每个 source outcome
2. `dedupe()` 规范化 URL、去除跟踪参数并拦截明显故事重复
3. `enrich_articles_with_tavily()` 可选验证/补充候选
4. `save_json()` 将候选和运行诊断写入 staging；摘要结果包含 `SummaryResult`
5. `summarize_result()` 或 `offline_summary_result()` 生成结构化摘要，`render_summary_markdown()` 本地确定性渲染
6. `save_markdown()` 写入 staging，`build_site()` 将内容构建到 staging `dist/`，通过发布门禁后再 promotion

## 关键函数

### `summarizer.py`

- `summarize(articles, stream=False) -> str`
- `summarize_result(articles, stream=False) -> SummaryResult`
- `offline_summary(articles) -> str`
- `offline_summary_result(articles) -> SummaryResult`
- `validate_summary_quality(content, expected_items=10, expected_article_ids=None) -> None`
- `test_connection() -> bool`

### `utils/summary_contracts.py`

- `article_id_for_index(index) -> str`
- `validate_summary_result(result, articles) -> None`
- `render_summary_markdown(result) -> str`

摘要条目必须使用输入候选中已知的 `article_id`，数量不能超过独立日报上限，且每条源 URL 必须与引用的输入候选一致。同一个 `article_id` 可以出现在多个条目中，以支持聚合链接拆分；这些规则由本地代码校验，不由提示词单独保证。

### `utils/dedupe.py`

- `canonical_url(link) -> str`
- `dedupe(articles) -> list[Article | dict]`

URL 跟踪参数、片段和明显的跨来源标题改写会被归并，优先级更高的候选保留。

### `sources/agihunt.py`

- `AgihuntClient.fetch_report(day) -> AgihuntReport`
- `AgihuntClient.fetch_channel_items(channel, day) -> list[dict]`
- `AgihuntSource.fetch(max_articles, reference_dt, deadline_at) -> list[Article]`

该 client 只调用官方 Agent API，使用 `Authorization`、skill version header、串行
锁、十分钟本地缓存和一次受控重试。日报只保留为覆盖诊断；`Article.link` 必须是
频道条目的原帖 URL，`Article.provenance` 保存频道、排名、热度、作者、API 日期和
日报链接。

### `utils/storage.py`

- `today_ymd() -> str`
- `today_cn() -> str`
- `save_json(dir_path, date_str, data) -> Path`
- `load_json(dir_path, date_str) -> dict | None`
- `save_markdown(dir_path, date_str, content) -> Path`

### `build.py`

- `build_site(source_dir=None, output_dir=None, assets_dir=None) -> list[dict[str, str]]`
- `build_article(md_path, base_path="") -> dict[str, str]`
- `parse_frontmatter(content) -> tuple[dict[str, str], str]`

构建输出目录是 `dist/`，不是 `docs/`。

### `scripts/manage_retention.py`

- `bundle_old_entries(...) -> list[Path]`
- `prune_old_entries(...) -> list[Path]`

该脚本用于：

- 将超过 7 天的 `data/` / `content/` 打包成 Release assets
- 在上传成功后清理仓库内超期热数据

### `scripts/agihunt_gray_health.py`

在 Actions 的 `enable_agihunt=true` preview 后验证 run manifest、请求预算、候选
provenance、数据/摘要 URL 映射、Markdown 归因和 staged publication。结果写入
本地默认 `.runs/agihunt-gray-health.json`；workflow 会将去敏结果写到根目录
`agihunt-gray-health.json`，以便被 preview artifact 收录。

## 配置对象

`config.py` 的 `Settings` 负责统一读取：

- `.env`
- `config.yaml`

关键路径字段：

- `data_dir`
- `content_dir`
- `site_dir`
- `agihunt_api_key`（仅环境变量）
- `agihunt`（非密钥 API 与筛选策略）

## 相关文档

- 架构说明：[`../architecture/system.md`](../architecture/system.md)
- 配置说明：[`../operations/configuration.md`](../operations/configuration.md)
