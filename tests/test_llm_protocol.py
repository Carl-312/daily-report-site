from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from openai import APIConnectionError, APITimeoutError

from utils.llm_compat import (
    LLMCompatibilityError,
    classify_exception,
    endpoint_label,
    extract_single_json_object,
    request_chat_completion,
)


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "llm-compat"


class _RawCompletions:
    def __init__(self, text: str, content_type: str = "application/json") -> None:
        self.with_raw_response = SimpleNamespace(
            create=lambda **_params: SimpleNamespace(
                status_code=200,
                headers={
                    "content-type": content_type,
                    "x-request-id": "req_synthetic",
                },
                text=text,
            )
        )


def _raw_client(text: str, content_type: str = "application/json") -> SimpleNamespace:
    return SimpleNamespace(
        chat=SimpleNamespace(
            completions=_RawCompletions(text, content_type=content_type)
        )
    )


def _fixture(name: str) -> str:
    return (FIXTURE_ROOT / name).read_text(encoding="utf-8")


def test_fixture_provenance_never_claims_synthetic_data_is_live() -> None:
    metadata = json.loads(_fixture("metadata.json"))

    assert metadata["source_type"] == "synthetic"
    assert "live" not in metadata["source_type"]


def test_content_blocks_keep_reasoning_separate_and_record_usage() -> None:
    result = request_chat_completion(
        _raw_client(_fixture("content_blocks.json")), {"stream": False}
    )

    payload = json.loads(result.content)
    assert payload["items"][0]["article_id"] == "a1"
    assert "synthetic reasoning placeholder" not in result.content
    assert result.telemetry.reasoning_length > 0
    assert result.telemetry.reasoning_tokens == 20
    assert result.telemetry.prompt_tokens == 100
    assert result.telemetry.completion_tokens == 80
    assert result.telemetry.total_tokens == 180
    assert result.telemetry.request_id == "req_synthetic"
    assert len(result.telemetry.response_sha256 or "") == 64


@pytest.mark.parametrize(
    ("fixture_name", "stage", "code"),
    [
        ("choices_null.json", "extraction", "empty_choices"),
        ("reasoning_only.json", "extraction", "reasoning_only"),
        ("refusal.json", "extraction", "refusal"),
        ("finish_length.json", "extraction", "incomplete_output"),
        ("multi_document.txt", "envelope", "protocol_multi_document"),
    ],
)
def test_protocol_fixtures_have_stable_failure_codes(
    fixture_name: str, stage: str, code: str
) -> None:
    with pytest.raises(LLMCompatibilityError) as error:
        request_chat_completion(_raw_client(_fixture(fixture_name)), {"stream": False})

    assert error.value.stage == stage
    assert error.value.code == code
    assert error.value.telemetry is not None


def test_completed_empty_choices_is_eligible_for_policy_evaluation() -> None:
    with pytest.raises(LLMCompatibilityError) as error:
        request_chat_completion(_raw_client(_fixture("choices_null.json")), {})

    assert error.value.code == "empty_choices"
    assert error.value.retryable is True


def test_wrong_content_type_is_not_treated_as_a_contract_failure() -> None:
    with pytest.raises(LLMCompatibilityError) as error:
        request_chat_completion(
            _raw_client(_fixture("content_blocks.json"), "text/plain"),
            {"stream": False},
        )

    assert (error.value.stage, error.value.code) == (
        "envelope",
        "protocol_wrong_content_type",
    )


def test_invalid_response_json_is_an_envelope_failure() -> None:
    with pytest.raises(LLMCompatibilityError) as error:
        request_chat_completion(_raw_client("not-json"), {"stream": False})

    assert (error.value.stage, error.value.code) == (
        "envelope",
        "protocol_invalid_json",
    )


def test_missing_message_is_distinct_from_empty_choices() -> None:
    response = json.dumps({"choices": [{"index": 0, "finish_reason": "stop"}]})

    with pytest.raises(LLMCompatibilityError) as error:
        request_chat_completion(_raw_client(response), {"stream": False})

    assert (error.value.stage, error.value.code) == (
        "extraction",
        "missing_message",
    )


def test_string_content_blocks_are_normalized_without_using_reasoning() -> None:
    response = json.dumps(
        {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "content": ["final ", "text"],
                        "reasoning_content": "private reasoning",
                    },
                }
            ]
        }
    )

    completion = request_chat_completion(_raw_client(response), {"stream": False})

    assert completion.content == "final text"
    assert completion.telemetry.reasoning_length == len("private reasoning")


@pytest.mark.parametrize(
    "content",
    [
        '{"items":[],"discussion_topic":"问题？"}',
        '```json\n{"items":[],"discussion_topic":"问题？"}\n```',
        '以下是结果：\n{"items":[],"discussion_topic":"问题？"}\n谢谢。',
    ],
)
def test_final_text_parser_accepts_one_unambiguous_root_object(content: str) -> None:
    assert extract_single_json_object(content)["items"] == []


@pytest.mark.parametrize(
    "content",
    [
        '{"items":[]}\n{"items":[]}',
        '结果一：{"items":[]} 结果二：{"items":[]}',
        '```json\n{"items":[]}\n```\n{"items":[]}',
    ],
)
def test_final_text_parser_never_guesses_between_multiple_objects(content: str) -> None:
    with pytest.raises(LLMCompatibilityError) as error:
        extract_single_json_object(content)

    assert error.value.code == "contract_multiple_json"


def test_failure_classifier_keeps_http_categories_mutually_exclusive() -> None:
    provider_error = RuntimeError("model has no provider supported")
    provider_error.status_code = 400
    auth_error = RuntimeError("forbidden")
    auth_error.status_code = 403
    rate_error = RuntimeError("slow down")
    rate_error.status_code = 429
    server_error = RuntimeError("upstream unavailable")
    server_error.status_code = 503

    assert classify_exception(provider_error).code == "provider_unavailable"
    assert classify_exception(auth_error).code == "authentication"
    assert classify_exception(rate_error).code == "rate_limit"
    assert classify_exception(server_error).code == "http_5xx"


def test_failure_classifier_keeps_only_the_retry_after_duration() -> None:
    rate_error = RuntimeError("slow down")
    rate_error.status_code = 429
    rate_error.response = SimpleNamespace(headers={"retry-after": "7"})

    classification = classify_exception(rate_error)

    assert classification.code == "rate_limit"
    assert classification.retryable is True
    assert classification.retry_after_seconds == 7


def test_failure_classifier_distinguishes_timeout_dns_and_proxy() -> None:
    request = httpx.Request("POST", "https://example.test/v1/chat/completions")

    assert classify_exception(APITimeoutError(request)).code == "timeout"
    assert (
        classify_exception(
            APIConnectionError(
                message="Temporary failure in name resolution", request=request
            )
        ).code
        == "network_dns"
    )
    assert (
        classify_exception(
            APIConnectionError(message="Proxy tunnel failed", request=request)
        ).code
        == "network_proxy"
    )


def test_endpoint_label_removes_credentials_query_and_fragment() -> None:
    assert (
        endpoint_label(
            "https://user:secret@example.test:8443/v1/?token=secret#fragment"
        )
        == "https://example.test:8443/v1"
    )
