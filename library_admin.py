"""The read model behind the admin Library tab.

One SELECT over requests with correlated subselects for everything the
table shows (requester, playability, missing episodes, retry queue, arr
mirror, TorBox), wrapped so filters and views can reference the computed
columns, plus a COUNT with the same WHERE. Views are named filter sets so
the rail counts and the table agree by construction.
"""
from __future__ import annotations

import arr_sync
import db

VIEWS = ("all", "attention", "wanted", "queue", "incomplete", "unmirrored")
PROBLEMS = ("failed", "wanted", "unplayable", "missing_episodes", "in_retry_queue", "no_requester", "not_mirrored")
STATUSES = ("success", "wanted", "upcoming", "failed", "pending")
SORTS = {
    "title": "t.title COLLATE NOCASE",
    "status": "t.status",
    "requester": "t.requester",
    "updated": "t.updated_at",
    "created": "t.created_at",
}
MAX_PER_PAGE = 200
DEFAULT_PER_PAGE = 50

# content_key on playability_state is either a bare imdb id ("tt1") or an
# episode key ("tt1:S01E02"); this expression recovers the imdb id from
# either shape so it can be grouped and joined once instead of scanned with
# a correlated OR/LIKE per requests row.
_PLAY_IMDB = ("CASE WHEN instr(content_key, ':') > 0 "
              "THEN substr(content_key, 1, instr(content_key, ':') - 1) "
              "ELSE content_key END")

_BASE = f"""
SELECT r.id, r.imdb_id, r.tmdb_id, r.title, r.media_type, r.status, r.error, r.quality, r.source,
       r.info_hash, r.seasons, r.created_at, r.updated_at, r.arr_mirrored_at,
       (SELECT u.username FROM user_requests ur JOIN users u ON u.id = ur.user_id
         WHERE ur.imdb_id = r.imdb_id ORDER BY ur.created_at DESC, ur.id DESC LIMIT 1) AS requester,
       (SELECT ur.user_id FROM user_requests ur WHERE ur.imdb_id = r.imdb_id
         ORDER BY ur.created_at DESC, ur.id DESC LIMIT 1) AS requester_id,
       (SELECT ur.created_at FROM user_requests ur WHERE ur.imdb_id = r.imdb_id
         ORDER BY ur.created_at DESC, ur.id DESC LIMIT 1) AS requested_at,
       CASE ps.rank WHEN 0 THEN 'degraded' WHEN 1 THEN 'unknown' WHEN 2 THEN 'playable' END AS play_status,
       pr.last_fail_reason AS play_reason,
       (SELECT COUNT(*) FROM wanted_episodes w WHERE w.imdb_id = r.imdb_id AND w.status = 'wanted') AS missing_episodes,
       (SELECT q.attempt FROM retry_queue q WHERE q.imdb_id = r.imdb_id) AS retry_attempt,
       (SELECT q.next_retry_at FROM retry_queue q WHERE q.imdb_id = r.imdb_id) AS retry_next,
       (SELECT 1 FROM wanted_movies wm WHERE wm.imdb_id = r.imdb_id) AS in_wanted_movies,
       (SELECT 1 FROM virtual_items v WHERE v.imdb_id = r.imdb_id AND v.torbox_id IS NOT NULL LIMIT 1) AS in_torbox
FROM requests r
LEFT JOIN (
    SELECT {_PLAY_IMDB} AS imdb,
           MIN(CASE status WHEN 'degraded' THEN 0 WHEN 'unknown' THEN 1 ELSE 2 END) AS rank
    FROM playability_state
    GROUP BY 1
) ps ON ps.imdb = r.imdb_id
LEFT JOIN (
    SELECT imdb, last_fail_reason FROM (
        SELECT {_PLAY_IMDB} AS imdb, last_fail_reason,
               ROW_NUMBER() OVER (PARTITION BY {_PLAY_IMDB} ORDER BY updated_at DESC) AS rn
        FROM playability_state
        WHERE status = 'degraded'
    ) WHERE rn = 1
) pr ON pr.imdb = r.imdb_id
"""

