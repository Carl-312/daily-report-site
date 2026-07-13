# 快速开始

## 项目用途

流水线从配置的新闻源抓取候选，执行本地 URL/故事去重，可选通过 Tavily 做受控增强，生成中文摘要，构建 GitHub Pages 静态站点。摘要和发布都有本地契约校验；输入不足时保持真实条数，不用提示词硬凑。

## 环境要求

- Python 3.12
- 本地运行不要求 API key；没有可用模型 key 时使用显式离线模式

## 安装与配置

```bash
pip install -r requirements-dev.txt
cp .env.example .env
```

按需在 `.env` 填写 `MODELSCOPE_API_KEY` 或 `SILICONFLOW_API_KEY`。非密钥配置位于 [`config.yaml`](../config.yaml)，字段说明见[配置指南](operations/configuration.md)。

## 运行

```bash
# 完整流程
python main.py run

# 无需模型 key 的确定性本地流程
python main.py run --offline

# 分阶段执行
python main.py fetch
python main.py summarize
python main.py build
```

Tavily 是默认关闭的 post-fetch enrichment，只在明确需要时启用：

```bash
TAVILY_API_KEY=... python3 main.py run --offline --enrichment on
python3 main.py run --offline --enrichment off
```

本地预览构建结果：

```bash
python -m http.server 8000 --directory dist
```

## 变更前最小检查

```bash
ruff check .
ruff format --check .
pytest -q
git diff --check
```

更完整的本地运行、失败恢复和发布说明见[运行与部署](operations/README.md)；贡献分支和提交约束见[开发指南](development/README.md)。
