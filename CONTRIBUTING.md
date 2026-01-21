# 开发贡献指南

本文档规定了 Daily Report Site 项目的开发规范和最佳实践。

---

## 🌳 分支策略

- **main**: 生产分支，所有 Release 从此分支发布
- **feature/***: 功能开发分支，命名格式 `feature/add-xxx-source`
- **fix/***: Bug 修复分支，命名格式 `fix/issue-123`

**合并流程**: Feature/Fix → main (Pull Request + Code Review)

---

## 📝 代码规范

### Python 风格 (PEP 8)

```python
# ✅ 推荐
def fetch_articles(source: str, max_count: int = 10) -> list[dict]:
    """
    从指定来源获取文章列表
    
    Args:
        source: 新闻源名称
        max_count: 最大文章数量
    
    Returns:
        文章字典列表
    """
    pass

# ❌ 避免
def get_data(s,n=10):  # 缺少类型提示和文档
    pass
```

**强制要求**:
- 使用 Type Hints (`from __future__ import annotations`)
- 函数/类必须有 Docstring
- 变量命名使用 `snake_case`
- 类名使用 `PascalCase`

### Linting 工具

项目使用 **Ruff** 作为统一的 Linter 和 Formatter:

```bash
# 安装 (已包含在 requirements.txt)
pip install ruff

# 检查代码
ruff check .

# 自动修复
ruff check --fix .

# 格式化代码
ruff format .
```

**CI 检查**: Pull Request 会自动运行 Ruff 检查，不通过无法合并

---

## 📁 文件组织

### 添加新的新闻源

1. 在 `sources/` 创建新模块:

```python
# sources/example_source.py
"""
Example Source Scraper
"""
from typing import List, Dict

def fetch() -> List[Dict[str, str]]:
    """
    从 ExampleSource 获取文章
    
    Returns:
        文章列表，格式: [{"title": "", "link": "", "desc": ""}]
    """
    return []
```

2. 在 `sources/__init__.py` 注册:

```python
from .example_source import fetch as fetch_example

SOURCE_REGISTRY = {
    # ...
    "example": fetch_example,
}
```

3. 在 `config.yaml` 启用:

```yaml
sources:
  example: true
```

### 目录规范

```
sources/
├── __init__.py        # Registry 注册表
├── base.py            # 基础类和工具函数
├── aibase.py          # AIBase 爬虫
└── techcrunch.py      # TechCrunch 爬虫

utils/
├── __init__.py
├── fileops.py         # 文件操作
├── dedupe.py          # 去重逻辑
└── datetime.py        # 日期工具
```

---

## 🧪 测试规范

### 单元测试 (推荐使用 pytest)

```bash
# 运行所有测试
pytest

# 运行单个模块
pytest tests/test_sources.py

# 查看覆盖率
pytest --cov=sources --cov-report=html
```

**测试覆盖要求**:
- 新增功能必须包含测试
- 核心模块 (`sources/`, `summarizer.py`) 覆盖率 > 80%

### 集成测试

```bash
# 测试完整流程 (离线模式)
python main.py run --offline

# 测试 API 连接
python main.py test
```

---

## 📦 依赖管理

**添加新依赖**:
1. 安装: `pip install package-name`
2. 更新 `requirements.txt`: `pip freeze > requirements.txt`
3. 在 PR 中说明依赖用途

**生产依赖 vs 开发依赖**:
- 生产: `requirements.txt` (必需)
- 开发: `requirements-dev.txt` (可选) - Linters, 测试工具等

---

## 🔐 安全规范

### 敏感信息处理

**✅ 正确做法**:
```python
from config import get_config

cfg = get_config()
api_key = cfg.api_key  # 从环境变量读取
```

**❌ 错误做法**:
```python
api_key = "sk-1234567890"  # 硬编码密钥
```

**环境变量规范**:
- 敏感信息仅存储在 `.env` (已在 `.gitignore`)
- 提供 `.env.example` 作为模板
- 在文档中说明必需的环境变量

---

## 📖 文档规范

### Markdown 文档

- 使用中文编写用户面向文档
- 代码注释使用英文
- 文件名使用小写+连字符: `extending-sources.md`

### Docstring 格式 (Google Style)

```python
def summarize(articles: list[dict], stream: bool = False) -> str:
    """
    使用 LLM 生成新闻摘要
    
    Args:
        articles: 文章列表，每个文章包含 title, link, desc
        stream: 是否启用流式输出
    
    Returns:
        生成的 Markdown 格式摘要
    
    Raises:
        ConnectionError: API 连接失败时
    """
    pass
```

---

## 🚀 发布流程

1. **版本号规范** (Semantic Versioning):
   - `v1.0.0`: 主版本.次版本.补丁版本
   - 示例: `v1.2.3`

2. **发布步骤**:
   ```bash
   # 更新 CHANGELOG.md
   git tag v1.2.3
   git push origin v1.2.3
   ```

3. **GitHub Release**: 
   - 自动触发 `.github/workflows/release.yml`
   - 生成 Release Notes

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
