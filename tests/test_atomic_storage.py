from __future__ import annotations

import json

import pytest

from utils import storage


def test_atomic_write_replaces_existing_file_without_temp_residue(tmp_path) -> None:
    target = tmp_path / "report.json"
    target.write_text("old", encoding="utf-8")

    assert storage.atomic_write_text(target, "new") == target
    assert target.read_text(encoding="utf-8") == "new"
    assert list(tmp_path.glob(".report.json.*")) == []


def test_atomic_write_preserves_previous_file_when_replace_fails(
    tmp_path, monkeypatch
) -> None:
    target = tmp_path / "report.json"
    target.write_text("last-known-good", encoding="utf-8")

    def fail_replace(source, destination) -> None:
        raise OSError("simulated promotion failure")

    monkeypatch.setattr(storage.os, "replace", fail_replace)
    with pytest.raises(OSError, match="simulated promotion failure"):
        storage.atomic_write_text(target, "new candidate")

    assert target.read_text(encoding="utf-8") == "last-known-good"
    assert list(tmp_path.glob(".report.json.*")) == []


def test_json_and_markdown_saves_use_atomic_writer(tmp_path) -> None:
    json_path = storage.save_json(str(tmp_path), "2026-07-10", {"articles": []})
    markdown_path = storage.save_markdown(str(tmp_path), "2026-07-10", "body")

    assert json.loads(json_path.read_text(encoding="utf-8")) == {"articles": []}
    assert markdown_path.read_text(encoding="utf-8").endswith("body")
