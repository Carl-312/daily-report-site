from __future__ import annotations

import pytest

from config import Settings, load_config


def test_default_llm_models(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("MODELSCOPE_MODEL", raising=False)
    monkeypatch.delenv("MODELSCOPE_SECONDARY_MODEL", raising=False)
    monkeypatch.delenv("SILICONFLOW_MODEL", raising=False)

    cfg = load_config(str(tmp_path / "missing-config.yaml"))

    assert Settings().model == "Qwen/Qwen3.5-35B-A3B"
    assert Settings().modelscope_secondary_model == ""
    assert Settings().fallback_model == "Pro/moonshotai/Kimi-K2.6"
    assert cfg.model == "Qwen/Qwen3.5-35B-A3B"
    assert cfg.modelscope_secondary_model == ""
    assert cfg.fallback_model == "Pro/moonshotai/Kimi-K2.6"


def test_llm_model_env_overrides(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("MODELSCOPE_MODEL", "custom/modelscope")
    monkeypatch.setenv("MODELSCOPE_SECONDARY_MODEL", "custom/modelscope-secondary")
    monkeypatch.setenv("SILICONFLOW_MODEL", "custom/siliconflow")

    cfg = load_config(str(tmp_path / "missing-config.yaml"))

    assert cfg.model == "custom/modelscope"
    assert cfg.modelscope_secondary_model == "custom/modelscope-secondary"
    assert cfg.fallback_model == "custom/siliconflow"


def test_agihunt_secret_is_environment_only_and_policy_loads_from_yaml(
    monkeypatch, tmp_path
) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
sources:
  agihunt: false
agihunt:
  include_report: false
  request_budget: 2
  core_channels: [models]
  supplemental_channel: products
  max_articles: 10
  cache_ttl_seconds: 900
  use_environment_proxy: false
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("AGIHUNT_API_KEY", "agihunt-test-secret")

    cfg = load_config(str(config_path))

    assert cfg.agihunt_api_key == "agihunt-test-secret"
    assert cfg.agihunt.cache_ttl_seconds == 900
    assert cfg.agihunt.use_environment_proxy is False
    assert cfg.agihunt.core_channels == ["models"]
    assert cfg.agihunt.max_articles == 10
    assert cfg.sources["agihunt"] is False


def test_agihunt_candidate_limit_must_fit_the_channel_prefix_capacity() -> None:
    with pytest.raises(ValueError, match="candidate capacity"):
        Settings(
            agihunt={
                "core_channels": ["models"],
                "supplemental_channel": "products",
                "max_articles": 11,
                "per_channel_limit": 5,
            }
        )


def test_default_agihunt_candidate_pool_has_room_for_deduplication() -> None:
    settings = Settings().agihunt

    assert settings.max_articles == 20
    assert settings.per_channel_limit == 6
    assert (
        len(settings.core_channels) + 1
    ) * settings.per_channel_limit > settings.max_articles


def test_default_enrichment_uses_the_candidate_queue_budget_without_refill() -> None:
    settings = Settings().enrichment

    assert settings.enabled is True
    assert settings.max_total_calls == 30
    assert settings.min_articles == 0
    assert settings.max_verify_calls == 0
    assert settings.max_refill_rounds == 0
    assert settings.max_lead_candidates == 10
    assert settings.lead_search_rounds == 2
    assert settings.lead_search_depth == "advanced"
    assert settings.enrichment_deadline_reserve_seconds == 240


def test_agihunt_trending_policy_loads_without_a_secret(monkeypatch, tmp_path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
sources:
  agihunt_trending: false
agihunt_trending:
  day_offset: -1
  max_articles: 12
  expected_articles: 15
  minimum_articles: 10
  virtual_time_budget_ms: 9000
""",
        encoding="utf-8",
    )
    monkeypatch.delenv("AGIHUNT_API_KEY", raising=False)

    cfg = load_config(str(config_path))

    assert cfg.sources["agihunt_trending"] is False
    assert cfg.agihunt_trending.day_offset == -1
    assert cfg.agihunt_trending.max_articles == 12
    assert cfg.agihunt_trending.virtual_time_budget_ms == 9000
    assert cfg.agihunt_api_key == ""


def test_agihunt_trending_rejects_an_impossible_article_contract() -> None:
    with pytest.raises(ValueError, match="minimum_articles"):
        Settings(
            agihunt_trending={
                "minimum_articles": 16,
                "expected_articles": 15,
            }
        )