_VIEW_WHERE = {
    "all": "1=1",
    "attention": "(t.status = 'failed' OR t.play_status = 'degraded' OR t.retry_attempt >= 3)",
    "wanted": "t.status IN ('wanted', 'upcoming')",
    "queue": "(t.status = 'pending' OR t.retry_attempt IS NOT NULL OR t.in_wanted_movies = 1 OR t.missing_episodes > 0)",
    "incomplete": "(t.media_type != 'movie' AND t.missing_episodes > 0)",
    "unmirrored": "(t.status = 'success' AND t.arr_mirrored_at IS NULL)",
}
_VIEW_ORDER = {
    "wanted": "t.updated_at ASC",
    "queue": "t.retry_next IS NULL, t.retry_next ASC, t.updated_at DESC",
}
_PROBLEM_WHERE = {
    "failed": "t.status = 'failed'",
    "wanted": "t.status IN ('wanted', 'upcoming')",
    "unplayable": "t.play_status = 'degraded'",
    "missing_episodes": "t.missing_episodes > 0",
    "in_retry_queue": "t.retry_attempt IS NOT NULL",
    "no_requester": "t.requester IS NULL",
    "not_mirrored": "(t.status = 'success' AND t.arr_mirrored_at IS NULL)",
}
_ADDED = {"24h": "-1 day", "7d": "-7 days", "30d": "-30 days"}


def _like(q: str) -> str:
    """Escape a search term for SQLite LIKE: backslash first (it is the
    escape character itself), then the two LIKE wildcards, so a literal
    `_` or `%` in a title or hash is matched literally rather than as a
    wildcard."""
    escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _where(filters: dict) -> tuple[str, list]:
    clauses: list[str] = []
    args: list = []
    view = filters.get("view") or "all"
    clauses.append(_VIEW_WHERE.get(view, "0=1"))
    q = (filters.get("q") or "").strip()
    if q:
        like = _like(q)
        clauses.append("(t.title LIKE ? ESCAPE '\\' OR t.imdb_id LIKE ? ESCAPE '\\' OR t.info_hash LIKE ? ESCAPE '\\')")
        args += [like, like, like]
    statuses = [s for s in (filters.get("status") or []) if s in STATUSES]
    if filters.get("status"):
        if statuses:
            clauses.append("t.status IN (%s)" % ",".join("?" * len(statuses)))
            args += statuses
        else:
            clauses.append("0=1")
    kind = filters.get("type")
    if kind == "movie":
        clauses.append("t.media_type = 'movie'")
    elif kind == "series":
        clauses.append("t.media_type != 'movie'")
    problem = filters.get("problem")
    if problem in _PROBLEM_WHERE:
        clauses.append(_PROBLEM_WHERE[problem])
    requester = filters.get("requester")
    if requester == "auto":
        clauses.append("t.requester IS NULL")
    elif requester and str(requester).isdigit():
        clauses.append("t.requester_id = ?")
        args.append(int(requester))
    added = _ADDED.get(filters.get("added") or "")
    if added:
        clauses.append("t.created_at >= datetime('now', ?)")
        args.append(added)
    return " AND ".join(clauses), args


def _order(filters: dict) -> str:
    sort = filters.get("sort")
    if sort in SORTS:
        direction = "ASC" if (filters.get("order") or "").lower() == "asc" else "DESC"
        return f"{SORTS[sort]} {direction}, t.id DESC"
    view = filters.get("view") or "all"
    return _VIEW_ORDER.get(view, "t.updated_at DESC, t.id DESC")


def _int(value, default: int, lo: int, hi: int) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


def _row(r: dict) -> dict:
    return {
        "id": r["id"], "imdb_id": r["imdb_id"], "tmdb_id": r["tmdb_id"], "title": r["title"],
        "media_type": r["media_type"], "status": r["status"], "error": r["error"],
        "quality": r["quality"], "source": r["source"], "info_hash": r["info_hash"], "seasons": r["seasons"],
        "created_at": r["created_at"], "updated_at": r["updated_at"],
        "requester": r["requester"] or "auto", "requester_id": r["requester_id"],
        "requested_at": r["requested_at"],
        "playability": ({"status": r["play_status"], "last_fail_reason": r["play_reason"]}
                        if r["play_status"] and r["play_status"] != "playable" else None),
        "missing_episodes": r["missing_episodes"] or 0,
        "retry": ({"attempt": r["retry_attempt"], "next_retry_at": r["retry_next"]}
                  if r["retry_attempt"] is not None else None),
        "arr_mirrored": r["arr_mirrored_at"] is not None,
        "in_torbox": bool(r["in_torbox"]),
        "in_wanted_movies": bool(r["in_wanted_movies"]),
    }


