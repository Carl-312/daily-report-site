from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import summarizer
from config import LLMModelCapability, LLMSettings
from utils.llm_compat import CompletionTelemetry, LLMCompatibilityError
from utils.summary_contracts import reader_summary_issues


VALID_SUMMARY = "发布重要产品更新，推动行业应用持续扩展并提升开发者实际工作效率。"


def _config() -> SimpleNamespace:
    return SimpleNamespace(
        max_output=2000,
        max_summary_items=10,
        title_max=150,
        desc_max=300,
        llm=LLMSettings(default_timeout_seconds=30),
    )


def _provider(name: str, model: str, key: str) -> dict:
    return {
        "provider_id": "modelscope",
        "name": name,
        "base_url": "https://modelscope.test/v1",
        "api_key": key,
        "model": model,
        "capability": LLMModelCapability(
            provider="modelscope",
            base_url="https://modelscope.test/v1",
            model=model,
            timeout_seconds=30,
        ),
    }


def _completion_payload(*, prefix: str = "", extra: bool = False) -> str:
    item = {"article_id": "a1", "summary": VALID_SUMMARY}
    payload: dict = {
        "items": [item],
        "discussion_topic": "你最关注哪条AI新闻？",
    }
    if extra:
        item["confidence"] = 0.9
        payload["provider_note"] = "ignored"
    return prefix + json.dumps(payload, ensure_ascii=False)


def test_model_title_is_optional_and_source_title_is_bound_locally(
    monkeypatch,
) -> None:
    monkeypatch.setattr(summarizer, "get_config", _config)
    monkeypatch.setattr(summarizer, "load_prompt", lambda: "prompt")
    monkeypatch.setattr(summarizer, "create_client", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(
        summarizer, "_summarize_sync", lambda *_args: _completion_payload()
    )

    result = summarizer.summarize_result(
        [{"title": "English source title", "link": "https://example.test/a"}],
        stream=False,
        provider_candidates=[_provider("ModelScope", "model-a", "secret-a")],
    )

    assert result.items[0].title == "English source title"
    assert result.items[0].url == "https://example.test/a"
    assert result.items[0].summary == VALID_SUMMARY
    assert result.validation_passed is True


def test_compatible_contract_has_an_explicit_legacy_rollback_switch() -> None:
    content = _completion_payload(prefix="以下是结果：\n", extra=True)

    with pytest.raises(summarizer.SummaryContractError):
        summarizer.validate_summary_quality(
            content,
            expected_items=1,
            expected_article_ids={"a1"},
            compatible_contract=False,
        )

    summarizer.validate_summary_quality(
        content,
        expected_items=1,
        expected_article_ids={"a1"},
        compatible_contract=True,
    )


def test_single_harmless_prefix_and_extra_fields_are_audited_not_trusted(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(summarizer, "get_config", _config)
    monkeypatch.setattr(summarizer, "load_prompt", lambda: "prompt")
    monkeypatch.setattr(summarizer, "create_client", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(
        summarizer,
        "_summarize_sync",
        lambda *_args: _completion_payload(prefix="以下是结果：\n", extra=True),
    )
    artifact_path = tmp_path / "summary-attempts.json"

    result = summarizer.summarize_result(
        [{"title": "Source", "link": "https://example.test/a"}],
        stream=False,
        attempt_artifact_path=artifact_path,
        provider_candidates=[_provider("ModelScope", "model-a", "secret-a")],
    )

    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    diagnostics = artifact["attempts"][0]["diagnostics"]
    assert result.items[0].title == "Source"
    assert "ignored_field:provider_note" in diagnostics
    assert "ignored_field:items[1].confidence" in diagnostics
    assert "secret-a" not in artifact_path.read_text(encoding="utf-8")


def test_all_provider_failures_are_persisted_before_the_final_exception(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(summarizer, "get_config", _config)
    monkeypatch.setattr(summarizer, "load_prompt", lambda: "prompt")
    monkeypatch.setattr(summarizer, "create_client", lambda *_args, **_kwargs: object())

    def fail(_client, params):
        telemetry = CompletionTelemetry(
            transport_status="completed",
            http_status=200,
            choices_count=0,
        )
        raise LLMCompatibilityError(
            "no choices",
            stage="extraction",
            code="empty_choices",
            telemetry=telemetry,
        )

    monkeypatch.setattr(summarizer, "_summarize_sync", fail)
    artifact_path = tmp_path / "summary-attempts.json"
    providers = [
        _provider("ModelScope", "model-a", "secret-a"),
        _provider("ModelScope secondary", "model-b", "secret-b"),
    ]

    with pytest.raises(summarizer.AllProvidersFailed) as error:
        summarizer.summarize_result(
            [{"title": "Source", "link": "https://example.test/a"}],
            stream=False,
            attempt_artifact_path=artifact_path,
            provider_candidates=providers,
        )

    artifact_text = artifact_path.read_text(encoding="utf-8")
    artifact = json.loads(artifact_text)
    assert [attempt["failure_code"] for attempt in artifact["attempts"]] == [
        "empty_choices",
        "empty_choices",
    ]
    assert [attempt["failure_stage"] for attempt in artifact["attempts"]] == [
        "extraction",
        "extraction",
    ]
    assert artifact["publishable"] is False
    assert artifact["real_api_attempted"] is True
    assert len(error.value.attempts) == 2
    assert "secret-a" not in artifact_text
    assert "secret-b" not in artifact_text
    assert "no choices" not in artifact_text


def test_fallback_success_keeps_both_attempts_and_selected_model(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(summarizer, "get_config", _config)
    monkeypatch.setattr(summarizer, "load_prompt", lambda: "prompt")
    monkeypatch.setattr(summarizer, "create_client", lambda *_args, **_kwargs: object())
    calls = 0

    def complete(_client, _params):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise LLMCompatibilityError(
                "empty",
                stage="extraction",
                code="empty_choices",
                telemetry=CompletionTelemetry(
                    transport_status="completed", http_status=200, choices_count=0
                ),
            )
        return _completion_payload()

    monkeypatch.setattr(summarizer, "_summarize_sync", complete)
    artifact_path = tmp_path / "summary-attempts.json"

    result = summarizer.summarize_result(
        [{"title": "Source", "link": "https://example.test/a"}],
        stream=False,
        attempt_artifact_path=artifact_path,
        provider_candidates=[
            _provider("ModelScope", "model-a", "secret-a"),
            _provider("ModelScope secondary", "model-b", "secret-b"),
        ],
    )

    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert [attempt.status for attempt in result.attempts] == ["failed", "ok"]
    assert artifact["publishable"] is True
    assert artifact["selected_provider"] == "ModelScope secondary"
    assert artifact["selected_model"] == "model-b"


def test_reader_sentence_accepts_a_terminal_quote_but_still_rejects_two_sentences() -> (
    None
):
    assert (
        reader_summary_issues(
            "该公司表示，新模型将帮助开发团队提升日常工作效率并显著降低部署成本。”"
        )
        == ()
    )
    assert "must contain exactly one reader sentence" in reader_summary_issues(
        "该公司发布了新模型。开发团队现已可以申请测试并评估部署效果。”"
    )
