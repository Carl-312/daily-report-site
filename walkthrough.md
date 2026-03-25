# Daily Report Site 规划建议

## 背景

基于 2026-03-25 的仓库现状，这个项目已经出现了几类典型的“规模刚开始上来就会反复踩坑”的问题：

- Python 版本声明分散在本地工具、CI、文档中，曾出现 `mise = 3.12`、CI = `3.11`、README = `3.10+` 的不一致。
- 贡献文档把 Ruff/pytest 描述成了已接入能力，但仓库原先没有 `requirements-dev.txt`，也没有对应 CI。
- 自动生成的 `content/`、`data/`、`docs/` 持续直接进入 `main`，每天都会制造额外 diff。
- `docs/` 目录同时承载“部署站点产物”和“手写工程文档”，职责混杂。

当前本地统计结果：

| 目录 | 文件数 | 体积 |
| --- | ---: | ---: |
| `content/` | 65 | 264K |
| `data/` | 64 | 776K |
| `docs/` | 75 | 376K |

虽然仓库体积现在还不大，但增长趋势是线性的，而且当前工作流会每天提交一次生成结果。继续沿用现状，后续会逐步放大这些问题：

- clone 变慢
- PR review 噪音变大
- diff 里混入大量产物变更
- “本地过、CI 挂”更难定位
- 目录语义越来越混乱

## 规划目标

建议用 3 个目标来约束后续改造：

1. 开发环境、CI 环境、文档说明只有一套可信版本定义。
2. 运行时依赖、开发依赖、质量检查职责清晰，能稳定复现。
3. 仓库只保留“值得长期进入 Git 历史”的内容，把高频生成产物和长尾归档从 `main` 中剥离出去。

## 建议总览

| 事项 | 优先级 | 当前问题 | 建议方向 |
| --- | --- | --- | --- |
| Python 版本统一 | 高 | 本地/CI/文档不一致 | 统一为 `Python 3.12`，由 `mise.toml` 和 CI 共同落实 |
| 依赖与文档一致性 | 高 | 文档说 Ruff 已在 `requirements.txt`，实际没有 | 拆分 `requirements.txt` 与 `requirements-dev.txt` |
| Ruff/pytest CI | 高 | 文档提到质量检查，但仓库无对应工作流 | 新增独立 `ci.yml`，跑 Ruff + pytest |
| `data/` 长期入库策略 | 中高 | 原始数据持续进入 `main` | 主分支仅保留最近 7 天，历史转 Release asset 或对象存储 |
| 源码与产物分层 | 中 | `content/`、`data/`、`docs/` 与源码混放；`docs/` 还混着手写文档 | 手写文档迁出 `docs/`，站点改为输出到独立目录，逐步停止将生成站点提交到 `main` |

## 具体建议

### 1. Python 版本策略统一为 `3.12`

建议结论：统一使用 `Python 3.12`，不再保留 `3.10+` 这种宽泛表述。

原因：

- 当前仓库已经使用 `mise.toml`，适合把它作为本地开发默认入口。
- CI 版本如果与本地不一致，最容易出现依赖解析差异、标准库行为差异、类型检查差异。
- “3.10+” 对读者友好，但对自动化不友好；工程上更需要明确值。

建议动作：

- `README`、部署文档、贡献文档统一写成 `Python 3.12`
- GitHub Actions 统一使用 `actions/setup-python` 的 `3.12`
- 开发者默认通过 `mise install` / `mise use -g python@3.12` 进入项目

验收标准：

- 仓库关键入口不再出现 `3.11`、`3.10+`
- 新同学按照 README 配置后，和 CI 使用相同版本

### 2. 运行时依赖与开发依赖分层

建议结论：保留 `requirements.txt` 作为运行时依赖，新增 `requirements-dev.txt` 作为开发依赖入口。

原因：

