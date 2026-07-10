from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from config import Settings
from utils.run_contracts import (
    Diagnostic,
    RunClock,
    canonical_json_bytes,
    fingerprint_settings,
    new_manifest,
    read_manifest,
    scrub_diagnostic,
    write_manifest,
)


def _settings(**updates) -> Settings:
    defaults = {
        "api_key": "primary-secret",
        "fallback_api_key": "fallback-secret",
        "syft_secret_key": "syft-secret",
        "tavily_api_key": "tavily-secret",
        "sources": {"aibase": True},
    }
    defaults.update(updates)
    return Settings(**defaults)


def _clock() -> RunClock:
    return RunClock.create(
        "Asia/Shanghai", now=datetime(2026, 7, 10, 16, tzinfo=timezone.utc)
    )


def test_fingerprint_is_canonical_redacted_and_sensitive_to_non_secrets() -> None:
    one = _settings()
    two = _settings(api_key="other-primary", tavily_api_key="other-tavily")
    snapshot, first = fingerprint_settings(one)
    _, second = fingerprint_settings(two)

    serialized = canonical_json_bytes(snapshot).decode("utf-8")
    assert first == second
    for secret in ("primary-secret", "fallback-secret", "syft-secret", "tavily-secret"):
        assert secret not in serialized
    for secret_name in (
        "api_key",
        "fallback_api_key",
        "syft_secret_key",
        "tavily_api_key",
    ):
        assert secret_name not in serialized

    _, changed = fingerprint_settings(_settings(max_articles=99))
    assert changed != first


def test_manifest_round_trip_scrubs_diagnostics_and_is_strict(tmp_path) -> None:
    settings = _settings()
    manifest = new_manifest(settings, _clock(), run_id_factory=lambda: "fixed-run")
    safe = scrub_diagnostic("request used primary-secret", settings)
    manifest = manifest.model_copy(
        update={"diagnostics": (Diagnostic(code="network", message=safe),)}
    )
    path = write_manifest(tmp_path / "manifest.json", manifest)

    assert read_manifest(path) == manifest
    persisted = path.read_text(encoding="utf-8")
    assert "primary-secret" not in persisted
    assert "[redacted]" in persisted
    assert path.read_bytes().endswith(b"\n")

    data = json.loads(persisted)
    data["unknown"] = True
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValidationError):
        read_manifest(path)


def test_manifest_rejects_invalid_schema_status_and_naive_time(tmp_path) -> None:
    manifest = new_manifest(_settings(), _clock(), run_id_factory=lambda: "fixed-run")
    path = write_manifest(tmp_path / "manifest.json", manifest)
    data = json.loads(path.read_text(encoding="utf-8"))

    data["schema_version"] = 2
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValidationError):
        read_manifest(path)

    data["schema_version"] = 1
    data["started_at"] = "2026-07-10T00:00:00"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValidationError, match="timezone-aware"):
        read_manifest(path)
