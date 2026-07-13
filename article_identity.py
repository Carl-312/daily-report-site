"""Low-level article identity helpers with no package-level dependencies."""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


_norm_re = re.compile(r"[\s\-—_]+")
_title_punctuation_re = re.compile(r"[^\w\s\u4e00-\u9fff]+", re.UNICODE)
_tracking_param_re = re.compile(r"^(utm_|fbclid$|gclid$|ref$)", re.IGNORECASE)


def normalize_title(title: str) -> str:
    """Normalize an article title for identity comparisons."""
    normalized = _title_punctuation_re.sub(" ", (title or "").strip().lower())
    return _norm_re.sub(" ", normalized).strip()


def canonical_url(link: str) -> str:
    """Remove URL noise that should not create a second candidate."""
    try:
        parsed = urlsplit((link or "").strip())
    except ValueError:
        return ""
    if not parsed.scheme or not parsed.netloc:
        return ""

    query = urlencode(
        sorted(
            (key, value)
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if not _tracking_param_re.match(key)
        )
    )
    path = parsed.path.rstrip("/") or "/"
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), path, query, ""))
