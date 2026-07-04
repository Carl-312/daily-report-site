from __future__ import annotations

from config import Settings, load_config


def test_default_llm_models(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("MODELSCOPE_MODEL", raising=False)
    monkeypatch.delenv("SILICONFLOW_MODEL", raising=False)

    cfg = load_config(str(tmp_path / "missing-config.yaml"))

    assert Settings().model == "ZhipuAI/GLM-5.2"
    assert Settings().fallback_model == "Pro/moonshotai/Kimi-K2.6"
    assert cfg.model == "ZhipuAI/GLM-5.2"
    assert cfg.fallback_model == "Pro/moonshotai/Kimi-K2.6"


def test_llm_model_env_overrides(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("MODELSCOPE_MODEL", "custom/modelscope")
    monkeypatch.setenv("SILICONFLOW_MODEL", "custom/siliconflow")

    cfg = load_config(str(tmp_path / "missing-config.yaml"))

    assert cfg.model == "custom/modelscope"
    assert cfg.fallback_model == "custom/siliconflow"
