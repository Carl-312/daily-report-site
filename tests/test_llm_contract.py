from __future__ import annotations

import inspect
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import summarizer
from config import LLMExecutionPolicy, LLMModelCapability, LLMSettings
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


def _provider(
    name: str,
    model: str,
    key: str,
    *,
    execution: LLMExecutionPolicy | None = None,
) -> dict:
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
            execution=execution or LLMExecutionPolicy(attempt_timeout_seconds=30),
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
        summarizer,
        "_request_non_stream_completion",
        lambda *_args: _completion_payload(),
    )

    result = summarizer.summarize_result(
        [{"title": "English source title", "link": "https://example.test/a"}],
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
        "_request_non_stream_completion",
        lambda *_args: _completion_payload(prefix="以下是结果：\n", extra=True),
    )
    artifact_path = tmp_path / "summary-attempts.json"

    result = summarizer.summarize_result(
        [{"title": "Source", "link": "https://example.test/a"}],
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

    monkeypatch.setattr(summarizer, "_request_non_stream_completion", fail)
    artifact_path = tmp_path / "summary-attempts.json"
    providers = [
        _provider("ModelScope", "model-a", "secret-a"),
        _provider("ModelScope secondary", "model-b", "secret-b"),
    ]

    with pytest.raises(summarizer.AllProvidersFailed) as error:
        summarizer.summarize_result(
            [{"title": "Source", "link": "https://example.test/a"}],
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

    monkeypatch.setattr(summarizer, "_request_non_stream_completion", complete)
    artifact_path = tmp_path / "summary-attempts.json"

    result = summarizer.summarize_result(
        [{"title": "Source", "link": "https://example.test/a"}],
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


def test_first_empty_choices_is_persisted_then_same_model_retry_succeeds(
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
                retryable=True,
                telemetry=CompletionTelemetry(
                    transport_status="completed", http_status=200, choices_count=0
                ),
            )
        return _completion_payload()

    monkeypatch.setattr(summarizer, "_request_non_stream_completion", complete)
    persisted_decisions: list[tuple[str, ...]] = []
    persist = summarizer._persist_summary_attempts

    def observe_persist(path, attempts, **kwargs):
        persisted_decisions.append(
            tuple(attempt.retry_decision for attempt in attempts)
        )
        return persist(path, attempts, **kwargs)

    monkeypatch.setattr(summarizer, "_persist_summary_attempts", observe_persist)
    artifact_path = tmp_path / "summary-attempts.json"
    execution = LLMExecutionPolicy(
        max_output_tokens=1234,
        attempt_timeout_seconds=30,
        provider_budget_seconds=60,
        max_attempts=2,
        retry_backoff_seconds=0,
        retryable_codes=("empty_choices",),
    )

    result = summarizer.summarize_result(
        [{"title": "Source", "link": "https://example.test/a"}],
        attempt_artifact_path=artifact_path,
        provider_candidates=[
            _provider("ModelScope", "model-a", "secret-a", execution=execution)
        ],
    )

    artifact_text = artifact_path.read_text(encoding="utf-8")
    artifact = json.loads(artifact_text)
    assert calls == 2
    assert [attempt.status for attempt in result.attempts] == ["failed", "ok"]
    assert [attempt.sequence for attempt in result.attempts] == [1, 2]
    assert [attempt.provider_attempt_number for attempt in result.attempts] == [1, 2]
    assert result.attempts[1].retry_of_sequence == 1
    assert [attempt.retry_decision for attempt in result.attempts] == [
        "retry_scheduled",
        "selected",
    ]
    assert persisted_decisions[0] == ("not_evaluated",)
    assert persisted_decisions[1] == ("retry_scheduled",)
    assert artifact["schema_version"] == 2
    assert artifact["selected_attempt_sequence"] == 2
    assert artifact["attempts"][0]["attempt_timeout_seconds"] == 30
    assert artifact["attempts"][0]["max_output_tokens"] == 1234
    assert artifact["attempts"][0]["provider_budget_seconds"] == 60
    assert "secret-a" not in artifact_text
    assert VALID_SUMMARY not in artifact_text


def test_repeated_empty_choices_falls_back_after_exactly_two_requests(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(summarizer, "get_config", _config)
    monkeypatch.setattr(summarizer, "load_prompt", lambda: "prompt")
    monkeypatch.setattr(summarizer, "create_client", lambda *_args, **_kwargs: object())
    calls: list[str] = []

    def complete(_client, params):
        calls.append(params["model"])
        if params["model"] == "model-a":
            raise LLMCompatibilityError(
                "empty",
                stage="extraction",
                code="empty_choices",
                retryable=True,
                telemetry=CompletionTelemetry(
                    transport_status="completed", http_status=200, choices_count=0
                ),
            )
        return _completion_payload()

    monkeypatch.setattr(summarizer, "_request_non_stream_completion", complete)
    retrying = LLMExecutionPolicy(
        attempt_timeout_seconds=30,
        max_attempts=3,
        retry_backoff_seconds=0,
        retryable_codes=("empty_choices",),
    )

    result = summarizer.summarize_result(
        [{"title": "Source", "link": "https://example.test/a"}],
        attempt_artifact_path=tmp_path / "summary-attempts.json",
        provider_candidates=[
            _provider("ModelScope", "model-a", "secret-a", execution=retrying),
            _provider("Fallback", "model-b", "secret-b"),
        ],
    )

    assert calls == ["model-a", "model-a", "model-b"]
    assert [attempt.status for attempt in result.attempts] == [
        "failed",
        "failed",
        "ok",
    ]
    assert [attempt.retry_decision for attempt in result.attempts] == [
        "retry_scheduled",
        "retry_limit_reached",
        "selected",
    ]
    assert [attempt.provider_attempt_number for attempt in result.attempts] == [
        1,
        2,
        1,
    ]


def test_incomplete_output_is_not_retried_with_the_same_request(
    monkeypatch,
) -> None:
    monkeypatch.setattr(summarizer, "get_config", _config)
    monkeypatch.setattr(summarizer, "load_prompt", lambda: "prompt")
    monkeypatch.setattr(summarizer, "create_client", lambda *_args, **_kwargs: object())
    calls: list[str] = []

    def complete(_client, params):
        calls.append(params["model"])
        if params["model"] == "model-a":
            raise LLMCompatibilityError(
                "length",
                stage="extraction",
                code="incomplete_output",
                telemetry=CompletionTelemetry(
                    transport_status="completed",
                    http_status=200,
                    finish_reason="length",
                ),
            )
        return _completion_payload()

    monkeypatch.setattr(summarizer, "_request_non_stream_completion", complete)
    policy = LLMExecutionPolicy(
        attempt_timeout_seconds=30,
        max_attempts=2,
        retry_backoff_seconds=0,
        retryable_codes=("incomplete_output",),
    )

    result = summarizer.summarize_result(
        [{"title": "Source", "link": "https://example.test/a"}],
        provider_candidates=[
            _provider("ModelScope", "model-a", "secret-a", execution=policy),
            _provider("Fallback", "model-b", "secret-b"),
        ],
    )

    assert calls == ["model-a", "model-b"]
    assert result.attempts[0].failure_code == "incomplete_output"
    assert result.attempts[0].retry_decision == "failure_not_retryable"


def test_provider_budget_can_refuse_a_retry_without_delaying_fallback(
    monkeypatch,
) -> None:
    monkeypatch.setattr(summarizer, "get_config", _config)
    monkeypatch.setattr(summarizer, "load_prompt", lambda: "prompt")
    monkeypatch.setattr(summarizer, "create_client", lambda *_args, **_kwargs: object())
    calls: list[str] = []

    def complete(_client, params):
        calls.append(params["model"])
        if params["model"] == "model-a":
            raise LLMCompatibilityError(
                "timeout",
                stage="transport",
                code="timeout",
                retryable=True,
                telemetry=CompletionTelemetry(transport_status="failed"),
            )
        return _completion_payload()

    monkeypatch.setattr(summarizer, "_request_non_stream_completion", complete)
    policy = LLMExecutionPolicy(
        attempt_timeout_seconds=30,
        provider_budget_seconds=1,
        max_attempts=2,
        retry_backoff_seconds=2,
        retryable_codes=("timeout",),
    )

    result = summarizer.summarize_result(
        [{"title": "Source", "link": "https://example.test/a"}],
        provider_candidates=[
            _provider("ModelScope", "model-a", "secret-a", execution=policy),
            _provider("Fallback", "model-b", "secret-b"),
        ],
    )

    assert calls == ["model-a", "model-b"]
    assert result.attempts[0].retry_decision == "provider_budget_exhausted"


def test_run_deadline_can_refuse_a_retry_without_blocking_immediate_fallback(
    monkeypatch,
) -> None:
    monkeypatch.setattr(summarizer, "get_config", _config)
    monkeypatch.setattr(summarizer, "load_prompt", lambda: "prompt")
    monkeypatch.setattr(summarizer, "create_client", lambda *_args, **_kwargs: object())
    calls: list[str] = []

    def complete(_client, params):
        calls.append(params["model"])
        if params["model"] == "model-a":
            raise LLMCompatibilityError(
                "server",
                stage="http",
                code="http_5xx",
                retryable=True,
                telemetry=CompletionTelemetry(
                    transport_status="completed", http_status=503
                ),
            )
        return _completion_payload()

    monkeypatch.setattr(summarizer, "_request_non_stream_completion", complete)
    policy = LLMExecutionPolicy(
        attempt_timeout_seconds=30,
        max_attempts=2,
        retry_backoff_seconds=2,
        retryable_codes=("http_5xx",),
    )
    run_deadline = datetime.now(timezone.utc) + timedelta(seconds=1)

    result = summarizer.summarize_result(
        [{"title": "Source", "link": "https://example.test/a"}],
        deadline_at=run_deadline,
        provider_candidates=[
            _provider("ModelScope", "model-a", "secret-a", execution=policy),
            _provider("Fallback", "model-b", "secret-b"),
        ],
    )

    assert calls == ["model-a", "model-b"]
    assert result.attempts[0].retry_decision == "run_deadline_exhausted"
    assert result.attempts[0].run_deadline_at == run_deadline


def test_model_token_and_timeout_policy_reach_separate_request_fields(
    monkeypatch,
) -> None:
    monkeypatch.setattr(summarizer, "get_config", _config)
    monkeypatch.setattr(summarizer, "load_prompt", lambda: "prompt")
    captured: dict[str, object] = {}

    def create_client(_base_url, _api_key, *, timeout):
        captured["timeout"] = timeout
        return object()

    def complete(_client, params):
        captured["params"] = params
        return _completion_payload()

    monkeypatch.setattr(summarizer, "create_client", create_client)
    monkeypatch.setattr(summarizer, "_request_non_stream_completion", complete)
    policy = LLMExecutionPolicy(
        max_output_tokens=4321,
        attempt_timeout_seconds=17,
    )

    result = summarizer.summarize_result(
        [{"title": "Source", "link": "https://example.test/a"}],
        provider_candidates=[
            _provider("ModelScope", "model-a", "secret-a", execution=policy)
        ],
    )

    assert captured["timeout"] == 17
    assert captured["params"]["max_tokens"] == 4321
    assert captured["params"]["stream"] is False
    assert result.attempts[0].attempt_timeout_seconds == 17
    assert result.attempts[0].max_output_tokens == 4321


def test_public_summary_api_has_no_ignored_stream_parameter() -> None:
    assert "stream" not in inspect.signature(summarizer.summarize).parameters
    assert "stream" not in inspect.signature(summarizer.summarize_result).parameters
    assert not hasattr(summarizer, "_summarize_stream")


def test_buffered_stream_mode_uses_private_collector(monkeypatch) -> None:
    monkeypatch.setattr(summarizer, "get_config", _config)
    monkeypatch.setattr(summarizer, "load_prompt", lambda: "prompt")
    monkeypatch.setattr(summarizer, "create_client", lambda *_args, **_kwargs: object())
    captured: dict = {}

    def complete(_client, params):
        captured.update(params)
        return _completion_payload()

    monkeypatch.setattr(summarizer, "_request_buffered_stream_completion", complete)
    policy = LLMExecutionPolicy(
        delivery_mode="buffered_stream",
        attempt_timeout_seconds=30,
    )

    result = summarizer.summarize_result(
        [{"title": "Source", "link": "https://example.test/a"}],
        provider_candidates=[
            _provider("ModelScope", "model-a", "secret-a", execution=policy)
        ],
    )

    assert captured["stream"] is True
    assert result.attempts[0].delivery_mode == "buffered_stream"
    assert result.attempts[0].publishable is True


def test_openai_sdk_retries_stay_disabled(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_openai(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(summarizer, "OpenAI", fake_openai)

    summarizer.create_client("https://example.test/v1", "secret", timeout=12)

    assert captured["max_retries"] == 0
    assert captured["timeout"] == 12


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
