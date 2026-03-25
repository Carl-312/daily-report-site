# 配置文件详解

项目配置主要来自 `config.yaml` 和 `.env`。

## `config.yaml`

当前示例：

```yaml
sources:
  aibase: true
  techcrunch: true
  theverge: true
  syft: false

limits:
  max_articles: 14

summarize:
  prompt_path: prompts/daily.md
  prefer_chinese: true
  compress:
    title_max: 200
    desc_max: 400

output:
  json_dir: data
  md_dir: content
  site_dir: dist
```

## 关键字段

### `sources`

控制启用哪些新闻源：

```yaml
sources:
  aibase: true
  techcrunch: true
  theverge: true
  syft: false
```

### `limits.max_articles`

控制每天进入摘要与构建流程的文章上限。

### `summarize.prompt_path`

指定摘要 Prompt 模板文件。

### `output`

- `json_dir`：日报原始 JSON 输出目录
- `md_dir`：日报 Markdown 输出目录
- `site_dir`：站点构建输出目录，默认 `dist`

## 路径约定

默认路径：

```text
data/     JSON 热数据
content/  Markdown 热数据
dist/     HTML 构建输出
```

注意：

- `dist/` 是构建产物，不进入 Git
- `data/` / `content/` 在部署流程中只保留最近 7 天
- 修改输出路径时，需要同步更新代码和文档

## `.env`

环境变量优先用于密钥和运行时覆盖项。

示例：

```bash
MODELSCOPE_API_KEY=sk-your-key
MODELSCOPE_MODEL=moonshotai/Kimi-K2.5
SYFT_WEB_APP_URL=https://syft.example.com
SYFT_SECRET_KEY=your-syft-secret-key
```

未配置 `MODELSCOPE_API_KEY` 时，可使用：

```bash
python main.py run --offline
```

## 相关文档

- 本地运行：[`../deployment/local.md`](../deployment/local.md)
- 扩展新闻源：[`extending-sources.md`](extending-sources.md)
