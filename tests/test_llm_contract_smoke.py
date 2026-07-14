from __future__ import annotations

import json
from types import SimpleNamespace

from config import LLMSettings
from scripts import llm_contract_smoke
from utils.summary_contracts import SummaryAttempt, SummaryItem, SummaryResult


def _args(**overrides):
    values = {
        "live": False,
        "data": "unused.json",
        "models": None,
        "prompt_path": None,
        "request_mode": "prompt_only",
        "schema_conflict": False,
        "request_budget": 1,
        "timeout": None,
        "output": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_contract_smoke_requires_explicit_live_acknowledgement(capsys) -> None:
    assert llm_contract_smoke.run(_args()) == 2
    assert "without --live" in capsys.readouterr().err


def test_contract_smoke_writes_only_secret_safe_attempt_evidence(
    monkeypatch, tmp_path
) -> None:
    data_path = tmp_path / "report.json"
    data_path.write_text(
        json.dumps({"articles": [{"title": "Story", "link": "https://x.test"}]}),
        encoding="utf-8",
    )
    output_path = tmp_path / "probe.json"
    cfg = SimpleNamespace(
        api_key="modelscope-secret",
        api_base_url="https://api-inference.modelscope.cn/v1",
        model="model-a",
        llm=LLMSettings(default_timeout_seconds=30),
    )
    monkeypatch.setattr(llm_contract_smoke, "get_config", lambda: cfg)
    captured: dict = {}

    def fake_summarize_result(*_args, **kwargs):
        captured.update(kwargs)
        return SummaryResult(
            policy="required_ai",
            items=(
                SummaryItem(
                    article_id="a1",
                    title="Story",
                    summary="发布重要产品更新，推动行业应用持续扩展并提升开发者实际工作效率。",
                    url="https://x.test",
                ),
            ),
            discussion_topic="你最关注哪条AI新闻？",
            provider="ModelScope live probe",
            model="model-a",
            input_fingerprint="input",
            prompt_fingerprint="prompt",
            attempts=(
                SummaryAttempt(
                    provider="ModelScope live probe",
                    model="model-a",
                    status="ok",
                    publishable=True,
                ),
            ),
            validation_passed=True,
        )

    monkeypatch.setattr(
        llm_contract_smoke,
        "summarize_result",
        fake_summarize_result,
    )

    prompt_path = tmp_path / "experiment.md"
    prompt_path.write_text("experimental prompt", encoding="utf-8")

    exit_code = llm_contract_smoke.run(
        _args(
            live=True,
            data=str(data_path),
            output=str(output_path),
            models=["model-a"],
            prompt_path=str(prompt_path),
        )
    )

    artifact_text = output_path.read_text(encoding="utf-8")
    artifact = json.loads(artifact_text)
    assert exit_code == 0
    assert artifact["source_type"] == "live"
    assert artifact["prompt_path"] == str(prompt_path)
    assert artifact["results"][0]["contract"]["status"] == "publishable"
    assert "modelscope-secret" not in artifact_text
    assert captured["prompt_path"] == prompt_path
