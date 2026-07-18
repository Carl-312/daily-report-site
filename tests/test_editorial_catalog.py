from __future__ import annotations

from utils.editorial_catalog import analyze_editorial_text, load_editorial_catalog


def test_catalog_tracks_frontier_families_across_us_and_china() -> None:
    catalog = load_editorial_catalog()

    assert catalog.schema_version == 1
    assert len(catalog.entities) >= 40

    cases = {
        "OpenAI releases GPT-5.6 for developers": ("openai", "gpt", "us"),
        "Anthropic launches Claude Fable 5": ("anthropic", "claude", "us"),
        "阿里发布 Qwen3.7 新模型": ("alibaba", "qwen", "cn"),
        "DeepSeek-V4-Pro API 正式上线": ("deepseek", "deepseek", "cn"),
        "月之暗面发布 Kimi K3": ("moonshot", "kimi", "cn"),
        "智谱 GLM-5.1 开放调用": ("zhipu", "glm", "cn"),
        "豆包 Doubao-Seed-2.0 更新": ("bytedance", "doubao", "cn"),
    }
    for title, (entity, family, region) in cases.items():
        analysis = analyze_editorial_text(title)
        assert entity in analysis.mentioned_entities
        assert family in analysis.model_families
        assert region in analysis.regions
        assert analysis.relevance_level == 3


def test_broad_technology_company_requires_explicit_ai_context() -> None:
    generic = analyze_editorial_text("Apple reports quarterly iPhone sales")
    ai_story = analyze_editorial_text("Apple launches an on-device AI model")

    assert generic.primary_entity == "apple"
    assert generic.relevance_level == 1
    assert ai_story.primary_entity == "apple"
    assert ai_story.relevance_level == 2
    assert ai_story.topic == "model_release"


def test_catalog_normalizes_model_brand_to_root_entity() -> None:
    analysis = analyze_editorial_text("Claude Fable 5 joins Max plans")

    assert analysis.primary_entity == "anthropic"
    assert analysis.mentioned_entities == ("anthropic",)
    assert analysis.model_families == ("claude",)
    assert analysis.topic == "product_access"
