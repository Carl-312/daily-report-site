"""Reader-safe diagnostics for non-blocking daily-report stage failures."""

from __future__ import annotations

import re
from typing import Any, Iterable


_SAFE_CODE = re.compile(r"[^a-zA-Z0-9_.-]+")


def _safe_code(value: Any, fallback: str = "unknown_error") -> str:
    normalized = _SAFE_CODE.sub("_", str(value or "").strip()).strip("_.-")
    return normalized[:80] or fallback


def collect_pipeline_diagnostics(
    *,
    source_results: Iterable[Any] = (),
    enrichment_report: dict[str, Any] | None = None,
    summary_result: Any | None = None,
) -> dict[str, Any]:
    """Collect only stable codes; raw exception messages never reach the page."""

    counts: dict[tuple[str, str], int] = {}

    def add(stage: str, code: Any, count: int = 1) -> None:
        key = (_safe_code(stage, "unknown_stage"), _safe_code(code))
        counts[key] = counts.get(key, 0) + max(1, int(count or 1))

    for result in source_results:
        if getattr(result, "status", "") not in {"failed", "degraded"}:
            continue
        stage = f"fetch.{getattr(result, 'source', 'unknown')}"
        diagnostic_codes = [
            getattr(diagnostic, "code", "")
            for diagnostic in getattr(result, "diagnostics", ())
            if getattr(diagnostic, "code", "")
            and not str(getattr(diagnostic, "code", "")).endswith("_snapshot")
        ]
        if diagnostic_codes:
            for code in diagnostic_codes:
                add(stage, code)
        else:
            add(stage, getattr(result, "error_kind", None) or "source_degraded")

    for failure in (enrichment_report or {}).get("stage_failures", []) or []:
        if not isinstance(failure, dict):
            continue
        add(
            f"enrichment.{failure.get('stage') or 'unknown'}",
            failure.get("code"),
            int(failure.get("count") or 1),
        )

    for attempt in getattr(summary_result, "attempts", ()) if summary_result else ():
        if getattr(attempt, "status", "") != "failed":
            continue
        provider = _safe_code(getattr(attempt, "provider", "provider"))
        add(
            f"summary.{provider}",
            getattr(attempt, "error_kind", None) or "provider_failed",
        )

    failures = [
        {"stage": stage, "code": code, "count": count}
        for (stage, code), count in sorted(counts.items())
    ]
    return {"status": "degraded" if failures else "ok", "failures": failures}


def render_pipeline_diagnostics_markdown(diagnostics: dict[str, Any]) -> str:
    """Render a compact footer that is useful for debugging but leaks no details."""

    failures = diagnostics.get("failures", []) or []
    lines = ["---", "", "## 运行诊断"]
    if not failures:
        lines.append("- 非阻塞阶段：`OK`")
        return "\n".join(lines)
    lines.append("以下仅显示稳定错误码；详细堆栈保留在本次运行日志中。")
    for failure in failures:
        count = int(failure.get("count") or 1)
        suffix = f" ×{count}" if count > 1 else ""
        lines.append(
            f"- `{_safe_code(failure.get('stage'))}`："
            f"`{_safe_code(failure.get('code'))}`{suffix}"
        )
    return "\n".join(lines)
