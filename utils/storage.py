"""
Storage utilities
Handles saving JSON data and Markdown files
"""

from __future__ import annotations
import json
import os
from pathlib import Path
import tempfile
from datetime import datetime, timezone, timedelta
from typing import Any

# Beijing timezone
beijing_tz = timezone(timedelta(hours=8))


def today_ymd(clock=None) -> str:
    """Get today's date in YYYY-MM-DD format (Beijing time)"""
    if clock is not None:
        return clock.report_date_ymd
    return datetime.now(beijing_tz).strftime("%Y-%m-%d")


def today_cn(clock=None) -> str:
    """Get today's date in Chinese format"""
    if clock is not None:
        return clock.report_date_cn
    d = datetime.now(beijing_tz)
    return f"{d.year}年{d.month:02d}月{d.day:02d}日"


def ensure_dir(path: str | Path) -> Path:
    """Ensure directory exists"""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def atomic_write_bytes(path: str | Path, content: bytes) -> Path:
    """Replace one file only after fully writing and syncing a sibling temp file."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, target)
        try:
            directory_fd = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            # Directory fsync is not available on every supported filesystem;
            # the file itself is still atomically replaced and synced.
            pass
        return target
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise


def atomic_write_text(path: str | Path, content: str) -> Path:
    """UTF-8 convenience wrapper around :func:`atomic_write_bytes`."""
    return atomic_write_bytes(path, content.encode("utf-8"))


def save_json(dir_path: str, date_str: str, data: Any) -> Path:
    """Save data as JSON file"""
    ensure_dir(dir_path)
    fp = Path(dir_path) / f"{date_str}.json"
    return atomic_write_text(fp, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def load_json(dir_path: str, date_str: str) -> dict | None:
    """Load JSON file if exists"""
    fp = Path(dir_path) / f"{date_str}.json"
    if fp.exists():
        with open(fp, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def save_markdown(dir_path: str, date_str: str, content: str) -> Path:
    """Save content as Markdown file with frontmatter"""
    ensure_dir(dir_path)
    fp = Path(dir_path) / f"{date_str}.md"

    # Add frontmatter
    frontmatter = f"""---
title: AI 新闻日报 {date_str}
date: {date_str}
---

"""
    return atomic_write_text(fp, frontmatter + content)
