from __future__ import annotations

from config import Settings, load_config


def test_modelscope_primary_model_defaults_to_glm_5_1(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("MODELSCOPE_MODEL", raising=False)

    cfg = load_config(str(tmp_path / "missing-config.yaml"))

    assert Settings().model == "ZhipuAI/GLM-5.1"
    assert cfg.model == "ZhipuAI/GLM-5.1"
    assert cfg.fallback_model == "Pro/zai-org/GLM-4.6"
