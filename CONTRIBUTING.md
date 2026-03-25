# 开发贡献指南

## 开发环境

项目开发、文档示例和 CI 统一使用 `Python 3.12`。

```bash
mise install
mise use -g python@3.12
pip install -r requirements-dev.txt
```

依赖分层约定：

- `requirements.txt`：运行时依赖
- `requirements-dev.txt`：开发依赖入口，包含 Ruff、pytest、pytest-cov

## 分支与提交流程

- `main`：生产分支
- `feature/*`：功能分支
- `fix/*`：修复分支

建议流程：`feature/*` 或 `fix/*` -> Pull Request -> `main`

如果这轮治理改造需要分批提交，优先按 [`handbook/project-rollout.md`](handbook/project-rollout.md) 中的 4 个 PR 边界切分。

## 代码规范

- 使用 `from __future__ import annotations`
- 新增函数和类应带有清晰的类型标注
- 复杂逻辑补简短注释，避免无意义注释
- 变量命名使用 `snake_case`，类名使用 `PascalCase`

本地提交前至少执行：

```bash
ruff check .
ruff format --check .
pytest
```

如果需要自动修复格式或部分 lint：

```bash
ruff check --fix .
ruff format .
```

## CI 约定

仓库已接入独立 `CI` workflow：

- 触发：`push`、`pull_request`
- Python：固定 `3.12`
- 安装：`pip install -r requirements-dev.txt`
- 检查：`ruff check .`
- 格式：`ruff format --check .`
- 测试：`pytest`

本地通过不代表 CI 一定通过；提交前请尽量按 CI 顺序跑一遍。

## 测试要求

- 新增功能应补最小可运行测试
- 涉及构建、归档、路径或日期逻辑时，优先补单元测试
- 集成验证可用：

```bash
python main.py run --offline
python main.py build
```

## 目录约定

```text
handbook/   手写工程文档
content/    最近 7 天 Markdown 产物
data/       最近 7 天 JSON 产物
dist/       构建输出，Git 忽略
scripts/    自动化脚本
tests/      pytest 测试
```

注意：

- `dist/` 是纯构建输出，不进入 Git
- `data/` 和 `content/` 仅保留最近 7 天
- 历史产物通过 GitHub Release assets 归档

## 添加新闻源

1. 在 `sources/` 下新增抓取模块。
2. 在 `sources/__init__.py` 注册。
3. 在 `config.yaml` 的 `sources` 中启用。
4. 补对应测试或离线验证步骤。

更详细示例见 [handbook/guides/extending-sources.md](handbook/guides/extending-sources.md)。

## 安全与配置

- API Key 只放 `.env`
- 不要在代码和测试里硬编码密钥
- 修改输出路径时，同时更新 `config.py` / `config.yaml` / 文档

## 文档规范

- 面向使用者的文档统一放在 `handbook/`
- 生成站点统一输出到 `dist/`
- 修改 workflow、目录结构或保留策略时，必须同步更新 README 和 handbook

---

## 🤝 Pull Request 规范

### PR 模板

```markdown
## 变更描述
简述本次变更的目的和内容

## 变更类型
- [ ] 新功能
- [ ] Bug 修复
- [ ] 文档更新
- [ ] 重构

## 测试清单
- [ ] 本地测试通过
- [ ] Linting 检查通过
- [ ] 添加/更新了测试

## 相关 Issue
Closes #123
```

### Code Review 重点

- 代码逻辑正确性
- 是否符合项目规范
- 是否有适当的错误处理
- 文档和注释是否清晰

---

## 📧 联系方式

- **Issue Tracker**: GitHub Issues
- **讨论区**: GitHub Discussions
- **维护者**: @your-username

---

**感谢贡献!** 🎉
