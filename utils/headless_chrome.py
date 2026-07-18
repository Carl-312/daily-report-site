"""Small, dependency-free Headless Chrome DOM renderer."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from time import perf_counter
from urllib.parse import urlparse


class ChromeNotFoundError(RuntimeError):
    diagnostic_code = "headless_chrome_not_found"


class ChromeRenderError(RuntimeError):
    diagnostic_code = "headless_chrome_render_failed"


@dataclass(frozen=True, slots=True)
class RenderedDom:
    html: str
    chrome_version: str
    duration_ms: int


def resolve_chrome_binary(configured: str = "") -> str:
    """Resolve an explicit or runner-provided Chrome executable."""

    candidates = (
        os.getenv("AGIHUNT_TRENDING_CHROME_BIN", "").strip(),
        configured.strip(),
        "google-chrome",
        "google-chrome-stable",
        "chromium",
        "chromium-browser",
    )
    for candidate in candidates:
        if not candidate:
            continue
        if os.path.sep in candidate:
            path = Path(candidate).expanduser()
            if path.is_file() and os.access(path, os.X_OK):
                return str(path.resolve())
            continue
        if resolved := shutil.which(candidate):
            return resolved
    raise ChromeNotFoundError("no supported Chrome executable is available")


def read_chrome_version(binary: str) -> str:
    """Return a bounded, single-line browser version for diagnostics."""

    try:
        result = subprocess.run(
            [binary, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ChromeRenderError("unable to inspect Chrome version") from exc
    version = " ".join(result.stdout.split())
    if result.returncode != 0 or not version:
        raise ChromeRenderError("Chrome version probe failed")
    return version[:160]


def render_page_dom(
    url: str,
    *,
    configured_binary: str = "",
    language: str = "zh-CN",
    timeout_seconds: float = 30,
    virtual_time_budget_ms: int = 12000,
    max_dom_bytes: int = 2_000_000,
    deadline_at: datetime | None = None,
) -> RenderedDom:
    """Render one HTTPS page and return its post-JavaScript serialized DOM."""

    parsed_url = urlparse(url)
    if parsed_url.scheme != "https" or not parsed_url.netloc:
        raise ValueError("Headless Chrome renderer only accepts HTTPS URLs")

    binary = resolve_chrome_binary(configured_binary)
    version = read_chrome_version(binary)
    remaining = float(timeout_seconds)
    if deadline_at is not None:
        from utils.run_contracts import RunDeadlineExceeded

        remaining = min(
            remaining,
            (deadline_at - datetime.now(deadline_at.tzinfo)).total_seconds(),
        )
        if remaining <= 0:
            raise RunDeadlineExceeded(
                "run deadline exceeded before Headless Chrome rendering"
            )

    major_match = re.search(r"\b(\d+)\.", version)
    chrome_major = major_match.group(1) if major_match else "120"
    user_agent = (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        f"(KHTML, like Gecko) Chrome/{chrome_major}.0.0.0 Safari/537.36 "
        "daily-report-site-agihunt-trending/1.0"
    )

    environment = dict(os.environ)
    environment["LANG"] = "zh_CN.UTF-8" if language == "zh-CN" else "en_US.UTF-8"
    started = perf_counter()
    try:
        with tempfile.TemporaryDirectory(prefix="daily-report-chrome-") as profile:
            result = subprocess.run(
                [
                    binary,
                    "--headless",
                    "--disable-gpu",
                    "--disable-dev-shm-usage",
                    "--disable-background-networking",
                    "--disable-component-update",
                    "--disable-features=Translate",
                    "--no-first-run",
                    "--no-default-browser-check",
                    f"--lang={language}",
                    f"--accept-lang={language},zh,en",
                    "--window-size=1440,1200",
                    f"--timeout={virtual_time_budget_ms}",
                    f"--virtual-time-budget={virtual_time_budget_ms}",
                    f"--user-agent={user_agent}",
                    f"--user-data-dir={profile}",
                    "--dump-dom",
                    url,
                ],
                env=environment,
                capture_output=True,
                timeout=remaining,
                check=False,
            )
    except subprocess.TimeoutExpired as exc:
        raise ChromeRenderError("Headless Chrome rendering timed out") from exc
    except OSError as exc:
        raise ChromeRenderError("Headless Chrome could not be started") from exc

    duration_ms = round((perf_counter() - started) * 1000)
    if result.returncode != 0:
        raise ChromeRenderError(
            f"Headless Chrome exited with status {result.returncode}"
        )
    if not result.stdout:
        raise ChromeRenderError("Headless Chrome returned an empty DOM")
    if len(result.stdout) > max_dom_bytes:
        raise ChromeRenderError("rendered DOM exceeded the configured size limit")

    return RenderedDom(
        html=result.stdout.decode("utf-8", errors="replace"),
        chrome_version=version,
        duration_ms=duration_ms,
    )
