# 推荐 PR 拆分

这轮治理改造建议按下面 4 个 PR 顺序合入，保持每一步都可独立验证、回滚成本低。

## 1. `chore/python-and-dev-deps-alignment`

目标：统一解释器版本与依赖入口。

建议纳入：

- `.python-version`
- `mise.toml`
- `requirements-dev.txt`
- `README.md`
- `CONTRIBUTING.md`
- `handbook/deployment/local.md`

验收点：

- 文档、CI、本地开发统一指向 `Python 3.12`
- 开发环境安装入口统一为 `pip install -r requirements-dev.txt`

## 2. `ci/add-ruff-pytest-checks`

目标：把质量检查和部署解耦。

建议纳入：

- `.github/workflows/ci.yml`
- `.gitignore`
- `tests/`

验收点：

- `push` / `pull_request` 会跑 Ruff 与 pytest
- 本地缓存目录不会误入 Git

## 3. `feat/archive-and-prune-generated-data`

目标：把主分支的 generated noise 收缩到最近 7 天。

建议纳入：

- `scripts/manage_retention.py`
- `.github/workflows/deploy.yml`
- `handbook/deployment/github-actions.md`
- `handbook/guides/troubleshooting.md`

验收点：

- 超过 7 天的 `data/` / `content/` 会先归档到 Release assets
- `main` 只保留最近 7 天热数据
- 非 `main` 手动验证不会误写 Release、仓库或 Pages

## 4. `refactor/separate-docs-and-build-output`

目标：拆开手写文档、构建输出和站点展示边界。

建议纳入：

- `handbook/`
- `build.py`
- `config.py`
- `config.yaml`
- `ARCHITECTURE.md`

验收点：

- 手写文档不再放在 `docs/`
- 站点输出统一到 `dist/`
- 站点明确只展示当前保留窗口内的近期内容，不再伪装成“全历史可浏览”

## 当前工作区怎么最稳妥地切

如果工作区已经混入多类改动，建议不要强行一次性提交成一个大 PR。

更稳妥的做法是：

1. 先按上面的边界用路径维度分批暂存。
2. 把 `docs/` 删除与 `handbook/` 新增放在同一批提交。
3. 把 `deploy.yml` 和 `scripts/manage_retention.py` 放在同一批提交。
4. 最后单独检查 README / handbook 是否仍与实际行为一致。
