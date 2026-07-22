# GitHub Actions 自动化配置

当前仓库将质量检查与部署拆成两个独立 workflow。

## 工作流概览

```text
.github/workflows/
├── ci.yml
├── deploy.yml
└── modelscope-smoke.yml
```

## `CI`

用途：只负责质量检查，不混入部署逻辑。

- 触发：`push`、`pull_request`
- Python：`3.12`
- 安装：`pip install -r requirements-dev.txt`
- 执行：
  - `ruff check .`
  - `ruff format --check .`
  - `pytest`

建议将其设为分支保护必过项。

## `ModelScope API Smoke`

用途：手动执行与本地相同的最小 Chat Completions 请求，并要求响应包含非空
`choices` 和非空正文。日志只记录 endpoint、模型名、数量、长度与失败分类，不打印密钥
或模型正文。

- 触发：`workflow_dispatch`
- Secret：`MODELSCOPE_API_KEY`
- 命令：`python scripts/modelscope_smoke.py`
- 失败分类：网络/代理、鉴权、配额、模型或 provider 不可用、非法 JSON、空
  `choices`、空正文

## `Daily Report Deploy`

用途：生成日报、归档历史产物、清理热数据并部署 Pages。

- 触发：`workflow_dispatch`、生产定时任务、每日正式灰度定时任务
- 手动输入：只保留一个必选 `run_mode` 下拉框；`preview`、`formal_gray`、`agihunt_shadow`、`rebuild_preview`、`production` 分别映射到经过验证的固定参数组合，不再允许多个布尔开关拼出无效或危险状态
- 定时：生产任务保留 `36 0 * * *`（UTC，对应上海时间 `08:36`）；正式灰度使用 `5 14 * * *` 和 `timezone: Asia/Shanghai`，每天上海时间 `14:05` 触发，页面在生成和健康检查通过后更新
- 说明：14:05 定时事件避开整点高负载，只发布独立灰度 Pages，不提交生成内容、不归档、不触发生产 Pages；GitHub Actions schedule 仍可能延迟启动
- Python：`3.12`
- 安装：`pip install -r requirements.txt`
- 关键步骤：
  1. 运行 `python main.py run` 或 `python main.py run --offline`
  2. `run_mode=rebuild_preview` 时改为运行 `python main.py build`
  3. 摘要阶段必须满足独立新闻条数上限与来源 `article_id` 契约；失败时不生成越界或无输入映射的日报，同一来源可支撑多条独立新闻
  4. 非 `main` 分支、手动非生产模式以及每日定时灰度，上传 `daily-report-preview-<run_id>`，不回写、不归档、不发布生产 Pages
  5. 仅当 `main` 且为 `08:36` 生产定时任务或手动 `run_mode=production` 时，执行归档、清理并提交保留后的 `data/` / `content/`
  6. 仅在上述生产模式且 Pages 已启用时，使用 `actions/upload-pages-artifact@v3` 和独立 `deploy` job 发布
  7. 每日定时任务自动采用正式灰度参数；手动 `run_mode=formal_gray` 使用同一预设。两种入口都以 Trending health 为硬门禁，通过后才将同一份 preview artifact 的 `dist/` 推送到独立灰度 Pages 仓库

## 必要配置

### Secret

如果要启用 AI 摘要，请配置：

| Name | Value |
| --- | --- |
| `MODELSCOPE_API_KEY` | ModelScope API Key |
| `SILICONFLOW_API_KEY` | SiliconFlow API Key（可选，用作 LLM 备用供应商） |
| `AGIHUNT_API_KEY` | AGIHunt Agent API Key（只在 `run_mode=agihunt_shadow` 时注入） |
| `GRAY_PAGES_DEPLOY_KEY` | 只允许写入 `daily-report-site-gray` 的 SSH deploy key，用于正式灰度 Pages |

两个 secret 都未配置时，部署 workflow 会自动退回离线模式。

`MODELSCOPE_SECONDARY_MODEL` 是可选的非密钥配置，默认留空；只有经过真实 API 验证的
模型才应显式设置。已知会返回协议异常或空 `choices` 的模型不得放入默认回退链。

官方 Agent API 的 `agihunt` source 默认关闭。手动选择 `run_mode=agihunt_shadow` 会传入
`--agihunt on`；如果 `AGIHUNT_API_KEY` 缺失，workflow 会立即失败而不是将
配置错误伪装为空来源。该模式不会改变定时生产任务的默认来源集合。

