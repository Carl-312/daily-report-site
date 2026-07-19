"""Strict, additive contracts for daily-run facts and manifests.

This module intentionally does not participate in the legacy pipeline yet.  It
provides deterministic data structures that later phases can wire into staged
publication without changing today's public output paths.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, model_validator

StageStatus = Literal["ok", "degraded", "failed", "skipped"]
SourceStatus = Literal["ok", "empty", "degraded", "failed"]
PublicationStatus = Literal["pending", "published", "blocked", "not_attempted"]

_SENSITIVE_KEY = re.compile(r"key|secret|token|password", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class RunClock:
    """A single immutable current-time snapshot for one daily run."""

    timezone_name: str
    started_at: datetime
    cutoff_at: datetime
    deadline_at: datetime

    @classmethod
    def create(
        cls,
        timezone_name: str,
        *,
        now: datetime | None = None,
        deadline_duration: timedelta = timedelta(minutes=20),
    ) -> "RunClock":
        if deadline_duration < timedelta(0):
            raise ValueError("deadline_duration must not be negative")
        try:
            timezone = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"unknown IANA timezone: {timezone_name}") from exc

        if now is None:
            now = datetime.now(timezone)
        elif now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("RunClock now must be timezone-aware")
        else:
            now = now.astimezone(timezone)

        return cls(
            timezone_name=timezone_name,
            started_at=now,
            cutoff_at=now,
            deadline_at=now + deadline_duration,
        )

    @property
    def report_date(self) -> date:
        return self.cutoff_at.date()

    @property
    def report_date_ymd(self) -> str:
        return self.report_date.isoformat()

    @property
    def report_date_cn(self) -> str:
        return (
            f"{self.report_date.year}年{self.report_date.month:02d}月"
            f"{self.report_date.day:02d}日"
        )

    def remaining_seconds(self, now: datetime | None = None) -> float:
        """Return the remaining run budget from the immutable deadline."""
        current = now or datetime.now(self.started_at.tzinfo)
        if current.tzinfo is None or current.utcoffset() is None:
            raise ValueError("RunClock now must be timezone-aware")
        return (
            self.deadline_at - current.astimezone(self.deadline_at.tzinfo)
        ).total_seconds()

    def require_time(self, stage: str, now: datetime | None = None) -> float:
        """Fail closed once a stage reaches the run deadline."""
        remaining = self.remaining_seconds(now)
        if remaining <= 0:
            raise RunDeadlineExceeded(f"run deadline exceeded before or during {stage}")
        return remaining

    def bounded_timeout(
        self,
        requested_seconds: float,
        stage: str,
        now: datetime | None = None,
    ) -> float:
        """Bound one network timeout by the remaining run budget."""
        if requested_seconds <= 0:
            raise ValueError("requested_seconds must be positive")
        return min(float(requested_seconds), self.require_time(stage, now))


class RunDeadlineExceeded(TimeoutError):
    """The current run cannot start another bounded stage operation."""


class StrictFrozenModel(BaseModel):
    """Persisted records reject schema drift and cannot be reassigned."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class Diagnostic(StrictFrozenModel):
    code: str
    message: str
    details: tuple[tuple[str, str], ...] = ()


class ArticleSnapshot(StrictFrozenModel):
    title: str
    link: str
    description: str = ""
    publish_time: str = ""
    content: str = ""
    priority: int = 0
    source: str = ""
    kind: str = "story"
    evidence_status: str = "direct"
    confidence: str = "reported"
    provenance: dict[str, str] = Field(default_factory=dict)


class StageResult(StrictFrozenModel):
    name: str
    status: StageStatus
    started_at: datetime
    finished_at: datetime | None = None
    duration_ms: int | None = Field(default=None, ge=0)
    diagnostics: tuple[Diagnostic, ...] = ()

    @model_validator(mode="after")
    def validate_timestamps(self) -> "StageResult":
        _require_aware(self.started_at, "started_at")
        if self.finished_at is not None:
            _require_aware(self.finished_at, "finished_at")
            if self.finished_at < self.started_at:
                raise ValueError("finished_at must not precede started_at")
        return self


class SourceRunResult(StrictFrozenModel):
    source: str
    status: SourceStatus
    attempts: int = Field(ge=0)
    duration_ms: int = Field(ge=0)
    fetched_count: int = Field(ge=0)
    accepted_count: int = Field(ge=0)
    error_kind: str | None = None
    error_message: str | None = None
    articles: tuple[ArticleSnapshot, ...] = ()
    diagnostics: tuple[Diagnostic, ...] = ()

    @model_validator(mode="after")
    def validate_outcome(self) -> "SourceRunResult":
        if self.accepted_count > self.fetched_count:
            raise ValueError("accepted_count must not exceed fetched_count")
        has_error = bool(self.error_kind or self.error_message)
        if self.status == "empty" and (
            self.fetched_count != 0 or self.accepted_count != 0 or has_error
        ):
            raise ValueError("empty sources must have zero counts and no error")
        if self.status == "ok" and has_error:
            raise ValueError("ok sources must not carry an error")
        if self.status in {"degraded", "failed"} and not (
            self.error_kind or self.diagnostics
        ):
            raise ValueError("degraded or failed sources need an error or diagnostic")
        return self