- 当前生产工作流只需要运行项目，不需要 Ruff/pytest。
- 开发工具混进运行时依赖，会让 CI、部署和本地环境边界不清晰。
- 文档如果要求使用 Ruff/pytest，就必须有稳定、明确的安装入口。

建议动作：

- `requirements.txt` 仅保留运行时依赖
- `requirements-dev.txt` 以 `-r requirements.txt` 开头，再补 `ruff`、`pytest`、`pytest-cov`
- 文档统一改成开发前执行 `pip install -r requirements-dev.txt`

验收标准：

- 文档不再声称 Ruff 已经包含在 `requirements.txt`
- 开发者只用一条命令即可拿到完整开发环境

### 3. 增加独立的 Ruff/pytest CI 工作流

建议结论：新增独立 `CI` 工作流，不与“日报生成/部署”工作流混在一起。

建议最小版本包含：

1. `push`、`pull_request` 触发
2. 固定 `Python 3.12`
3. 安装 `requirements-dev.txt`
4. 运行 `ruff check .`
5. 运行 `ruff format --check .`
6. 运行 `pytest`

原因：

- 质量检查和站点部署是两种职责，拆开后日志更清楚，失败原因更容易判断。
- Ruff 负责快速发现格式和静态问题；pytest 负责发现行为回归。
- 当前仓库还没有很多测试，先上最小版比等待“测试完善后再接 CI”更实际。

后续增强项：

- 补充覆盖率输出，如 `pytest --cov=sources --cov=summarizer`
- 将 CI 设为分支保护必过项

### 4. `data/` 长期入库策略

建议结论：`main` 分支只保留最近 7 天的 `data/` 和 `content/`，更老的历史产物转移到长期归档层。

建议采用“两层存储”：

- 热数据层：Git 仓库仅保留最近 7 天，方便调试、回溯、快速修复
- 冷归档层：历史日报原始 JSON / Markdown / 可选 HTML 进入 GitHub Release assets 或对象存储

为什么不建议继续全量放在 `main`：

- 这些文件几乎都是机器生成，不适合作为长期代码审查对象
- 每天新增内容会不断放大 Git 历史与 diff 噪音
- 将来哪怕单日文件不大，累计起来也会拖慢 clone、status、review

归档方案建议：

- 过渡方案：使用 GitHub Release assets，成本低、接入简单
- 长期推荐：对象存储（S3 / R2 / OSS 等），便于保留策略、索引和后续 API 化
- 不建议把 GitHub Actions workflow artifacts 当长期存储，因为其保留期和可访问性不适合作为永久归档

建议实施方式：

- 新增归档/清理脚本，按日期保留最近 7 天
- CI 在成功生成后：
  - 上传当天产物到归档层
  - 清理仓库内超过 7 天的 `data/`、`content/`
  - 再提交保留后的结果
- 归档层建议按日期组织，例如 `YYYY/MM/DD/`

风险与注意点：

- 如果站点要展示全历史，构建时就不能只依赖仓库里最近 7 天的数据
- 因此需要同时设计“站点如何获取历史”的机制，见下一节

### 5. 优化“产物与源码混放”

建议结论：把“工程文档”“构建输入”“构建输出”“长期归档”拆成不同层次，不再把它们全部堆在根目录和 `docs/` 中。

当前主要问题有两个：

1. `content/`、`data/`、`docs/` 都在 `main` 持续增长
2. `docs/` 目录同时包含：
   - 生成站点页面，如 `docs/2026-03-25.html`
   - 工程文档，如 `docs/deployment/local.md`

这会带来几个隐患：

- 目录语义不清楚，开发者很难一眼看出哪些是源码、哪些是产物
- GitHub Pages 部署目录和项目文档目录发生耦合
- 未来站点生成逻辑更复杂时，容易覆盖或污染手写文档

推荐目标结构：