### 2026-07-14 AGIHunt shadow 状态

`AGIHUNT_API_KEY` 已配置为 Actions Secret 并成功用于非发布 shadow。当时的第 1 天运行
使用 `enable_agihunt=true`、`enable_tavily=false`、`publish=false`，通过生成与 health
gate；preview artifact 根目录的 `agihunt-gray-health.json` 记录 `healthy: true`、
source `ok`、13 个接受候选、5 次物理请求和 `publication_status: published`。该
`published` 仅表示 staged publication 成功；本次 run 没有提交内容、部署 Pages 或运行
发布 job。

此结果是 7 天观察的第 1 天。历史运行中，ModelScope endpoint/token 不支持 Kimi K2.7
Code provider，摘要安全回退到 SiliconFlow。随后对 `Tencent-Hunyuan/Hy3` 完成一次
`publish=false` GitHub 灰度，成功完成 health gate，仍为 source `ok`、13 个接受候选、
5 次物理请求，且没有发布或回写。
但摘要 provenance 记录当时的主 ModelScope 与 `Tencent-Hunyuan/Hy3` 都因空摘要触发
`SummaryQualityError`，最终使用 SiliconFlow `Pro/moonshotai/Kimi-K2.6`。因此该模型
尝试不计为可用验证，也不新增 7 天 shadow 的通过日。Hy3 现已从默认回退链移除；这不
改变 AGIHunt 的独立灰度门槛。
上述早期 shadow 的 GitHub Actions 运行记录已于 2026-07-21 按灰度清理删除。

如果要手动灰度验证 Tavily enrichment，可额外配置：

| Name | Value |
| --- | --- |
| `TAVILY_API_KEY` | Tavily Search API Key |

该 secret 注入生成任务；每日定时灰度与手动 `run_mode=formal_gray` 强制使用
`--enrichment on`，其他手动模式显式关闭。未配置时，开启 Tavily 的运行仍会完成，并在
页尾输出稳定诊断码。不要把真实 secret 写进文档、测试、fixture 或示例提交。

### Workflow 权限

进入 `Settings -> Actions -> General`，将 `Workflow permissions` 设为：

- `Read and write permissions`

因为部署 workflow 需要：

- 推送清理后的 `data/` / `content/`
- 创建或更新 GitHub Release assets
- 部署 GitHub Pages

### GitHub Pages

进入 `Settings -> Pages`，`Source` 选择 `GitHub Actions`。

当前仓库的生产 Pages 仍为 `https://carl-312.github.io/daily-report-site/`。GitHub Pages
每个仓库只能有一个站点，因此正式灰度发布到独立公开仓库
`Carl-312/daily-report-site-gray` 的 `gh-pages` 分支，对应
`https://carl-312.github.io/daily-report-site-gray/`。灰度 job 不调用 `actions/deploy-pages`，
不使用生产 `github-pages` environment，也不改写本仓库的 Pages artifact。

正式灰度手动输入固定为：

```text
run_mode=formal_gray
```

每日定时入口等价于上述正式灰度模式，无需人工提供
`workflow_dispatch` inputs；它不会隐式取得生产发布权限。

灰度站点根目录的 `gray-build.json` 保留 source repository、commit、Actions run ID
和 artifact 名，用于追溯当前在线灰度版本。

### 当前正式灰度（2026-07-21）

