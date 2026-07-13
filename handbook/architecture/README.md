# 架构

## 阅读顺序

1. [系统架构与数据流](system.md)：完整的模块、阶段和可靠性说明
2. [接口参考](../reference/api.md)：跨阶段调用边界和数据契约
3. [开发指南](../development/README.md)：修改边界、扩展方式和验证要求

## 当前边界

```text
sources
  -> canonical URL / story dedupe
  -> optional Tavily enrichment
  -> staged JSON checkpoint
  -> structured SummaryResult + local contract validation
  -> deterministic Markdown rendering
  -> staged static-site build
  -> quality gate / promotion / GitHub Pages
```

核心约束：失败运行不能覆盖上一版已发布产物；每条摘要必须通过 `article_id` 映射回输入来源；同一来源可支撑多条彼此独立的新闻；去重和发布门禁不依赖 LLM 自觉遵守。

## 代码归属

- 抓取与 source registry：`sources/`
- 去重与摘要契约：`utils/dedupe.py`、`utils/summary_contracts.py`
- 模型调用与摘要解析：`summarizer.py`
- 运行编排与 CLI：`main.py`
- 文件持久化：`utils/storage.py`
- 静态站点：`build.py`
- 可选 Tavily：`utils/news_enrichment.py`

架构文档描述边界和决策，不复制每次运行的结果；运行结果和质量结论统一放在 [`../quality/`](../quality/README.md)。
