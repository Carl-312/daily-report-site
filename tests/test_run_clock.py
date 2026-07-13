from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from utils.run_contracts import RunClock


def test_clock_derives_every_report_date_from_one_aware_instant() -> None:
    clock = RunClock.create(
        "Asia/Shanghai",
        now=datetime(2026, 7, 10, 16, 1, tzinfo=timezone.utc),
        deadline_duration=timedelta(minutes=15),
    )

    assert clock.report_date_ymd == "2026-07-11"
    assert clock.report_date_cn == "2026年07月11日"
    assert clock.cutoff_at == clock.started_at
    assert clock.deadline_at - clock.started_at == timedelta(minutes=15)


def test_clock_rejects_invalid_or_ambiguous_input() -> None:
    with pytest.raises(ValueError, match="unknown IANA timezone"):
        RunClock.create("not/a-zone")
    with pytest.raises(ValueError, match="timezone-aware"):
        RunClock.create("Asia/Shanghai", now=datetime(2026, 7, 10))
    with pytest.raises(ValueError, match="must not be negative"):
        RunClock.create("Asia/Shanghai", deadline_duration=timedelta(seconds=-1))


def test_clock_bounds_stage_timeouts_and_fails_after_deadline() -> None:
    started = datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc)
    clock = RunClock.create(
        "Asia/Shanghai",
        now=started,
        deadline_duration=timedelta(seconds=10),
    )

    before_deadline = datetime(2026, 7, 10, 12, 0, 5, tzinfo=timezone.utc)
    assert clock.remaining_seconds(before_deadline) == 5
    assert clock.bounded_timeout(30, "request", before_deadline) == 5

    after_deadline = datetime(2026, 7, 10, 12, 0, 11, tzinfo=timezone.utc)
    with pytest.raises(TimeoutError, match="deadline exceeded"):
        clock.require_time("request", after_deadline)
