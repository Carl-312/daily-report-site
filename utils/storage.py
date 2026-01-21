"""
Storage utilities
Handles saving JSON data and Markdown files
"""
from __future__ import annotations
import os
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Any

# Beijing timezone
beijing_tz = timezone(timedelta(hours=8))


def today_ymd() -> str:
    """Get today's date in YYYY-MM-DD format (Beijing time)"""
    return datetime.now(beijing_tz).strftime('%Y-%m-%d')


def today_cn() -> str:
    """Get today's date in Chinese format"""
    d = datetime.now(beijing_tz)
    return f"{d.year}年{d.month:02d}月{d.day:02d}日"


def ensure_dir(path: str | Path) -> Path:
    """Ensure directory exists"""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def save_json(dir_path: str, date_str: str, data: Any) -> Path:
    """Save data as JSON file"""
    ensure_dir(dir_path)
    fp = Path(dir_path) / f'{date_str}.json'
    with open(fp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return fp


def load_json(dir_path: str, date_str: str) -> dict | None:
    """Load JSON file if exists"""
    fp = Path(dir_path) / f'{date_str}.json'
    if fp.exists():
        with open(fp, 'r', encoding='utf-8') as f:
            return json.load(f)
    return None


def save_markdown(dir_path: str, date_str: str, content: str) -> Path:
    """Save content as Markdown file with frontmatter"""
    ensure_dir(dir_path)
    fp = Path(dir_path) / f'{date_str}.md'
    
    # Add frontmatter
    frontmatter = f"""---
title: AI 新闻日报 {date_str}
date: {date_str}
---

"""
    with open(fp, 'w', encoding='utf-8') as f:
        f.write(frontmatter + content)
    
    return fp
