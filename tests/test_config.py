from __future__ import annotations

from config import Settings, load_config


def test_default_llm_models(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("MODELSCOPE_MODEL", raising=False)
    monkeypatch.delenv("MODELSCOPE_SECONDARY_MODEL", raising=False)
    monkeypatch.delenv("SILICONFLOW_MODEL", raising=False)

    cfg = load_config(str(tmp_path / "missing-config.yaml"))

    assert Settings().model == "ZhipuAI/GLM-5.2"
    assert Settings().modelscope_secondary_model == "moonshotai/Kimi-K2.7-Code"
    assert Settings().fallback_model == "Pro/moonshotai/Kimi-K2.6"
    assert cfg.model == "ZhipuAI/GLM-5.2"
    assert cfg.modelscope_secondary_model == "moonshotai/Kimi-K2.7-Code"
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
    assert cfg.sources["agihunt"] is False
