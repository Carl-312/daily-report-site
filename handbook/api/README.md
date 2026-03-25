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

## 数据流

完整流程如下：

1. `fetch_all()` 抓取新闻
2. `dedupe()` 做去重
3. `save_json()` 写入 `data/YYYY-MM-DD.json`
4. `summarize()` 或 `offline_summary()` 生成 Markdown
5. `save_markdown()` 写入 `content/YYYY-MM-DD.md`
6. `build_site()` 将 `content/` 渲染到 `dist/`

## 关键函数

### `summarizer.py`

- `summarize(articles, stream=False) -> str`
- `offline_summary(articles) -> str`
- `test_connection() -> bool`

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

## 配置对象

`config.py` 的 `Settings` 负责统一读取：

- `.env`
- `config.yaml`

关键路径字段：

- `data_dir`
- `content_dir`
- `site_dir`

## 相关文档

- 架构说明：[`../../ARCHITECTURE.md`](../../ARCHITECTURE.md)
- 配置说明：[`../guides/configuration.md`](../guides/configuration.md)
