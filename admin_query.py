"""Shared helpers for the paged admin read models (library_admin.py and
requests_admin.py): LIKE-escaping, int clamping, the 'added' day windows,
and the page-clamping rule. Kept in one place so the two read models can't
drift on how they escape a search term, clamp an out-of-range int, or
decide which page to actually serve.
"""
from __future__ import annotations


def like_pattern(q: str) -> str:
    """Escape a search term for SQLite LIKE: backslash first (it is the
    escape character itself), then the two LIKE wildcards, so a literal
    `_` or `%` in a title or hash is matched literally rather than as a
    wildcard."""
    escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def clamp_int(value, default: int, lo: int, hi: int) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


ADDED_WINDOWS = {"24h": "-1 day", "7d": "-7 days", "30d": "-30 days"}


def effective_page(page: int, per_page: int, total: int) -> int:
    """The page a paged query should actually serve: the requested page,
    or the last real page once the requested one runs past the end of the
    result set (page 1 when there are no rows at all)."""
    if total <= 0:
        return 1
    last_page = -(-total // per_page)  # ceil division
    return min(page, last_page)
