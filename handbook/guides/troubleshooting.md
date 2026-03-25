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
