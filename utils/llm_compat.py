"""Provider-neutral helpers for OpenAI-compatible chat completions.

The OpenAI-compatible label only promises an HTTP shape.  Providers still
vary in how they encode final text, reasoning, refusal, usage, and even the
response document itself.  This module keeps those protocol differences away
from the daily-summary contract and, importantly, never promotes reasoning to
reader-visible content.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import json
from json import JSONDecodeError
import re
from typing import Any, Literal, Mapping
from urllib.parse import urlsplit

from openai import (
    APIConnectionError,
    APIResponseValidationError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    PermissionDeniedError,
    RateLimitError,
)


FailureStage = Literal[
    "transport",
    "http",
    "envelope",
    "extraction",
    "contract",
    "provenance",
    "quality",
]
TransportStatus = Literal["not_started", "failed", "completed"]

_JSON_CONTENT_TYPE = re.compile(r"(?:^|[/+])json(?:$|[;\s])", re.IGNORECASE)
_JSON_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL | re.IGNORECASE)
_REASONING_FIELDS = (
    "reasoning_content",
    "reasoning",
    "reasoning_details",
)
_SAFE_AFFIX_MAX_CHARS = 200


@dataclass(frozen=True, slots=True)
class FailureClassification:
    """Stable, mutually exclusive classification for one failed attempt."""

    stage: FailureStage
    code: str
    retryable: bool
    http_status: int | None = None
    request_id: str | None = None
    retry_after_seconds: float | None = None


@dataclass(slots=True)
class CompletionTelemetry:
    """Secret-safe response facts carried into a persisted attempt record."""

    transport_status: TransportStatus = "not_started"
    http_status: int | None = None
    request_id: str | None = None
    retry_after_seconds: float | None = None
    content_type: str | None = None
    response_sha256: str | None = None
    choices_count: int | None = None
    content_length: int = 0
    reasoning_length: int = 0
    finish_reason: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    reasoning_tokens: int | None = None
    total_tokens: int | None = None
    final_text_received: bool = False
    diagnostics: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class CompletionResult:
    """Final assistant text plus non-sensitive protocol observations."""

    content: str
    telemetry: CompletionTelemetry


class LLMCompatibilityError(ValueError):
    """A classified failure between the request and publication contract."""

    def __init__(
        self,
        message: str,
        *,
        stage: FailureStage,
        code: str,
        retryable: bool = False,
        telemetry: CompletionTelemetry | None = None,
    ) -> None:
        super().__init__(message)
        self.stage = stage
        self.code = code
        self.retryable = retryable
        self.telemetry = telemetry


def endpoint_label(base_url: str) -> str:
    """Render an endpoint without credentials, query parameters, or fragments."""

    parsed = urlsplit(base_url)
    host = parsed.hostname or "invalid-host"
    port = f":{parsed.port}" if parsed.port else ""
    path = parsed.path.rstrip("/")
    scheme = parsed.scheme or "https"
    return f"{scheme}://{host}{port}{path}"


def classify_exception(exc: Exception) -> FailureClassification:
    """Map SDK, HTTP, and local protocol failures to stable reason codes."""

    if isinstance(exc, LLMCompatibilityError):
        telemetry = exc.telemetry
        return FailureClassification(
            stage=exc.stage,
            code=exc.code,
            retryable=exc.retryable,
            http_status=telemetry.http_status if telemetry else None,
            request_id=telemetry.request_id if telemetry else None,
            retry_after_seconds=(telemetry.retry_after_seconds if telemetry else None),
        )

    status = _optional_int(getattr(exc, "status_code", None))
    request_id = _optional_text(getattr(exc, "request_id", None))
    retry_after_seconds = _retry_after_seconds(exc)
    message = " ".join(str(exc).lower().split())

    if isinstance(exc, APITimeoutError) or _looks_like_timeout(exc, message):
        return FailureClassification(
            "transport", "timeout", True, retry_after_seconds=retry_after_seconds
        )
    if isinstance(exc, APIConnectionError):
        if _contains_any(message, "proxy", "tunnel"):
            code = "network_proxy"
        elif _contains_any(
            message,
            "name or service not known",
            "nodename nor servname",
            "temporary failure in name resolution",
            "getaddrinfo",
            "dns",
        ):
            code = "network_dns"
        else:
            code = "network_connection"
        return FailureClassification(
            "transport", code, True, retry_after_seconds=retry_after_seconds
        )

    if isinstance(exc, (AuthenticationError, PermissionDeniedError)) or status in {
        401,
        403,
    }:
        return FailureClassification(
            "http",
            "authentication",
            False,
            status,
            request_id,
            retry_after_seconds,
        )
    if isinstance(exc, RateLimitError) or status == 429:
        return FailureClassification(
            "http", "rate_limit", True, status, request_id, retry_after_seconds
        )
    if isinstance(exc, BadRequestError) or status == 400:
        code = (
            "provider_unavailable"
            if _contains_any(
                message,
                "no provider supported",
                "provider not supported",
                "model is unavailable",
            )
            else "bad_request"
        )
        return FailureClassification(
            "http", code, False, status, request_id, retry_after_seconds
        )
    if isinstance(exc, APIStatusError) or status is not None:
        code = "http_5xx" if status is not None and status >= 500 else "http_error"
        return FailureClassification(
            "http",
            code,
            status is not None and (status >= 500 or status in {408, 409}),
            status,
            request_id,
            retry_after_seconds,
        )
    if isinstance(exc, (JSONDecodeError, APIResponseValidationError)):
        return FailureClassification("envelope", "protocol_invalid_json", False)
    return FailureClassification("transport", "network_unknown", False)


def request_chat_completion(client: Any, params: dict[str, Any]) -> CompletionResult:
    """Request one non-streaming completion and extract final assistant text.

    Real OpenAI 1.x/2.x clients expose ``with_raw_response``.  Reading that
    response before SDK parsing lets us reject concatenated JSON documents and
    wrong content types deterministically.  Lightweight compatible clients and
    test doubles can still provide the ordinary ``create`` method.
    """

    telemetry = CompletionTelemetry()
    resource = client.chat.completions
    raw_resource = getattr(resource, "with_raw_response", None)
    try:
        if raw_resource is not None and hasattr(raw_resource, "create"):
            raw_response = raw_resource.create(**params)
            telemetry.transport_status = "completed"
            telemetry.http_status = _optional_int(
                getattr(raw_response, "status_code", None)
            )
            telemetry.request_id = _header_value(
                getattr(raw_response, "headers", None), "x-request-id"
            )
            telemetry.content_type = _normalized_content_type(
                _header_value(getattr(raw_response, "headers", None), "content-type")
            )
            raw_text = _raw_response_text(raw_response)
            telemetry.response_sha256 = hashlib.sha256(
                raw_text.encode("utf-8")
            ).hexdigest()
            document = _decode_response_document(raw_text, telemetry)
        else:
            response = resource.create(**params)
            telemetry.transport_status = "completed"
            telemetry.http_status = 200
            telemetry.request_id = _optional_text(
                getattr(response, "_request_id", None)
            )
            document = _to_plain(response)
            canonical = json.dumps(
                document,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            )
            telemetry.response_sha256 = hashlib.sha256(
                canonical.encode("utf-8")
            ).hexdigest()
    except Exception as exc:
        if isinstance(exc, LLMCompatibilityError):
            if exc.telemetry is None:
                exc.telemetry = telemetry
            raise
        classification = classify_exception(exc)
        telemetry.transport_status = (
            "failed" if classification.stage == "transport" else "completed"
        )
        telemetry.http_status = classification.http_status
        telemetry.request_id = classification.request_id
        telemetry.retry_after_seconds = classification.retry_after_seconds
        raise LLMCompatibilityError(
            f"chat completion failed ({classification.code})",
            stage=classification.stage,
            code=classification.code,
            retryable=classification.retryable,
            telemetry=telemetry,
        ) from exc

    if not isinstance(document, Mapping):
        raise LLMCompatibilityError(
            "provider response root must be a JSON object",
            stage="envelope",
            code="protocol_shape",
            telemetry=telemetry,
        )
    return _extract_final_text(document, telemetry)


def request_streaming_chat_completion(
    client: Any, params: dict[str, Any]
) -> CompletionResult:
    """Buffer one SSE completion and expose only its final assistant content.

    Reasoning deltas are counted for telemetry but are never appended to the
    final text.  The fully buffered content still passes through the same
    extraction checks as a non-streaming response before callers can validate
    or publish it.
    """

    telemetry = CompletionTelemetry(content_type="text/event-stream")
    request_params = dict(params)
    request_params["stream"] = True
    response_hasher = hashlib.sha256()
    states: dict[int, dict[str, Any]] = {}
    usage: Any = None

    try:
        stream = client.chat.completions.create(**request_params)
        telemetry.transport_status = "completed"
        telemetry.http_status = 200
        for raw_chunk in stream:
            chunk = _to_plain(raw_chunk)
            canonical = json.dumps(
                chunk,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            )
            response_hasher.update(canonical.encode("utf-8"))
            if not isinstance(chunk, Mapping):
                raise LLMCompatibilityError(
                    "provider stream chunk must be a JSON object",
                    stage="envelope",
                    code="protocol_shape",
                    telemetry=telemetry,
                )
            if chunk.get("usage") is not None:
                usage = chunk.get("usage")
            choices = chunk.get("choices", [])
            if choices is None:
                choices = []
            if not isinstance(choices, (list, tuple)):
                raise LLMCompatibilityError(
                    "provider stream choices must be an array",
                    stage="envelope",
                    code="protocol_shape",
                    telemetry=telemetry,
                )
            for raw_choice in choices:
                choice = _mapping_or_none(raw_choice)
                if choice is None:
                    raise LLMCompatibilityError(
                        "provider stream choice must be an object",
                        stage="envelope",
                        code="protocol_shape",
                        telemetry=telemetry,
                    )
                index = _optional_int(choice.get("index")) or 0
                state = states.setdefault(
                    index,
                    {
                        "content": [],
                        "reasoning_length": 0,
                        "refusal": False,
                        "finish_reason": None,
                    },
                )
                delta = _mapping_or_none(choice.get("delta")) or {}
                content, block_refusal = _content_text(delta.get("content"))
                if content:
                    state["content"].append(content)
                state["refusal"] = bool(
                    state["refusal"]
                    or block_refusal
                    or _flatten_diagnostic_text(delta.get("refusal")).strip()
                )
                state["reasoning_length"] += sum(
                    len(_flatten_diagnostic_text(delta.get(field_name)))
                    for field_name in _REASONING_FIELDS
                    if delta.get(field_name) is not None
                )
                if choice.get("finish_reason") is not None:
                    state["finish_reason"] = choice.get("finish_reason")
    except Exception as exc:
        if isinstance(exc, LLMCompatibilityError):
            if exc.telemetry is None:
                exc.telemetry = telemetry
            raise
        classification = classify_exception(exc)
        telemetry.transport_status = (
            "failed" if classification.stage == "transport" else "completed"
        )
        telemetry.http_status = classification.http_status
        telemetry.request_id = classification.request_id
        telemetry.retry_after_seconds = classification.retry_after_seconds
        raise LLMCompatibilityError(
            f"streaming chat completion failed ({classification.code})",
            stage=classification.stage,
            code=classification.code,
            retryable=classification.retryable,
            telemetry=telemetry,
        ) from exc

    telemetry.response_sha256 = response_hasher.hexdigest()
    if any(state["finish_reason"] is None for state in states.values()):
        raise LLMCompatibilityError(
            "provider stream ended without a terminal finish reason",
            stage="extraction",
            code="incomplete_output",
            telemetry=telemetry,
        )
    choices = []
    for index, state in sorted(states.items()):
        message: dict[str, Any] = {"content": "".join(state["content"])}
        if state["reasoning_length"]:
            # Preserve only the observed length for the shared reasoning-only
            # check. The actual reasoning text is deliberately discarded.
            message["reasoning_content"] = "x" * state["reasoning_length"]
        if state["refusal"]:
            message["refusal"] = "stream_refusal"
        choices.append(
            {
                "index": index,
                "message": message,
                "finish_reason": state["finish_reason"],
            }
        )
    return _extract_final_text({"choices": choices, "usage": usage}, telemetry)


def extract_single_json_object(content: str) -> dict[str, Any]:
    """Extract exactly one JSON object from final assistant text.

    Pure JSON and a complete JSON fence are preferred.  A unique root object
    surrounded by short, non-structural prose is accepted for providers that
    insist on a template sentence.  Multiple root objects are always rejected;
    the parser never guesses which one the model intended.
    """

    stripped = content.strip()
    if not stripped:
        raise LLMCompatibilityError(
            "assistant final text is empty",
            stage="contract",
            code="contract_invalid_json",
        )

    fence = _JSON_FENCE.fullmatch(stripped)
    candidate_text = fence.group(1).strip() if fence else stripped
    decoder = json.JSONDecoder()

    try:
        value, end = decoder.raw_decode(candidate_text)
    except JSONDecodeError:
        value = None
        end = 0
    else:
        remainder = candidate_text[end:].strip()
        if not remainder:
            if not isinstance(value, dict):
                raise LLMCompatibilityError(
                    "summary JSON root must be an object",
                    stage="contract",
                    code="contract_shape",
                )
            return value
        if _starts_with_json_value(remainder):
            raise LLMCompatibilityError(
                "assistant text contains multiple JSON values",
                stage="contract",
                code="contract_multiple_json",
            )

    candidates = _maximal_json_objects(candidate_text, decoder)
    if len(candidates) > 1:
        raise LLMCompatibilityError(
            "assistant text contains multiple JSON objects",
            stage="contract",
            code="contract_multiple_json",
        )
    if not candidates:
        raise LLMCompatibilityError(
            "assistant text does not contain a valid JSON object",
            stage="contract",
            code="contract_invalid_json",
        )

    start, end, value = candidates[0]
    prefix = candidate_text[:start].strip()
    suffix = candidate_text[end:].strip()
    if not _is_safe_json_affix(prefix) or not _is_safe_json_affix(suffix):
        raise LLMCompatibilityError(
            "assistant JSON has an unsafe or ambiguous prefix/suffix",
            stage="contract",
            code="contract_invalid_json",
        )
    return value


def _decode_response_document(
    raw_text: str, telemetry: CompletionTelemetry
) -> dict[str, Any]:
    if telemetry.content_type and not _JSON_CONTENT_TYPE.search(telemetry.content_type):
        raise LLMCompatibilityError(
            "provider returned a non-JSON Content-Type",
            stage="envelope",
            code="protocol_wrong_content_type",
            telemetry=telemetry,
        )

    stripped = raw_text.lstrip()
    decoder = json.JSONDecoder()
    try:
        value, end = decoder.raw_decode(stripped)
    except JSONDecodeError as exc:
        raise LLMCompatibilityError(
            "provider response is not valid JSON",
            stage="envelope",
            code="protocol_invalid_json",
            telemetry=telemetry,
        ) from exc

    remainder = stripped[end:].strip()
    if remainder:
        code = (
            "protocol_multi_document"
            if _starts_with_json_value(remainder)
            else "protocol_invalid_json"
        )
        raise LLMCompatibilityError(
            "provider returned more than one response document"
            if code == "protocol_multi_document"
            else "provider response has trailing non-JSON data",
            stage="envelope",
            code=code,
            telemetry=telemetry,
        )
    if not isinstance(value, dict):
        raise LLMCompatibilityError(
            "provider response root must be a JSON object",
            stage="envelope",
            code="protocol_shape",
            telemetry=telemetry,
        )
    return value


def _extract_final_text(
    document: Mapping[str, Any], telemetry: CompletionTelemetry
) -> CompletionResult:
    provider_error = _mapping_or_none(document.get("error"))
    if provider_error is not None and "choices" not in document:
        error_text = _flatten_diagnostic_text(provider_error).lower()
        if _contains_any(error_text, "no provider supported", "provider unavailable"):
            code = "provider_unavailable"
        elif _contains_any(error_text, "rate limit", "quota"):
            code = "rate_limit"
        else:
            code = "provider_error"
        raise LLMCompatibilityError(
            f"provider returned an error envelope ({code})",
            stage="http",
            code=code,
            retryable=code in {"rate_limit", "provider_error"},
            telemetry=telemetry,
        )

    choices = document.get("choices")
    if "choices" not in document:
        raise LLMCompatibilityError(
            "provider response is missing choices",
            stage="extraction",
            code="missing_choices",
            telemetry=telemetry,
        )
    if choices is None or choices == []:
        telemetry.choices_count = 0
        raise LLMCompatibilityError(
            "provider returned no choices",
            stage="extraction",
            code="empty_choices",
            retryable=True,
            telemetry=telemetry,
        )
    if not isinstance(choices, (list, tuple)):
        raise LLMCompatibilityError(
            "provider choices must be an array",
            stage="envelope",
            code="protocol_shape",
            telemetry=telemetry,
        )

    telemetry.choices_count = len(choices)
    choice = _mapping_or_none(choices[0])
    if choice is None:
        raise LLMCompatibilityError(
            "provider choice must be an object",
            stage="envelope",
            code="protocol_shape",
            telemetry=telemetry,
        )

    telemetry.finish_reason = _optional_text(choice.get("finish_reason"))
    _extract_usage(document.get("usage"), telemetry)
    if telemetry.finish_reason in {"length", "max_tokens", "max_output_tokens"}:
        raise LLMCompatibilityError(
            "provider stopped because the output limit was reached",
            stage="extraction",
            code="incomplete_output",
            telemetry=telemetry,
        )
    if telemetry.finish_reason in {"content_filter", "safety", "blocked"}:
        raise LLMCompatibilityError(
            "provider blocked the completion",
            stage="extraction",
            code="refusal",
            telemetry=telemetry,
        )

    if "message" not in choice or choice.get("message") is None:
        raise LLMCompatibilityError(
            "provider choice is missing an assistant message",
            stage="extraction",
            code="missing_message",
            telemetry=telemetry,
        )
    message = _mapping_or_none(choice.get("message"))
    if message is None:
        raise LLMCompatibilityError(
            "provider assistant message must be an object",
            stage="envelope",
            code="protocol_shape",
            telemetry=telemetry,
        )

    telemetry.reasoning_length = sum(
        len(_flatten_diagnostic_text(message.get(field_name)))
        for field_name in _REASONING_FIELDS
        if message.get(field_name) is not None
    ) + sum(
        len(_flatten_diagnostic_text(choice.get(field_name)))
        for field_name in _REASONING_FIELDS
        if choice.get(field_name) is not None
    )
    refusal = _flatten_diagnostic_text(message.get("refusal")).strip()
    if refusal:
        raise LLMCompatibilityError(
            "provider returned a refusal instead of final text",
            stage="extraction",
            code="refusal",
            telemetry=telemetry,
        )

    try:
        content, block_refusal = _content_text(message.get("content"))
    except LLMCompatibilityError as exc:
        exc.telemetry = telemetry
        raise
    if block_refusal:
        raise LLMCompatibilityError(
            "provider returned a refusal content block",
            stage="extraction",
            code="refusal",
            telemetry=telemetry,
        )
    telemetry.content_length = len(content)
    if not content.strip():
        code = "reasoning_only" if telemetry.reasoning_length else "empty_content"
        raise LLMCompatibilityError(
            "provider returned reasoning without final text"
            if code == "reasoning_only"
            else "provider returned empty final text",
            stage="extraction",
            code=code,
            telemetry=telemetry,
        )
    telemetry.final_text_received = True
    return CompletionResult(content=content, telemetry=telemetry)


def _content_text(content: Any) -> tuple[str, bool]:
    if content is None:
        return "", False
    if isinstance(content, str):
        return content, False
    if isinstance(content, Mapping):
        content = [content]
    if not isinstance(content, (list, tuple)):
        raise LLMCompatibilityError(
            "provider returned an unsupported message content shape",
            stage="extraction",
            code="unsupported_content",
        )

    parts: list[str] = []
    refusal = False
    for raw_block in content:
        if isinstance(raw_block, str):
            parts.append(raw_block)
            continue
        block = _mapping_or_none(raw_block)
        if block is None:
            continue
        block_type = str(block.get("type") or "").lower()
        if block_type in {"refusal", "safety"} or block.get("refusal"):
            refusal = True
            continue
        text = block.get("text")
        if isinstance(text, Mapping):
            text = text.get("value") or text.get("text")
        if isinstance(text, str) and (
            not block_type or block_type in {"text", "output_text"}
        ):
            parts.append(text)
    return "".join(parts), refusal


def _extract_usage(value: Any, telemetry: CompletionTelemetry) -> None:
    usage = _mapping_or_none(value)
    if usage is None:
        return
    telemetry.prompt_tokens = _optional_int(usage.get("prompt_tokens"))
    telemetry.completion_tokens = _optional_int(usage.get("completion_tokens"))
    telemetry.total_tokens = _optional_int(usage.get("total_tokens"))
    completion_details = _mapping_or_none(usage.get("completion_tokens_details"))
    if completion_details:
        telemetry.reasoning_tokens = _optional_int(
            completion_details.get("reasoning_tokens")
        )


def _raw_response_text(response: Any) -> str:
    text = getattr(response, "text", None)
    if callable(text):
        text = text()
    if isinstance(text, str):
        return text
    content = getattr(response, "content", b"")
    if callable(content):
        content = content()
    if isinstance(content, bytes):
        return content.decode("utf-8", errors="replace")
    return str(content or "")


def _to_plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _to_plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_plain(item) for item in value]
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return _to_plain(model_dump(mode="json"))
    if hasattr(value, "__dict__"):
        return {
            key: _to_plain(item)
            for key, item in vars(value).items()
            if not key.startswith("_")
        }
    return value


def _mapping_or_none(value: Any) -> dict[str, Any] | None:
    plain = _to_plain(value)
    return dict(plain) if isinstance(plain, Mapping) else None


def _flatten_diagnostic_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        return "".join(_flatten_diagnostic_text(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return "".join(_flatten_diagnostic_text(item) for item in value)
    return str(value)


def _maximal_json_objects(
    text: str, decoder: json.JSONDecoder
) -> list[tuple[int, int, dict[str, Any]]]:
    candidates: list[tuple[int, int, dict[str, Any]]] = []
    for start, character in enumerate(text):
        if character != "{":
            continue
        try:
            value, relative_end = decoder.raw_decode(text[start:])
        except JSONDecodeError:
            continue
        if isinstance(value, dict):
            candidates.append((start, start + relative_end, value))

    maximal = []
    for candidate in candidates:
        start, end, _value = candidate
        if any(
            other_start <= start
            and end <= other_end
            and (other_start, other_end) != (start, end)
            for other_start, other_end, _other_value in candidates
        ):
            continue
        maximal.append(candidate)
    return sorted(maximal, key=lambda item: item[0])


def _is_safe_json_affix(value: str) -> bool:
    if not value:
        return True
    if len(value) > _SAFE_AFFIX_MAX_CHARS:
        return False
    return not any(character in value for character in "{}[]<>")


def _starts_with_json_value(value: str) -> bool:
    stripped = value.lstrip()
    if not stripped:
        return False
    try:
        json.JSONDecoder().raw_decode(stripped)
    except JSONDecodeError:
        return False
    return True


def _header_value(headers: Any, name: str) -> str | None:
    if headers is None:
        return None
    getter = getattr(headers, "get", None)
    if callable(getter):
        value = getter(name)
        if value is None:
            value = getter(name.title())
        return _optional_text(value)
    return None


def _normalized_content_type(value: str | None) -> str | None:
    if value is None:
        return None
    return value.split(";", 1)[0].strip().lower() or None


def _optional_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _retry_after_seconds(exc: Exception) -> float | None:
    """Parse a provider Retry-After hint without persisting response headers."""

    response = getattr(exc, "response", None)
    value = _header_value(getattr(response, "headers", None), "retry-after")
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        try:
            retry_at = parsedate_to_datetime(value)
        except (TypeError, ValueError, OverflowError):
            return None
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=timezone.utc)
        return max(0.0, (retry_at - datetime.now(timezone.utc)).total_seconds())


def _looks_like_timeout(exc: Exception, message: str) -> bool:
    exception_name = type(exc).__name__.lower()
    return (
        isinstance(exc, TimeoutError)
        or "timeout" in exception_name
        or _contains_any(message, "timed out", "timeout error")
    )


def _contains_any(value: str, *needles: str) -> bool:
    return any(needle in value for needle in needles)