def list_titles(filters: dict) -> tuple[list[dict], int]:
    where, args = _where(filters)
    per_page = _int(filters.get("per_page"), DEFAULT_PER_PAGE, 1, MAX_PER_PAGE)
    page = _int(filters.get("page"), 1, 1, 10_000_000)
    order = _order(filters)
    with db._connect() as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM ({_BASE}) t WHERE {where}", args).fetchone()[0]
        rows = conn.execute(
            f"SELECT * FROM ({_BASE}) t WHERE {where} ORDER BY {order} LIMIT ? OFFSET ?",
            args + [per_page, (page - 1) * per_page]).fetchall()
    return [_row(dict(r)) for r in rows], total


def view_counts() -> dict[str, int]:
    out = {}
    with db._connect() as conn:
        for view in VIEWS:
            out[view] = conn.execute(f"SELECT COUNT(*) FROM ({_BASE}) t WHERE {_VIEW_WHERE[view]}").fetchone()[0]
    return out


def _seasons_summary(imdb_id: str) -> list[dict]:
    with db._connect() as conn:
        present = {r["season"]: r["n"] for r in conn.execute(
            "SELECT season, COUNT(*) AS n FROM virtual_items WHERE imdb_id = ? AND season IS NOT NULL GROUP BY season",
            (imdb_id,))}
        wanted = {r["season"]: r["n"] for r in conn.execute(
            "SELECT season, COUNT(*) AS n FROM wanted_episodes WHERE imdb_id = ? AND status = 'wanted' GROUP BY season",
            (imdb_id,))}
    return [{"season": s, "present": present.get(s, 0), "wanted": wanted.get(s, 0)}
            for s in sorted(set(present) | set(wanted))]


def title_detail(imdb_id: str) -> dict | None:
    req = db.get_request_by_imdb(imdb_id)
    if not req:
        return None
    is_series = req["media_type"] != "movie"
    items = db.get_virtual_items_by_imdb(imdb_id)
    return {
        "request": req,
        "items": [{k: i.get(k) for k in ("token", "info_hash", "strm_path", "torbox_id", "last_played",
                                         "play_count", "season", "episode", "debrid_provider", "quality")}
                  for i in items],
        "playability": db.get_playability_for_title(imdb_id),
        "episodes": _seasons_summary(imdb_id) if is_series else None,
        "monitored": db.get_monitored_series_by_imdb(imdb_id) if is_series else None,
        "retry": db.get_retry_by_imdb(imdb_id),
        "wanted_movie": None if is_series else db.get_wanted_movie(imdb_id),
        "user_requests": db.get_user_requests_for_title(imdb_id),
        "seerr_request_id": db.get_seerr_request_id(imdb_id),
        "override": db.get_show_override(imdb_id),
        "hashes": db.get_hashes_for_title(imdb_id),
        "activity": db.get_activity_for_title(imdb_id, req.get("title")),
        "arr": {"mirrored_at": req.get("arr_mirrored_at")},
        "mirror_on": arr_sync.is_enabled(),
    }


def season_episodes(imdb_id: str, season: int) -> list[dict]:
    with db._connect() as conn:
        present = {r["episode"]: dict(r) for r in conn.execute(
            "SELECT episode, token, strm_path FROM virtual_items WHERE imdb_id = ? AND season = ? AND episode IS NOT NULL",
            (imdb_id, season))}
    wanted = {w["episode"]: w for w in db.get_wanted_episodes_for_title(imdb_id) if w["season"] == season}
    out = []
    for ep in sorted(set(present) | set(wanted)):
        p, w = present.get(ep), wanted.get(ep)
        out.append({"season": season, "episode": ep, "present": p is not None,
                    "strm_path": p["strm_path"] if p else None, "token": p["token"] if p else None,
                    "wanted_status": w["status"] if w else None,
                    "attempt_count": w["attempt_count"] if w else 0,
                    "air_date": w["air_date"] if w else None,
                    "last_attempted": w["last_attempted"] if w else None})
    return out
