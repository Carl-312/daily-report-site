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

### 摘要来源映射、条数或字数超限

当前契约先按 `max_summary_items=10` 生成确定性短名单，每日目标和上限均为 10 条；证据合格候选不足时允许更少，没有候选时应显示“暂无新闻”。模型必须按原顺序对每个短名单 `article_id` 输出一次，不能遗漏、重复、新增来源或编造事实。ID 与 URL 只保存在内部 `SummaryResult`/JSON 溯源数据，读者页面不会显示它们。

排查当天 `data/YYYY-MM-DD.json`：

- 看 `summary.items` 数量是否在证据充足时达到 10 条、始终不超过 `max_summary_items=10`，并与 `candidate_article_ids` 数量一致。
- 看 `summary.items[*].article_id` 是否与 `candidate_article_ids` 完全一致；重复、遗漏和改序都会阻断发布。
- 看 `summary.selection_policy` 是否为 `source_balanced_v2`，并检查 `selection_diagnostics`：
  - `story_clusters` / `duplicate_story_rejected_count` 解释哪些跨源事件被合并；
  - `source_counts`、`primary_entity_counts`、`mentioned_entity_counts`、`model_family_counts` 展示集中度；
  - `topic_counts`、`region_counts` 展示话题和中美主体覆盖；
  - `quota_relaxations` 非空表示候选不足时实际放宽的约束及对应 `article_id`。
- `selection_diagnostics` 会在发布前从完整候选快照重算；手工修改诊断、目录或候选顺序而不重跑摘要会被阻断。
- 看每条 `summary` 去除空白后的可见字符数是否优先落在 35–60；30–80 是本地硬范围；空泛来源措辞和内部趋势信号也会被代码拒绝，不能只依赖提示词。
- 看每条 `summary` 是否是一条可独立理解的完整句（以 `。`、`！` 或 `？` 结尾），且不含 `：`、`...` 或 `…`；读者 Markdown 应直接显示该句，不能再渲染成“标题：摘要”。
- `--summary-mode ai` 只接受 `policy: required_ai` 的模型结果。主端点“无可用 provider”或备用端点返回空 `choices` 都是 AI 验证失败；不得把随后生成的 `offline` / `reviewed` 结果改标为 AI。
- 人工复核回放应同时保留 `summary_mode: reviewed`、非 AI policy、`editorial_review` provider 和 `publish: false`，并在报告中明确它只验证本地契约与渲染链路。
- 如果出现 `SummaryQualityError`、未知 ID、URL 不匹配或 `publication blocked`，应保留上一版产物，修复输入或摘要结果后再重跑。
- 输入 URL 带跟踪参数、片段，或不同来源标题只是明显改写时，`dedupe()` 会合并并保留高优先级候选；这是预期的候选减少，不是抓取丢失。
- 泛科技公司新闻只有在同时出现 AI、模型、芯片、算力、机器人或自动驾驶上下文时才达到选题门槛；仅有公司名或宽泛的 “generative” 不入选是预期行为。

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

- `run_mode` 必须选择 `formal_gray`，该预设会同时开启 Tavily、Trending 和灰度 Pages 硬门禁。
- `run_mode=rebuild_preview` 只重建站点，不运行抓取和 Tavily。
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

- 本地运行：[`local.md`](local.md)
- GitHub Actions：[`github-actions.md`](github-actions.md)
- Tavily 接入总览：[`tavily.md`](tavily.md)