class ArtifactHash(StrictFrozenModel):
    name: str
    algorithm: Literal["sha256"] = "sha256"
    digest: str | None = None


class PublicationState(StrictFrozenModel):
    status: PublicationStatus = "pending"
    published_run_id: str | None = None
    previous_published_run_id: str | None = None
    reason: str | None = None


class DailyRunManifest(StrictFrozenModel):
    schema_version: Literal[1] = 1
    run_id: str
    report_date: date
    timezone: str
    started_at: datetime
    cutoff_at: datetime
    deadline_at: datetime
    config_fingerprint: str
    config_snapshot: str
    stages: tuple[StageResult, ...] = ()
    sources: tuple[SourceRunResult, ...] = ()
    artifacts: tuple[ArtifactHash, ...] = ()
    publication: PublicationState = Field(default_factory=PublicationState)
    diagnostics: tuple[Diagnostic, ...] = ()

    @model_validator(mode="after")
    def validate_clock(self) -> "DailyRunManifest":
        _require_aware(self.started_at, "started_at")
        _require_aware(self.cutoff_at, "cutoff_at")
        _require_aware(self.deadline_at, "deadline_at")
        if not self.started_at <= self.cutoff_at <= self.deadline_at:
            raise ValueError(
                "manifest clock must satisfy started <= cutoff <= deadline"
            )
        return self


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def redact_sensitive(value: Any) -> Any:
    """Recursively omit secret-bearing fields from JSON-compatible data."""
    if hasattr(value, "model_dump"):
        return redact_sensitive(value.model_dump(mode="json"))
    if isinstance(value, dict):
        return {
            str(key): redact_sensitive(item)
            for key, item in value.items()
            if not _SENSITIVE_KEY.search(str(key))
        }
    if isinstance(value, list):
        return [redact_sensitive(item) for item in value]
    if isinstance(value, tuple):
        return [redact_sensitive(item) for item in value]
    return value


def canonical_json_bytes(value: Any) -> bytes:
    """Encode a JSON-compatible value into stable UTF-8 bytes."""
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def fingerprint_settings(settings: Any) -> tuple[dict[str, Any], str]:
    """Return a redacted settings snapshot and its deterministic SHA-256 hash."""
    raw_settings = (
        settings.model_dump(mode="json")
        if hasattr(settings, "model_dump")
        else vars(settings)
    )
    snapshot = redact_sensitive(raw_settings)
    if not isinstance(snapshot, dict):
        raise TypeError("settings snapshot must be a mapping")
    digest = hashlib.sha256(canonical_json_bytes(snapshot)).hexdigest()
    return snapshot, digest


def scrub_diagnostic(message: str, settings: Any) -> str:
    """Remove known configured secret values from a diagnostic message."""
    raw_settings = (
        settings.model_dump(mode="json")
        if hasattr(settings, "model_dump")
        else vars(settings)
    )
    values = _sensitive_values(raw_settings)
    safe_message = message
    for value in values:
        if value:
            safe_message = safe_message.replace(value, "[redacted]")
    return safe_message


def _sensitive_values(value: Any) -> tuple[str, ...]:
    values: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if _SENSITIVE_KEY.search(str(key)) and isinstance(item, str):
                values.append(item)
            else:
                values.extend(_sensitive_values(item))
    elif isinstance(value, (list, tuple)):
        for item in value:
            values.extend(_sensitive_values(item))
    return tuple(values)


def new_manifest(
    settings: Any,
    clock: RunClock,
    *,
    run_id_factory: Callable[[], str] | None = None,
) -> DailyRunManifest:
    """Build a pending manifest without changing current runtime behavior."""
    snapshot, fingerprint = fingerprint_settings(settings)
    return DailyRunManifest(
        run_id=(run_id_factory or (lambda: uuid.uuid4().hex))(),
        report_date=clock.report_date,
        timezone=clock.timezone_name,
        started_at=clock.started_at,
        cutoff_at=clock.cutoff_at,
        deadline_at=clock.deadline_at,
        config_fingerprint=fingerprint,
        config_snapshot=canonical_json_bytes(snapshot).decode("utf-8"),
    )


def write_manifest(path: str | Path, manifest: DailyRunManifest) -> Path:
    """Persist a validated manifest atomically for recovery and diagnosis."""
    from utils.storage import atomic_write_bytes

    return atomic_write_bytes(
        path,
        canonical_json_bytes(manifest.model_dump(mode="json")) + b"\n",
    )


def read_manifest(path: str | Path) -> DailyRunManifest:
    """Load a manifest and reject schema drift or malformed data."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return DailyRunManifest.model_validate(data)
