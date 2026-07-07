from __future__ import annotations

from types import SimpleNamespace

import summarizer


def _llm_config(**overrides):
    cfg = {
        "api_key": "modelscope-key",
        "api_base_url": "https://modelscope.test/v1",
        "model": "ZhipuAI/GLM-5.2",
        "modelscope_secondary_model": "moonshotai/Kimi-K2.7-Code",
        "fallback_api_key": "siliconflow-key",
        "fallback_api_base_url": "https://siliconflow.test/v1",
        "fallback_model": "Pro/moonshotai/Kimi-K2.6",
        "max_output": 2000,
        "title_max": 150,
        "desc_max": 300,
        "prompt_path": "missing-prompt.md",
    }
    cfg.update(overrides)
    return SimpleNamespace(**cfg)


def test_provider_candidates_use_modelscope_secondary_before_siliconflow(
    monkeypatch,
) -> None:
    monkeypatch.setattr(summarizer, "get_config", _llm_config)

    providers = summarizer._provider_candidates()

    assert [
        (provider["name"], provider["base_url"], provider["model"])
        for provider in providers
    ] == [
        ("ModelScope", "https://modelscope.test/v1", "ZhipuAI/GLM-5.2"),
        (
            "ModelScope secondary",
            "https://modelscope.test/v1",
            "moonshotai/Kimi-K2.7-Code",
        ),
        ("SiliconFlow", "https://siliconflow.test/v1", "Pro/moonshotai/Kimi-K2.6"),
    ]


def test_provider_candidates_skip_duplicate_modelscope_model(monkeypatch) -> None:
    monkeypatch.setattr(
        summarizer,
        "get_config",
        lambda: _llm_config(
            modelscope_secondary_model="ZhipuAI/GLM-5.2",
            fallback_api_key="",
        ),
    )

    providers = summarizer._provider_candidates()

    assert [(provider["name"], provider["model"]) for provider in providers] == [
        ("ModelScope", "ZhipuAI/GLM-5.2")
    ]


def test_summarize_tries_modelscope_secondary_before_siliconflow(
    monkeypatch,
) -> None:
    monkeypatch.setattr(summarizer, "get_config", _llm_config)
    monkeypatch.setattr(summarizer, "load_prompt", lambda: "prompt")
    monkeypatch.setattr(
        summarizer,
        "create_client",
        lambda base_url, api_key: f"{base_url}|{api_key}",
    )
    calls: list[tuple[str, str]] = []

    def fake_summarize_sync(client, params):
        calls.append((client, params["model"]))
        if params["model"] == "moonshotai/Kimi-K2.7-Code":
            return "secondary model summary"
        raise RuntimeError("provider failed")

    monkeypatch.setattr(summarizer, "_summarize_sync", fake_summarize_sync)

    content = summarizer.summarize([{"title": "Story"}], stream=False)

    assert content == "secondary model summary"
    assert calls == [
        ("https://modelscope.test/v1|modelscope-key", "ZhipuAI/GLM-5.2"),
        (
            "https://modelscope.test/v1|modelscope-key",
            "moonshotai/Kimi-K2.7-Code",
        ),
    ]


def test_summarize_treats_empty_provider_response_as_failure(monkeypatch) -> None:
    monkeypatch.setattr(summarizer, "get_config", _llm_config)
    monkeypatch.setattr(summarizer, "load_prompt", lambda: "prompt")
    monkeypatch.setattr(
        summarizer,
        "create_client",
        lambda base_url, api_key: f"{base_url}|{api_key}",
    )
    calls: list[str] = []

    def fake_summarize_sync(client, params):
        calls.append(params["model"])
        if params["model"] == "ZhipuAI/GLM-5.2":
            return "  \n"
        return "fallback model summary"

    monkeypatch.setattr(summarizer, "_summarize_sync", fake_summarize_sync)

    content = summarizer.summarize([{"title": "Story"}], stream=False)

    assert content == "fallback model summary"
    assert calls == ["ZhipuAI/GLM-5.2", "moonshotai/Kimi-K2.7-Code"]


def test_offline_summary_preserves_full_title_and_link() -> None:
    content = summarizer.offline_summary(
        [
            {
                "title": (
                    "A very long AI funding headline that should stay readable "
                    "instead of being cut off"
                ),
                "link": "https://example.com/story",
                "priority": 1,
            }
        ],
        limit=1,
    )

    assert (
        "[🔥A very long AI funding headline that should stay readable "
        "instead of being cut off](https://example.com/story)"
    ) in content
