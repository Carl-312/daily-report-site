from __future__ import annotations

from types import SimpleNamespace

from scripts.modelscope_smoke import classify_failure, run_smoke


def _config(**overrides):
    values = {
        "api_base_url": "https://api-inference.modelscope.cn/v1",
        "api_key": "test-secret",
        "model": "ZhipuAI/GLM-5.2",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _client_with_choices(*contents: str):
    choices = [
        SimpleNamespace(
            message=SimpleNamespace(content=content),
            finish_reason="stop",
        )
        for content in contents
    ]
    response = SimpleNamespace(choices=choices)
    return SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=lambda **_params: response)
        )
    )


def test_smoke_requires_non_empty_choice_and_content() -> None:
    output: list[str] = []

    exit_code = run_smoke(
        cfg=_config(),
        client_factory=lambda *_args, **_kwargs: _client_with_choices("OK"),
        emit=output.append,
    )

    assert exit_code == 0
    assert output[-1] == (
        "ModelScope smoke succeeded: choices=1 content_length=2 "
        "reasoning_length=0 finish_reason=stop"
    )


def test_smoke_rejects_empty_choices() -> None:
    output: list[str] = []

    exit_code = run_smoke(
        cfg=_config(),
        client_factory=lambda *_args, **_kwargs: _client_with_choices(),
        emit=output.append,
    )

    assert exit_code == 1
    assert output[-1].endswith(
        "stage=extraction category=empty_choices type=LLMCompatibilityError"
    )


def test_smoke_never_prints_the_api_key_from_an_exception() -> None:
    output: list[str] = []

    def fail(*_args, **_kwargs):
        raise RuntimeError("request failed with test-secret")

    exit_code = run_smoke(
        cfg=_config(),
        client_factory=fail,
        emit=output.append,
    )

    assert exit_code == 1
    assert "test-secret" not in "\n".join(output)
    assert "category=network_unknown" in output[-1]


def test_failure_classifier_distinguishes_provider_unavailable() -> None:
    error = RuntimeError("model has no provider supported")
    error.status_code = 400

    assert classify_failure(error) == "provider_unavailable"
