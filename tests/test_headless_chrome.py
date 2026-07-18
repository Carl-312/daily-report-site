from __future__ import annotations

from types import SimpleNamespace

import utils.headless_chrome as chrome


def test_renderer_uses_one_sandboxed_dump_dom_process(monkeypatch, tmp_path) -> None:
    binary = tmp_path / "google-chrome"
    binary.write_text("fixture", encoding="utf-8")
    binary.chmod(0o700)
    monkeypatch.setenv("AGIHUNT_TRENDING_CHROME_BIN", str(binary))
    calls: list[tuple[list[str], dict]] = []

    def run(arguments, **kwargs):
        calls.append((arguments, kwargs))
        if "--version" in arguments:
            return SimpleNamespace(
                returncode=0,
                stdout="Google Chrome 150.0.0.0\n",
                stderr="",
            )
        return SimpleNamespace(
            returncode=0,
            stdout=b"<html><main>rendered</main></html>",
            stderr=b"",
        )

    monkeypatch.setattr(chrome.subprocess, "run", run)

    result = chrome.render_page_dom("https://agihunt.info/?day=2026-07-18")

    assert result.chrome_version == "Google Chrome 150.0.0.0"
    assert result.html == "<html><main>rendered</main></html>"
    render_calls = [call for call in calls if "--dump-dom" in call[0]]
    assert len(render_calls) == 1
    arguments, kwargs = render_calls[0]
    assert "--headless" in arguments
    assert "--no-sandbox" not in arguments
    assert arguments[-1] == "https://agihunt.info/?day=2026-07-18"
    assert kwargs.get("shell") is None