```text
daily-report-site/
├── src-ish files...            # Python 代码与配置
├── handbook/                   # 手写工程文档（从 docs/ 迁出）
├── content/                    # 近期 Markdown 输入（仅保留最近 7 天）
├── data/                       # 近期 JSON 输入（仅保留最近 7 天）
├── dist/                       # 纯构建输出，不进入 Git
└── archive/                    # 可选，本地临时归档目录（通常不进 Git）
```

配套建议：

- 将手写工程文档从 `docs/` 迁到 `handbook/` 或 `project-docs/`
- 将站点构建输出目录从 `docs/` 改为 `dist/`
- GitHub Actions 的 Pages 上传路径从 `docs` 改为 `dist`
- `.gitignore` 忽略 `dist/`
- 每日自动工作流不再提交 `dist/`

为什么这里推荐 `dist/`：

- 当前 GitHub Pages 工作流已经使用 `upload-pages-artifact`，并不是依赖 “`main` 分支的 `/docs` 目录” 模式
- 既然部署已经走 artifact，就没有必要继续把生成站点长期放在 Git 历史中

### 6. 站点历史展示的推荐实现

如果采用“仓库只保留最近 7 天”的策略，建议同时明确站点的历史展示边界。

推荐有两种路径：

#### 路径 A：站点只展示最近 7 天，历史通过归档下载

优点：

- 实现最简单
- 对当前代码改动最少
- 非常适合作为第一阶段收敛方案

缺点：

- GitHub Pages 页面上不能直接浏览全历史

适用场景：

- 近期日报是主要流量入口
- 历史更多是备份和运维用途

#### 路径 B：站点保留全历史，但历史数据从归档层读取

优点：

- 用户体验完整
- 仓库本身仍然保持轻量

缺点：

- 需要补 manifest、索引或拉取逻辑
- 构建流程会更复杂

建议判断：

- 如果近期目标是先把仓库负担降下来，优先落地路径 A
- 如果后续产品定位里“可浏览历史日报”很重要，再升级到路径 B

## 推荐实施顺序

### Phase 1：先把环境和质量闭环补齐

目标：停止继续积累“配置不同步”问题。

- 完成 Python 3.12 统一
- 引入 `requirements-dev.txt`
- 新增 Ruff/pytest CI
- 更新 README / CONTRIBUTING / 部署文档

### Phase 2：控制产物规模

目标：让 `main` 不再无限增长。

- 新增“最近 7 天保留”清理脚本
- 选定归档后端：优先 Release assets，长期迁移对象存储
- 工作流生成后先归档，再清理，再提交

### Phase 3：拆分源码、文档、构建产物

目标：恢复目录语义清晰度，减少部署耦合。

- 手写文档从 `docs/` 迁移到 `handbook/`
- `build.py` 输出目录切换到 `dist/`
- Pages 部署改为上传 `dist/`
- `dist/` 不再进入 Git

### Phase 4：按产品目标决定是否保留全历史站点

目标：在“运维简单”和“历史可浏览”之间做明确取舍。

- 若只保留最近 7 天页面：直接链接外部归档
- 若保留全历史页面：补 manifest 和历史索引拉取机制

## 我更推荐的落地方案

如果以“尽快止损、最少重构”为优先级，建议采用下面这条路线：

1. 先完成 Python / 依赖 / CI 三件高优先级治理
2. 接着把 `data/` 和 `content/` 收缩到最近 7 天
3. 历史先落到 GitHub Release assets，避免一开始就引入对象存储运维成本
4. 再把手写文档迁出 `docs/`，站点输出改到 `dist/`
5. 最后再评估是否要做“站点可浏览全历史”

这样做的好处是：

- 短期内就能明显降低主分支噪音
- 不会一次性引入过多基础设施
- 每一步都可以独立成 PR，回滚成本低

## 建议后续 PR 切分

建议拆成 4 个独立 PR：

1. `chore/python-and-dev-deps-alignment`
2. `ci/add-ruff-pytest-checks`
3. `feat/archive-and-prune-generated-data`
4. `refactor/separate-docs-and-build-output`

这样评审粒度更清楚，也更容易逐步验证。
