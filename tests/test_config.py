from __future__ import annotations

import pytest

from config import (
    LLMExecutionPolicy,
    LLMModelCapability,
    LLMSettings,
    Settings,
    load_config,
)


def test_default_llm_models(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("MODELSCOPE_MODEL", raising=False)
    monkeypatch.delenv("MODELSCOPE_SECONDARY_MODEL", raising=False)
    monkeypatch.delenv("SILICONFLOW_MODEL", raising=False)

    cfg = load_config(str(tmp_path / "missing-config.yaml"))

    assert Settings().model == "ZhipuAI/GLM-5.2"
    assert Settings().modelscope_secondary_model == ""
    assert Settings().fallback_model == "Pro/moonshotai/Kimi-K2.6"
    assert cfg.model == "ZhipuAI/GLM-5.2"
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


def test_repository_config_loads_endpoint_scoped_llm_capabilities(monkeypatch) -> None:
    monkeypatch.delenv("MODELSCOPE_MODEL", raising=False)

    cfg = load_config("config.yaml")
    glm = cfg.llm.capability_for(
        "modelscope",
        "https://api-inference.modelscope.cn/v1",
        "ZhipuAI/GLM-5.2",
    )
    qwen = cfg.llm.capability_for(
        "modelscope",
        "https://api-inference.modelscope.cn/v1",
        "Qwen/Qwen3-235B-A22B-Instruct-2507",
    )
    kimi = cfg.llm.capability_for(
        "modelscope",
        "https://api-inference.modelscope.cn/v1",
        "moonshotai/Kimi-K2.7-Code:Moonshot",
    )
    siliconflow = cfg.llm.capability_for(
        "siliconflow",
        "https://api.siliconflow.cn/v1",
        "Pro/moonshotai/Kimi-K2.6",
    )

    assert glm.thinking_control_parameter == "enable_thinking"
    assert glm.thinking_control_value is False
    assert glm.request_mode == "prompt_only"
    assert glm.execution.delivery_mode == "non_stream"
    assert glm.execution.max_output_tokens == 2000
    assert glm.execution.attempt_timeout_seconds == 120
    assert glm.execution.max_attempts == 1
    assert qwen.supports_json_schema is True
    assert qwen.enforces_json_schema is False
    assert qwen.request_mode == "prompt_only"
    assert kimi.execution.delivery_mode == "buffered_stream"
    assert kimi.execution.max_output_tokens == 16000
    assert kimi.execution.attempt_timeout_seconds == 240
    assert kimi.supports_temperature is False
    assert kimi.request_mode == "prompt_only"
    assert kimi.verification_sample_count == 4
    assert siliconflow.execution.max_attempts == 2
    assert siliconflow.execution.provider_budget_seconds == 365
    assert set(siliconflow.execution.retryable_codes) == {
        "timeout",
        "network_connection",
        "network_dns",
        "http_5xx",
    }
    assert cfg.llm.compatible_output_contract is True
    assert all(
        capability.model != "deepseek-ai/DeepSeek-V4-Pro"
        for capability in cfg.llm.capabilities
    )


def test_unverified_structured_output_cannot_be_enabled() -> None:
    with pytest.raises(ValueError, match="verified schema enforcement"):
        LLMModelCapability(
            provider="modelscope",
            model="custom/model",
            supports_json_schema=True,
            enforces_json_schema=False,
            request_mode="json_schema",
        )


def test_capability_lookup_does_not_leak_across_endpoints() -> None:
    settings = LLMSettings(
        capabilities=[
            LLMModelCapability(
                provider="modelscope",
                base_url="https://one.example/v1",
                model="same/model",
                thinking_control_parameter="enable_thinking",
                thinking_control_value=False,
            )
        ]
    )
    assert (
        settings.capability_for(
            "modelscope", "https://one.example/v1", "same/model"
        ).thinking_control_parameter
        == "enable_thinking"
    )
    assert (
        settings.capability_for(
            "modelscope", "https://two.example/v1", "same/model"
        ).thinking_control_parameter
        is None
    )


def test_execution_policy_rejects_unbounded_retry_configuration() -> None:
    with pytest.raises(ValueError):
        LLMExecutionPolicy(max_attempts=4)

    with pytest.raises(ValueError, match="duplicates"):
        LLMExecutionPolicy(retryable_codes=("timeout", "timeout"))


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
