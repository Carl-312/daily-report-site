# 故障排查手册

## 推荐排查顺序

1. 检查 `Python 3.12`
2. 检查依赖是否按用途安装
3. 检查 `.env` 与 `config.yaml`
4. 检查 `data/` / `content/` / `dist/` 路径
5. 查看本地命令或 GitHub Actions 日志

## 常见问题

### 依赖缺失

如果报 `ModuleNotFoundError`：

```bash
pip install -r requirements.txt
```

如果缺的是 `ruff`、`pytest` 等开发工具：

```bash
pip install -r requirements-dev.txt
```

### pytest 没通过

先在本地跑：

```bash
pytest
```

如果是和路径、构建输出或保留策略有关的改动，请同步检查：

```bash
python main.py build
python scripts/manage_retention.py bundle --keep-days 7
```

### API Key 不可用

确认 `.env` 中有：

```bash
MODELSCOPE_API_KEY=sk-your-key
```

也可以直接切换离线模式：

```bash
python main.py run --offline
```

### Tavily 没有启用

Tavily 默认关闭。确认 `config.yaml` 中仍是：

```yaml
enrichment.enabled: false
```

本地显式启用需要同时提供 key 和 CLI 开关：

```bash
TAVILY_API_KEY=... python3 main.py fetch --enrichment on
TAVILY_API_KEY=... python3 main.py run --offline --enrichment on
```

安全关闭或回滚到默认抓取路径：

```bash
python3 main.py fetch --enrichment off
python3 main.py run --offline --enrichment off
```

`--enrichment auto` 跟随配置；在默认 `enrichment.enabled: false` 下不会启用 Tavily。

### Tavily 失败或结果为 0

先看当天 `data/YYYY-MM-DD.json` 顶层的 `enrichment` 字段：

- `enabled=false` 或 `skip_reason=disabled`：本次没有启用 Tavily。
- `skip_reason=missing_api_key`：缺少 `TAVILY_API_KEY`，主流程应继续使用去重后的文章。
- `request_outcome=timeout/http_error/connection_error/request_error`：这是请求失败，不应当被解释为新闻验证失败。
- `preserved_error_count` 大于 0：verify 请求失败时保留了原始 deduped articles，符合 fail-open 预期。
- `final_count=0` 且 `input_count=0`：source 没有候选，Tavily 只能尝试受控 refill；这不是 verify 成熟度证明，也不说明可以放弃 source 层。

不要为了单次 `final_count` 不足而放宽 `strict_hours: 24`，也不要临时把 `trusted_domains` 当作热修名单扩张。

### GitHub Actions 手动 Tavily 灰度没有效果

检查 `Daily Report Deploy` 的手动输入：

- `enable_tavily` 必须设为 `true`，否则不会追加 `--enrichment on`。
- `skip_generate=true` 只重建站点，不运行抓取和 Tavily。
- 仓库 secret 需要配置 `TAVILY_API_KEY`；缺失时 workflow 仍应完成，但 JSON 会记录安全降级。
- 非 `main` 分支运行不会回写 `data/` / `content/` 或发布 Pages，只适合看日志。

### 构建输出不对

当前站点输出目录是 `dist/`，不是 `docs/`。

可直接重建：

```bash
python main.py build
python -m http.server 8000 --directory dist
```

### 旧日报被清理了

这是预期行为。部署流程会：

1. 先把超过 7 天的 `data/` / `content/` 打包成 Release assets
2. 再从 `main` 删除超期文件

如果要找历史内容，请到 GitHub Release `daily-report-archive` 下载对应日期的 tar.gz。

### GitHub Pages 没更新

重点检查 `Daily Report Deploy` workflow：

- `Upload Pages artifact`
- `Deploy to GitHub Pages`

同时确认仓库设置里 `Pages -> Source` 是 `GitHub Actions`。

如果这次是从非 `main` 分支手动触发 workflow，那么“没有更新 Pages”是预期行为，因为非主分支只做验证、不做发布。

## 相关文档

- 本地运行：[`../deployment/local.md`](../deployment/local.md)
- GitHub Actions：[`../deployment/github-actions.md`](../deployment/github-actions.md)
- Tavily 接入总览：[`tavily-integration.md`](tavily-integration.md)
