"""The read model behind the admin Requests tab.

One SELECT over user_requests joined to users twice (requester and
reviewer) and left-joined to requests for the library status, wrapped so
views and filters reference the computed columns, plus a COUNT with the
same WHERE. Same shape as library_admin so the two rails behave alike.
"""
from __future__ import annotations

import db

VIEWS = ("pending", "approved", "denied", "all")
SORTS = {
    "created": "t.created_at",
    "reviewed": "t.reviewed_at",
    "user": "t.username COLLATE NOCASE",
    "title": "t.title COLLATE NOCASE",
}
MAX_PER_PAGE = 200
DEFAULT_PER_PAGE = 50

_BASE = """
SELECT ur.id, ur.imdb_id, ur.tmdb_id, ur.title, ur.media_type, ur.seasons, ur.status, ur.note,
       ur.created_at, ur.reviewed_at, ur.user_id, u.username, rv.username AS reviewer,
       r.status AS library_status
FROM user_requests ur
JOIN users u ON u.id = ur.user_id
LEFT JOIN users rv ON rv.id = ur.reviewed_by
LEFT JOIN requests r ON r.imdb_id = ur.imdb_id
"""

_VIEW_WHERE = {"all": "1=1", "pending": "t.status = 'pending'",
               "approved": "t.status = 'approved'", "denied": "t.status = 'denied'"}
_VIEW_ORDER = {"pending": "t.created_at ASC, t.id ASC"}
_ADDED = {"24h": "-1 day", "7d": "-7 days", "30d": "-30 days"}


def _like(q: str) -> str:
    q = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{q}%"


def _int(value, default: int, lo: int, hi: int) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


def _where(filters: dict) -> tuple[str, list]:
    clauses = [_VIEW_WHERE.get(filters.get("view") or "all", "0=1")]
    args: list = []
    user = filters.get("user")
    if user and str(user).isdigit():
        clauses.append("t.user_id = ?")
        args.append(int(user))
    kind = filters.get("type")
    if kind == "movie":
        clauses.append("t.media_type = 'movie'")
    elif kind == "series":
        clauses.append("t.media_type != 'movie'")
    added = _ADDED.get(filters.get("added") or "")
    if added:
        clauses.append("t.created_at >= datetime('now', ?)")
        args.append(added)
    q = (filters.get("q") or "").strip()
    if q:
        clauses.append("(t.title LIKE ? ESCAPE '\\' OR t.imdb_id LIKE ? ESCAPE '\\')")
        args += [_like(q), _like(q)]
    return " AND ".join(clauses), args


def _order(filters: dict) -> str:
    sort = filters.get("sort")
    if sort in SORTS:
        direction = "ASC" if (filters.get("order") or "").lower() == "asc" else "DESC"
        col = SORTS[sort]
        if sort == "reviewed":
            return f"{col} IS NULL, {col} {direction}, t.id DESC"
        return f"{col} {direction}, t.id DESC"
    return _VIEW_ORDER.get(filters.get("view") or "all", "t.created_at DESC, t.id DESC")


def list_requests(filters: dict) -> tuple[list[dict], int]:
    where, args = _where(filters)
    per_page = _int(filters.get("per_page"), DEFAULT_PER_PAGE, 1, MAX_PER_PAGE)
    page = _int(filters.get("page"), 1, 1, 10_000_000)
    with db._connect() as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM ({_BASE}) t WHERE {where}", args).fetchone()[0]
        rows = conn.execute(
            f"SELECT * FROM ({_BASE}) t WHERE {where} ORDER BY {_order(filters)} LIMIT ? OFFSET ?",
            args + [per_page, (page - 1) * per_page]).fetchall()
    return [dict(r) for r in rows], total


def view_counts() -> dict[str, int]:
    with db._connect() as conn:
        return {v: conn.execute(f"SELECT COUNT(*) FROM ({_BASE}) t WHERE {_VIEW_WHERE[v]}").fetchone()[0]
                for v in VIEWS}