- 源提交：`0cbaef35569fcecf1620a0eae25379bf071f450e`
- 源运行：[`29818465019`](https://github.com/Carl-312/daily-report-site/actions/runs/29818465019)
- preview artifact：`daily-report-preview-29818465019`
- 灰度 Pages 运行：[`29818600100`](https://github.com/Carl-312/daily-report-site-gray/actions/runs/29818600100)
- 在线站点：[`https://carl-312.github.io/daily-report-site-gray/`](https://carl-312.github.io/daily-report-site-gray/)

该运行发布 10 条新闻，Trending health 通过，生产 deploy 跳过。页面的互动话题独立成段，
页尾“入选来源”按最终入选条目由代码生成。灰度清理后，GitHub 仅保留上述源运行、
灰度 Pages 运行及对应 deployment；旧灰度运行和失活 deployment 已删除。

## 保留策略说明

- `main` 仅保留最近 7 天的 `data/` 与 `content/`
- 更早的数据先打包为 `daily-report-YYYY-MM-DD.tar.gz`
- 归档上传到 Release `daily-report-archive`
- 上传成功后才执行清理，避免先删后丢

当前最小方案只对 `data/` / `content/` 做长期归档；站点本身只展示仓库保留窗口内的内容。

`workflow_dispatch` 在非 `main` 分支上仍可用于手动验证生成流程，但只上传预览 artifact，
不会回写仓库、上传归档或发布 Pages。`production` 也只有在 `main` 上才取得发布权限。

### 2026-07-10 灰度证据

成功预览 run `29076119648` 的输入为 `skip_generate=true`、`publish=false`、
`enable_tavily=false`；`generate-and-deploy` 成功，`deploy` 跳过，预览 artifact
为 `daily-report-preview-29076119648`。artifact 保留 2026-07-04 至 2026-07-09
内容与 `dist/`，不含 `content/2026-07-10.md`、`data/2026-07-10.json` 或
`dist/2026-07-10.html`。PR #8 仍为 OPEN/Draft（head
`gsd/daily-news-reliability`，base `main`）；本次 run 未发布 Pages，生产 URL 未变。

手动触发时 `enable_tavily=false` 运行 `--enrichment off`，设为 `true` 时运行
`--enrichment on`。定时任务不加覆盖参数，跟随 `config.yaml`（当前默认开启）。

Tavily 灰度限制：

- 定时任务按 `config.yaml` 决定 Tavily 是否启用；Secret 本身不改变配置。
- `run_mode=rebuild_preview` 只执行 `python main.py build`，不会验证 enrichment。
- 非 `main` 分支可用于手动验证命令和日志，但不会回写生成的 `data/` / `content/`，也不会发布 Pages。
- 单次 live 结果只能作为接线样本，不作为默认开启或修改 `trusted_domains` 的稳定证据。
- 如果 Tavily timeout、HTTP error、connection error 或 key 缺失，预期行为是 fail-open：主流程继续完成，已有 deduped articles 尽量保留，失败原因写入 JSON 诊断。

手动灰度后检查当天 `data/YYYY-MM-DD.json` 的 `enrichment` 字段：

- `enabled` / `applied` / `skip_reason` / `error`
- `verify_calls` / `refill_calls` / `fallback_calls` / `total_calls`
- `preserved_error_count` / `final_count` / `stop_reason`
- `verify_runs[*].request_outcome` 与 refill runs 的 `request_outcome`

### 2026-07-13 摘要契约预览证据

提交 `adc9bf0` 的 [preview run `29238871654`](https://github.com/Carl-312/daily-report-site/actions/runs/29238871654)
使用 `skip_generate=false`、`enable_tavily=false`、`publish=false`。2 条去重后候选生成 2 条摘要，
`a1/a2` 的来源契约校验通过，artifact 成功生成，`deploy` job 跳过；该 run 未回写仓库或发布
GitHub Pages。它验证的是摘要边界和灰度生成链路，不代表 Tavily 开启或生产发布已验收。

## 手动验证建议

合并前建议分别手动触发一次：

1. `CI`
2. `Daily Report Deploy`

重点检查：

- `dist/` 是否成功上传为 Pages artifact
- Release `daily-report-archive` 是否出现 tar.gz 资产
- `main` 上是否只保留最近 7 天的 `data/` / `content/`
- 手动设置 `run_mode=formal_gray` 时，日志是否显示 `--enrichment on`
- `data/YYYY-MM-DD.json` 是否包含可复盘的 `enrichment` 诊断
- `data/YYYY-MM-DD.json` 中 `summary.items[*].article_id` 是否均来自 `articles`，且在证据充足时达到每日目标 10 条、始终不超过 `max_summary_items=10`
- 聚合来源是否能拆出多条有独立标题和摘要的新闻，同时没有重复事实
- AGIHunt gray 时 `scripts/agihunt_gray_health.py` 已通过，preview artifact 根目录的
  去敏 `agihunt-gray-health.json` 显示健康；health gate 已核对 manifest 与 provenance
  中的频道和原帖 URL，且 `publish=false` artifact 没有发布 Pages

## 相关文档

- GitHub Pages：[`github-pages.md`](github-pages.md)
- 本地运行：[`local.md`](local.md)
- Tavily 接入总览：[`tavily.md`](tavily.md)
