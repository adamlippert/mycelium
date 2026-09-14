"""What the React SPA calls: discover, watchlist, user requests, the
library views it renders, and the static shell itself. Registered last: it
owns the catch-all."""
import logging
import threading
import time

from flask import Blueprint, jsonify, redirect, request, url_for

import admin_query
import auth
import config as cfg
import db
import jellyfin
import monitor
import plugin_loader
import processor
import quota
import strm_generator
import tmdb
import torbox
import upgrader
from appcore import LITE_MODE
from routes._common import (_SPA_ASSET_DIR, _SPA_DIR, _series_episodes_cache,
                            _series_episodes_lock, _SERIES_EPISODES_TTL_SEC,
                            _spa_index)

log = logging.getLogger("mycelium")

bp = Blueprint("spa", __name__)


# ── Discover (TMDB) ──────────────────────────────────────────────────────────

@bp.get("/ui/api/discover/search")
def ui_api_discover_search():
    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify(results=[])
    page = admin_query.clamp_int(request.args.get("page"), 1, 1, 500)
    results = tmdb.multi_search(q, page=page)
    results = _filter_by_language(results)
    _enrich_library_status(results)
    return jsonify(results=results)


_STATUS_PRIORITY = {"success": 0, "available": 0, "wanted": 1, "pending": 2, "upcoming": 3, "failed": 4}


def _enrich_library_status(items: list[dict]) -> None:
    """Add library_status and imdb_id to TMDB result dicts by checking all tables with tmdb_id."""
    tmdb_ids = [it["tmdb_id"] for it in items if it.get("tmdb_id")]
    if not tmdb_ids:
        return
    ph = ",".join("?" * len(tmdb_ids))
    with db._connect() as conn:
        rows = conn.execute(f"""
            SELECT tmdb_id, status FROM requests WHERE tmdb_id IN ({ph})
            UNION ALL
            SELECT w.tmdb_id, r.status
            FROM watchlist w JOIN requests r ON r.imdb_id = w.imdb_id
            WHERE w.tmdb_id IN ({ph})
            UNION ALL
            SELECT ms.tmdb_id, r.status
            FROM monitored_series ms JOIN requests r ON r.imdb_id = ms.imdb_id
            WHERE ms.tmdb_id IN ({ph})
            UNION ALL
            SELECT ur.tmdb_id, COALESCE(r.status, ur.status)
            FROM user_requests ur LEFT JOIN requests r ON r.imdb_id = ur.imdb_id
            WHERE ur.tmdb_id IN ({ph})
        """, tmdb_ids * 4).fetchall()
        # Fetch imdb_ids from library so PosterCard can show watched badges
        imdb_rows = conn.execute(
            f"SELECT tmdb_id, imdb_id FROM requests WHERE tmdb_id IN ({ph}) AND imdb_id IS NOT NULL",
            tmdb_ids,
        ).fetchall()
        # Also from trakt_watched for items watched but not in library
        rec = auth.current_user_record()
        trakt_imdb_rows = []
        if rec and rec.get("id"):
            try:
                trakt_imdb_rows = conn.execute(
                    f"SELECT tmdb_id, imdb_id FROM trakt_watched WHERE user_id=? AND tmdb_id IN ({ph}) AND imdb_id IS NOT NULL",
                    [rec["id"]] + tmdb_ids,
                ).fetchall()
            except Exception:
                pass
    status_map: dict[int, str] = {}
    for r in rows:
        tid, st = r["tmdb_id"], r["status"]
        prev = status_map.get(tid)
        if prev is None or _STATUS_PRIORITY.get(st, 9) < _STATUS_PRIORITY.get(prev, 9):
            status_map[tid] = st
    imdb_map = {r["tmdb_id"]: r["imdb_id"] for r in imdb_rows}
    for r in trakt_imdb_rows:
        imdb_map.setdefault(r["tmdb_id"], r["imdb_id"])
    for it in items:
        it["library_status"] = status_map.get(it.get("tmdb_id"))
        if not it.get("imdb_id"):
            it["imdb_id"] = imdb_map.get(it.get("tmdb_id"))


def _filter_by_language(items: list[dict]) -> list[dict]:
    """Apply the logged-in user's Discover language include/exclude preference
    to a list of normalized TMDB items (in place semantics via return value).
    Include wins when both are set for the same language. Items with no
    original_language (rare) are never filtered out."""
    rec = auth.current_user_record()
    if not rec:
        return items
    include = {l.strip().lower() for l in (rec.get("discover_language_include") or "").split(",") if l.strip()}
    exclude = {l.strip().lower() for l in (rec.get("discover_language_exclude") or "").split(",") if l.strip()}
    if not include and not exclude:
        return items
    out = []
    for it in items:
        lang = (it.get("original_language") or "").lower()
        if not lang:
            out.append(it)
            continue
        if include:
            if lang in include:
                out.append(it)
            continue
        if lang not in exclude:
            out.append(it)
    return out


def _user_region() -> str:
    """Region from ?region= param, or from the logged-in user's profile, or system default."""
    r = request.args.get("region")
    if r:
        return r
    rec = auth.current_user_record()
    if rec and rec.get("region"):
        return rec["region"]
    return cfg.AUTO_ADD_REGION


@bp.get("/ui/api/discover/trending")
def ui_api_discover_trending():
    media = request.args.get("type", "all")  # all | movie | tv
    window = request.args.get("window", "week")  # day | week
    results = tmdb.trending(media, window)
    results = _filter_by_language(results)
    _enrich_library_status(results)
    return jsonify(results=results)


@bp.get("/ui/api/discover/popular")
def ui_api_discover_popular():
    media = request.args.get("type", "movie")
    region = _user_region()
    results = tmdb.popular(media, region=region)
    results = _filter_by_language(results)
    _enrich_library_status(results)
    return jsonify(results=results)


@bp.get("/ui/api/discover/top-rated")
def ui_api_discover_top_rated():
    media = request.args.get("type", "movie")
    results = tmdb.top_rated(media)
    results = _filter_by_language(results)
    _enrich_library_status(results)
    return jsonify(results=results)


@bp.get("/ui/api/discover/now-playing")
def ui_api_discover_now_playing():
    region = _user_region()
    results = tmdb.now_playing(region=region)
    results = _filter_by_language(results)
    _enrich_library_status(results)
    return jsonify(results=results)


@bp.get("/ui/api/discover/upcoming")
def ui_api_discover_upcoming():
    region = _user_region()
    results = tmdb.upcoming(region=region)
    results = _filter_by_language(results)
    _enrich_library_status(results)
    return jsonify(results=results)


@bp.get("/ui/api/discover/on-the-air")
def ui_api_discover_on_the_air():
    results = tmdb.on_the_air()
    results = _filter_by_language(results)
    _enrich_library_status(results)
    return jsonify(results=results)


@bp.get("/ui/api/discover/providers")
def ui_api_discover_providers():
    media = request.args.get("type", "movie")
    region = _user_region()
    return jsonify(providers=tmdb.list_providers(media, region=region))


@bp.get("/ui/api/discover/by-provider")
def ui_api_discover_by_provider():
    media = request.args.get("type", "movie")
    pid = int(request.args.get("provider_id") or "0")
    region = _user_region()
    sort = request.args.get("sort_by", "popularity.desc")
    if not pid:
        return jsonify(error="provider_id required"), 400
    results = tmdb.discover_by_provider(media, pid, region=region, sort_by=sort)
    results = _filter_by_language(results)
    _enrich_library_status(results)
    return jsonify(results=results)


@bp.get("/ui/api/discover/by-genre")
def ui_api_discover_by_genre():
    media = request.args.get("type", "movie")
    genre_id = int(request.args.get("genre_id") or "0")
    if not genre_id:
        return jsonify(error="genre_id required"), 400
    year_from = request.args.get("year_from")
    year_to = request.args.get("year_to")
    results = tmdb.discover_by_genre(
        media, genre_id,
        year_from=int(year_from) if year_from else None,
        year_to=int(year_to) if year_to else None,
    )
    results = _filter_by_language(results)
    _enrich_library_status(results)
    return jsonify(results=results)


@bp.get("/ui/api/discover/genre-tabs")
def ui_api_discover_genre_tabs():
    """Public: enabled genre-tab configs for the Discover page rows."""
    import json
    import settings as _s
    raw = _s.get("DISCOVER_GENRE_TABS", "[]")
    try:
        tabs = json.loads(raw) if isinstance(raw, str) else (raw or [])
    except (TypeError, ValueError):
        tabs = []
    return jsonify(tabs=[t for t in tabs if t.get("enabled")])


@bp.get("/ui/api/discover/genre-tabs/config")
@auth.require_auth
def ui_api_discover_genre_tabs_config_get():
    if not auth.is_admin():
        return jsonify(error="unauthorized"), 401
    import json
    import settings as _s
    raw = _s.get("DISCOVER_GENRE_TABS", "[]")
    try:
        tabs = json.loads(raw) if isinstance(raw, str) else (raw or [])
    except (TypeError, ValueError):
        tabs = []
    return jsonify(tabs=tabs)


@bp.post("/ui/api/discover/genre-tabs/config")
@auth.require_auth
def ui_api_discover_genre_tabs_config_set():
    if not auth.is_admin():
        return jsonify(error="unauthorized"), 401
    import json
    import settings as _s
    p = request.get_json(silent=True) or {}
    tabs = p.get("tabs")
    if not isinstance(tabs, list):
        return jsonify(error="tabs must be a list"), 400
    _s.set("DISCOVER_GENRE_TABS", json.dumps(tabs))
    return jsonify(ok=True)


@bp.get("/ui/api/discover/details")
def ui_api_discover_details():
    media = request.args.get("type", "movie")
    tmdb_id = int(request.args.get("id") or "0")
    region = _user_region()
    if not tmdb_id:
        return jsonify(error="id required"), 400
    detail = tmdb.details(media, tmdb_id, region=region)
    if not detail:
        return jsonify(error="not found"), 404
    imdb_id = detail.get("imdb_id")
    if imdb_id:
        vi = db.get_virtual_items_by_imdb(imdb_id)
        if vi:
            detail["library_status"] = "available"
        else:
            with db._connect() as conn:
                row = conn.execute(
                    "SELECT status FROM requests WHERE imdb_id=?", (imdb_id,)
                ).fetchone()
            if row:
                detail["library_status"] = row["status"]
    return jsonify(detail)


_QUOTA_PAUSE_NOTE = "auto-approve paused: monthly quota reached"


@bp.post("/ui/api/discover/add")
def ui_api_discover_add():
    """One-click add: resolve TMDB→IMDB, queue for processing.
    For TV the payload may include monitor_mode ('all'|'future'|'selected')
    and seasons (list of season numbers, used when mode is 'selected')."""
    payload = request.get_json(silent=True) or {}
    tmdb_id = payload.get("tmdb_id")
    media_type = payload.get("media_type") or "movie"
    title = payload.get("title") or ""
    monitor_mode = payload.get("monitor_mode") or "all"
    seasons = payload.get("seasons") or None
    if not tmdb_id or not title:
        return jsonify(error="tmdb_id and title required"), 400

    imdb_id = tmdb.tmdb_to_imdb(tmdb_id, media_type=media_type)
    if not imdb_id:
        return jsonify(error="could not resolve imdb_id"), 400

    user_rec = auth.current_user_record()
    if user_rec and user_rec.get("id"):
        # Multi-user mode: go through approval flow, quota first
        ok, info = quota.allows(user_rec)
        auto = bool(user_rec.get("auto_approve")) or user_rec.get("role") == "admin"
        if not ok and not auto:
            return jsonify(error="quota reached", used=info["used"], limit=info["limit"],
                           resets_at=info["resets_at"]), 409
        status = "approved" if auto and ok else "pending"
        note = None if ok else _QUOTA_PAUSE_NOTE
        rid = db.create_user_request(user_rec["id"], imdb_id, tmdb_id, media_type,
                                       title, status=status, note=note)
        if status == "approved":
            _kick_off_processing(title, imdb_id, media_type, tmdb_id, monitor_mode, seasons)
        return jsonify(status=status, request_id=rid, imdb_id=imdb_id)

    # Single-user / legacy mode: process immediately
    _kick_off_processing(title, imdb_id, media_type, tmdb_id, monitor_mode, seasons)
    return jsonify(status="queued", imdb_id=imdb_id)


def _kick_off_processing(title: str, imdb_id: str, media_type: str,
                          tmdb_id: int | None = None,
                          monitor_mode: str = "all",
                          seasons: list[int] | None = None) -> None:
    from webhook_parser import MediaRequest
    if media_type == "tv":
        try:
            show = tmdb.get_show_info(tmdb_id) if tmdb_id else None
            n_seasons = (show or {}).get("number_of_seasons") or 1
            all_seasons = list(range(1, n_seasons + 1))
            if monitor_mode == "selected" and seasons:
                monitored = [int(s) for s in seasons if int(s) in all_seasons]
            else:
                monitored = all_seasons
            db.upsert_monitored_series(imdb_id, tmdb_id, title, monitored, monitor_mode=monitor_mode)
        except Exception as exc:
            log.warning("upsert_monitored_series failed: %s", exc)
            monitored = seasons or [1]
        # 'future' mode: don't eagerly fetch the back-catalog  -  let the monitor
        # pick up episodes as they air. Eagerly process only for all/selected.
        process_seasons = [] if monitor_mode == "future" else monitored
        req = MediaRequest(title=title, media_type="series",
                            imdb_id=imdb_id, seasons=process_seasons, tmdb_id=tmdb_id)
        if not process_seasons:
            # Nothing to fetch now; the series is monitored and the periodic
            # check will grab future episodes.
            return
    else:
        req = MediaRequest(title=title, media_type="movie", imdb_id=imdb_id, seasons=[], tmdb_id=tmdb_id)
    threading.Thread(
        target=processor.process, args=(req,),
        name=f"discover-{imdb_id}", daemon=True,
    ).start()


# ── Watchlist (per user) ─────────────────────────────────────────────────────

@bp.get("/ui/api/watchlist")
def ui_api_watchlist_get():
    rec = auth.current_user_record()
    if not rec or not rec.get("id"):
        return jsonify(items=[])
    items = db.get_watchlist(rec["id"])
    imdb_ids = [w["imdb_id"] for w in items if w.get("imdb_id")]
    if imdb_ids:
        with db._connect() as conn:
            ph = ",".join("?" * len(imdb_ids))
            rows = conn.execute(
                f"SELECT imdb_id, status FROM requests WHERE imdb_id IN ({ph})",
                imdb_ids,
            ).fetchall()
            lib_map = {r["imdb_id"]: r["status"] for r in rows}
            # Enrich poster_path from poster_cache for items missing it
            poster_rows = conn.execute(
                f"SELECT imdb_id, poster_path FROM poster_cache WHERE imdb_id IN ({ph})",
                imdb_ids,
            ).fetchall()
            poster_map = {r["imdb_id"]: r["poster_path"] for r in poster_rows}
        for w in items:
            w["library_status"] = lib_map.get(w.get("imdb_id"))
            if not w.get("poster_path") and w.get("imdb_id"):
                w["poster_path"] = poster_map.get(w["imdb_id"])
    else:
        for w in items:
            w["library_status"] = None
    return jsonify(items=items)


@bp.post("/ui/api/watchlist/add")
def ui_api_watchlist_add():
    rec = auth.current_user_record()
    if not rec or not rec.get("id"):
        return jsonify(error="login required"), 401
    p = request.get_json(silent=True) or {}
    imdb = (p.get("imdb_id") or "").strip()
    if not imdb:
        return jsonify(error="imdb_id required"), 400
    db.add_to_watchlist(rec["id"], imdb, p.get("tmdb_id"),
                         p.get("media_type") or "movie",
                         p.get("title") or "", p.get("poster_path"))
    return jsonify(ok=True)


@bp.post("/ui/api/watchlist/remove")
def ui_api_watchlist_remove():
    rec = auth.current_user_record()
    if not rec or not rec.get("id"):
        return jsonify(error="login required"), 401
    p = request.get_json(silent=True) or {}
    db.remove_from_watchlist(rec["id"], (p.get("imdb_id") or "").strip(),
                              p.get("media_type") or "movie")
    return jsonify(ok=True)


# ── User requests (approval flow) ────────────────────────────────────────────

@bp.get("/ui/api/user-requests")
def ui_api_user_requests():
    rec = auth.current_user_record()
    if not rec:
        return jsonify(items=[])
    status = request.args.get("status") or None
    mine_only = request.args.get("mine") == "1"
    if mine_only or rec.get("role") != "admin":
        items = db.get_user_requests(user_id=rec["id"], status=status)
    else:
        items = db.get_user_requests(status=status)
    imdb_ids = {r["imdb_id"] for r in items}
    if imdb_ids:
        with db._connect() as conn:
            ph = ",".join("?" * len(imdb_ids))
            rows = conn.execute(
                f"SELECT imdb_id, status FROM requests WHERE imdb_id IN ({ph})",
                list(imdb_ids),
            ).fetchall()
            lib_map = {r["imdb_id"]: r["status"] for r in rows}
        for r in items:
            r["library_status"] = lib_map.get(r["imdb_id"])
    else:
        for r in items:
            r["library_status"] = None
    return jsonify(items=items)


@bp.post("/ui/api/user-requests/<int:req_id>/approve")
def ui_api_user_request_approve(req_id: int):
    if not auth.is_admin():
        return jsonify(error="admin required"), 403
    rec = auth.current_user_record()
    r = db.get_user_request(req_id)
    if not r:
        return jsonify(error="not found"), 404
    db.update_user_request_status(req_id, "approved",
                                   reviewed_by=(rec or {}).get("id"))
    if r.get("note") == _QUOTA_PAUSE_NOTE:
        db.clear_user_request_note(req_id)
    _kick_off_processing(r["title"], r["imdb_id"], r["media_type"], r.get("tmdb_id"))
    return jsonify(ok=True)


@bp.post("/ui/api/user-requests/<int:req_id>/deny")
def ui_api_user_request_deny(req_id: int):
    if not auth.is_admin():
        return jsonify(error="admin required"), 403
    rec = auth.current_user_record()
    p = request.get_json(silent=True) or {}
    db.update_user_request_status(req_id, "denied",
                                   reviewed_by=(rec or {}).get("id"),
                                   note=p.get("note"))
    return jsonify(ok=True)


# ── User management (admin) ──────────────────────────────────────────────────

@bp.get("/ui/api/wanted-movies")
def ui_api_wanted_movies():
    return jsonify(items=db.get_wanted_movies())


@bp.post("/ui/api/wanted-recheck")
def ui_api_wanted_recheck():
    if not auth.is_admin():
        return jsonify(error="admin required"), 403
    def _run():
        try:
            upgrader.recheck_wanted()
            monitor.run_series_check()
        except Exception as exc:
            logging.getLogger(__name__).error("wanted-recheck-manual failed: %s", exc)
    threading.Thread(target=_run, name="wanted-recheck-manual", daemon=True).start()
    return jsonify(ok=True, message="wanted recheck started")


@bp.get("/ui/api/wanted-episodes")
def ui_api_wanted_episodes():
    db.reconcile_wanted_episodes()
    return jsonify(items=db.get_all_wanted_episodes())


@bp.get("/ui/api/library/status-map")
def ui_api_library_status_map():
    """Map of tmdb_id -> library status for badge display on poster cards."""
    with db._connect() as conn:
        rows = conn.execute("""
            SELECT tmdb_id, status FROM requests WHERE tmdb_id IS NOT NULL
            UNION
            SELECT w.tmdb_id, r.status
            FROM watchlist w
            JOIN requests r ON r.imdb_id = w.imdb_id
            WHERE w.tmdb_id IS NOT NULL
            UNION
            SELECT ms.tmdb_id, r.status
            FROM monitored_series ms
            JOIN requests r ON r.imdb_id = ms.imdb_id
            WHERE ms.tmdb_id IS NOT NULL
            UNION
            SELECT ur.tmdb_id,
                   COALESCE(r.status, ur.status) AS status
            FROM user_requests ur
            LEFT JOIN requests r ON r.imdb_id = ur.imdb_id
            WHERE ur.tmdb_id IS NOT NULL
        """).fetchall()
    return jsonify({str(r["tmdb_id"]): r["status"] for r in rows})


@bp.get("/ui/api/library/movies")
def ui_api_library_movies():
    """One page of movie requests with status info, reconciling stale wanted
    status. Paginated server-side: the old get_recent(10000) shape silently
    hid everything past the 10,000 most recent rows."""
    db.reconcile_wanted_movies()
    try:
        page = max(1, int(request.args.get("page", 1)))
    except ValueError:
        page = 1
    try:
        page_size = min(100, max(1, int(request.args.get("page_size", 24))))
    except ValueError:
        page_size = 24
    search = (request.args.get("search") or "").strip()
    status_filter = request.args.get("filter", "all")
    if status_filter not in ("all", "available", "wanted"):
        status_filter = "all"
    result = db.get_movie_requests_page(
        search=search, status_filter=status_filter,
        limit=page_size, offset=(page - 1) * page_size)
    items = [{
        "title": r.get("title") or "Unknown",
        "imdb_id": r.get("imdb_id", ""),
        "tmdb_id": r.get("tmdb_id"),
        "quality": r.get("quality"),
        "status": r.get("status"),
        "source": r.get("source"),
        "created_at": r.get("created_at"),
        "year": r.get("year"),
    } for r in result["items"]]
    # Enrich with cached poster paths (single batch query)
    imdb_ids = [it["imdb_id"] for it in items if it.get("imdb_id")]
    poster_map = db.get_posters_batch(imdb_ids)
    for it in items:
        it["poster_path"] = poster_map.get(it["imdb_id"])
    return jsonify(items=items, total=result["total"], counts=result["counts"],
                   page=page, page_size=page_size)


@bp.get("/ui/api/library/series-episodes")
def ui_api_library_series_episodes():
    """Return available episodes per series with wanted info."""
    now = time.monotonic()
    if _series_episodes_cache["data"] is not None \
            and now - _series_episodes_cache["ts"] < _SERIES_EPISODES_TTL_SEC:
        return jsonify(series=_series_episodes_cache["data"])
    with _series_episodes_lock:
        now = time.monotonic()
        if _series_episodes_cache["data"] is not None \
                and now - _series_episodes_cache["ts"] < _SERIES_EPISODES_TTL_SEC:
            return jsonify(series=_series_episodes_cache["data"])
        out = _build_series_episodes()
        _series_episodes_cache["data"] = out
        _series_episodes_cache["ts"] = time.monotonic()
        return jsonify(series=out)


def _build_series_episodes() -> list[dict]:
    db.reconcile_wanted_episodes()
    import re as _re
    from pathlib import Path as _Path
    _EP_RE = _re.compile(r'[Ss](\d{1,2})[Ee](\d{1,3})')
    series_dir = _Path(cfg.MEDIA_PATH) / "series"

    folder_imdb = db.get_series_folder_imdb_map()

    all_monitored = db.get_all_monitored_series()
    mon_by_title: dict[str, dict] = {}
    for s in all_monitored:
        mon_by_title[s["title"].lower()] = s

    wanted_eps = db.get_all_wanted_episodes()
    wanted_by_imdb: dict[str, list[dict]] = {}
    for ep in wanted_eps:
        if ep.get("status") != "wanted":
            continue
        wanted_by_imdb.setdefault(ep["imdb_id"], []).append(ep)

    all_eps_by_imdb: dict[str, list[dict]] = {}
    for ep in wanted_eps:
        all_eps_by_imdb.setdefault(ep["imdb_id"], []).append(ep)

    out = []
    if not series_dir.is_dir():
        return []
    for show in sorted(series_dir.iterdir()):
        if not show.is_dir():
            continue
        seasons_map: dict[int, list[int]] = {}
        for season_dir in sorted(show.iterdir()):
            if not season_dir.is_dir():
                continue
            try:
                s_num = int("".join(c for c in season_dir.name if c.isdigit()))
            except ValueError:
                continue
            episodes = []
            for strm in sorted(season_dir.glob("*.strm")):
                m = _EP_RE.search(strm.stem)
                if m:
                    episodes.append(int(m.group(2)))
            if episodes:
                seasons_map[s_num] = sorted(set(episodes))

        folder_lower = show.name.lower()
        clean = _re.sub(r'\s*\(\d{4}\)\s*$', '', folder_lower)

        imdb_id = folder_imdb.get(folder_lower) or folder_imdb.get(clean)
        if not imdb_id:
            mon = mon_by_title.get(folder_lower) or mon_by_title.get(clean)
            if not mon:
                for title, s in mon_by_title.items():
                    if title.startswith(clean) or clean.startswith(title):
                        mon = s
                        break
            imdb_id = mon["imdb_id"] if mon else None

        missing_eps = wanted_by_imdb.get(imdb_id, []) if imdb_id else []
        missing = [{"season": ep["season"], "episode": ep["episode"]} for ep in missing_eps]

        for m in missing:
            if m["season"] not in seasons_map:
                seasons_map[m["season"]] = []

        season_years: dict[int, str] = {}
        if imdb_id and imdb_id in all_eps_by_imdb:
            for ep in all_eps_by_imdb[imdb_id]:
                s = ep["season"]
                ad = ep.get("air_date") or ""
                if ad and s not in season_years:
                    season_years[s] = ad[:4]

        seasons = [
            {"season": s, "episodes": eps, "year": season_years.get(s, "")}
            for s, eps in sorted(seasons_map.items())
        ]

        if seasons or missing:
            out.append({
                "title": show.name,
                "imdb_id": imdb_id,
                "seasons": seasons,
                "missing": missing,
            })
    return out


@bp.get("/ui/api/torbox-quota")
def ui_api_torbox_quota():
    """createtorrent usage in the last hour, broken down by reason  -  explains
    why TorBox 429 rate limits are being hit."""
    return jsonify(torbox.createtorrent_usage())


@bp.post("/ui/api/me/plugin-fields")
@auth.require_auth
def ui_api_me_plugin_fields():
    """Let users toggle their own plugin user_fields (e.g. webplayer_enabled)."""
    rec = auth.current_user_record()
    if not rec:
        return jsonify(error="not authenticated"), 401
    p = request.get_json(silent=True) or {}
    allowed = set(plugin_loader.user_fields())
    fields = {k: (1 if v else 0) for k, v in p.items() if k in allowed}
    if not fields:
        return jsonify(error="no valid fields"), 400
    if not rec.get("id"):
        # Legacy single-user login: id=0 matches no users-table row, so
        # db.update_user(0, ...) silently no-ops. Same fix as region
        # (LEGACY_USER_REGION): persist in settings; the shim record in
        # auth.current_user_record() reads it back.
        auth.save_legacy_user_prefs(fields)
        return jsonify(ok=True)
    db.update_user(rec["id"], **fields)
    return jsonify(ok=True)


@bp.post("/ui/api/me/region")
@auth.require_auth
def ui_api_me_region():
    """Let users change their own region."""
    rec = auth.current_user_record()
    if not rec:
        return jsonify(error="not authenticated"), 401
    p = request.get_json(silent=True) or {}
    region = str(p.get("region", "")).upper().strip()[:5]
    if not region:
        return jsonify(error="region required"), 400
    if not rec.get("id"):
        # Legacy single-user login (AUTH_USERNAME/AUTH_PASSWORD) has no real
        # users-table row: current_user_record() hands back a synthetic dict
        # with id=0 (auth.py:170), so db.update_user(0, ...) would match zero
        # rows and silently no-op. That login is single-user by definition
        # though, so there is nothing ambiguous about "the" region for it -
        # persist it as a runtime setting instead of a users-table column.
        # ui_api_session reads it back the same way (LEGACY_USER_REGION).
        import settings as _settings
        _settings.set("LEGACY_USER_REGION", region)
        return jsonify(ok=True, region=region)
    db.update_user(rec["id"], region=region)
    return jsonify(ok=True, region=region)


@bp.post("/ui/api/me/preferences")
@auth.require_auth
def ui_api_me_preferences():
    """Let users update their own UI preferences."""
    rec = auth.current_user_record()
    if not rec:
        return jsonify(error="not authenticated"), 401
    p = request.get_json(silent=True) or {}
    _BOOL_FIELDS = {"library_click_jellyfin"}
    _TEXT_FIELDS = {"discover_language_include", "discover_language_exclude"}
    fields = {}
    for k, v in p.items():
        if k in _BOOL_FIELDS:
            fields[k] = 1 if v else 0
        elif k in _TEXT_FIELDS:
            fields[k] = ",".join(l.strip().lower() for l in str(v or "").split(",") if l.strip())
    if not fields:
        return jsonify(error="no valid fields"), 400
    if not rec.get("id"):
        # Legacy single-user login: see ui_api_me_plugin_fields above.
        auth.save_legacy_user_prefs(fields)
        return jsonify(ok=True)
    db.update_user(rec["id"], **fields)
    return jsonify(ok=True)


## Trakt OAuth/sync/watched/scrobble routes live in plugins/trakt/routes.py
## (a pre-existing plugin - see PLUGIN_META in plugins/trakt/__init__.py).


@bp.get("/ui/api/mdblist/status")
@auth.require_auth
def ui_api_mdblist_status():
    rec = auth.current_user_record()
    if not rec:
        return jsonify(error="not authenticated"), 401
    import mdblist
    return jsonify(
        connected=mdblist.is_configured(rec),
        list_ids=rec.get("mdblist_list_ids") or "",
    )


@bp.post("/ui/api/mdblist/connect")
@auth.require_auth
def ui_api_mdblist_connect():
    rec = auth.current_user_record()
    if not rec:
        return jsonify(error="not authenticated"), 401
    p = request.get_json(silent=True) or {}
    api_key = (p.get("api_key") or "").strip()
    if not api_key:
        return jsonify(error="api_key required"), 400
    db.update_user(rec["id"], mdblist_api_key=api_key)
    return jsonify(ok=True)


@bp.post("/ui/api/mdblist/disconnect")
@auth.require_auth
def ui_api_mdblist_disconnect():
    rec = auth.current_user_record()
    if not rec:
        return jsonify(error="not authenticated"), 401
    db.update_user(rec["id"], mdblist_api_key="", mdblist_list_ids="")
    return jsonify(ok=True)


@bp.get("/ui/api/mdblist/lists")
@auth.require_auth
def ui_api_mdblist_lists():
    rec = auth.current_user_record()
    if not rec or not rec.get("mdblist_api_key"):
        return jsonify(error="MDBList not connected"), 400
    import mdblist
    return jsonify(lists=mdblist.get_user_lists(rec["mdblist_api_key"]))


@bp.post("/ui/api/mdblist/lists")
@auth.require_auth
def ui_api_mdblist_set_lists():
    rec = auth.current_user_record()
    if not rec:
        return jsonify(error="not authenticated"), 401
    p = request.get_json(silent=True) or {}
    list_ids = p.get("list_ids")
    if not isinstance(list_ids, list):
        return jsonify(error="list_ids must be a list"), 400
    db.update_user(rec["id"], mdblist_list_ids=",".join(str(i) for i in list_ids))
    return jsonify(ok=True)


@bp.post("/ui/api/mdblist/sync")
@auth.require_auth
def ui_api_mdblist_sync():
    rec = auth.current_user_record()
    if not rec:
        return jsonify(error="not authenticated"), 401
    import mdblist
    added = mdblist.sync_auto_request(rec)
    return jsonify(ok=True, added=added)


# Cache Jellyfin item IDs: imdb_id -> jellyfin_item_id (or None if not found)
_jellyfin_item_cache: dict[str, str | None] = {}


@bp.get("/ui/api/jellyfin/item")
@auth.require_auth
def ui_api_jellyfin_item():
    """Look up Jellyfin item ID for a given IMDB id. Result is cached in memory."""
    import settings as _settings
    imdb_id = request.args.get("imdb_id", "").strip()
    if not imdb_id:
        return jsonify(error="imdb_id required"), 400
    if imdb_id in _jellyfin_item_cache:
        jid = _jellyfin_item_cache[imdb_id]
        jurl = (_settings.get("JELLYFIN_URL") or cfg.JELLYFIN_URL or "").rstrip("/")
        return jsonify(jellyfin_id=jid, jellyfin_url=jurl or None)
    jurl = (_settings.get("JELLYFIN_URL") or cfg.JELLYFIN_URL or "").rstrip("/")
    jkey = _settings.get("JELLYFIN_API_KEY") or cfg.JELLYFIN_API_KEY or ""
    if not jurl or not jkey:
        return jsonify(jellyfin_id=None, jellyfin_url=None)
    try:
        import requests as _req
        resp = _req.get(
            f"{jurl}/Items",
            params={"AnyProviderIdEquals": f"imdb.{imdb_id}", "includeItemTypes": "Movie,Series"},
            headers=jellyfin.auth_headers(jkey),
            timeout=5,
        )
        resp.raise_for_status()
        items = (resp.json() or {}).get("Items") or []
        jid = items[0]["Id"] if items else None
    except Exception as exc:
        log.debug("Jellyfin item lookup %s failed: %s", imdb_id, exc)
        return jsonify(jellyfin_id=None, jellyfin_url=jurl or None)
    _jellyfin_item_cache[imdb_id] = jid
    return jsonify(jellyfin_id=jid, jellyfin_url=jurl or None)


@bp.get("/ui/api/jellyfin/items")
@auth.require_auth
def ui_api_jellyfin_items():
    """Build imdb_id -> jellyfin_id map by fetching the full Jellyfin library once.
    Cached in memory; returns {jellyfin_url, items: {imdb_id: jellyfin_id_or_null}}."""
    import settings as _settings
    raw = request.args.get("imdb_ids", "").strip()
    if not raw:
        return jsonify(jellyfin_url=None, items={})
    want = {x.strip() for x in raw.split(",") if x.strip()}
    jurl = (_settings.get("JELLYFIN_URL") or cfg.JELLYFIN_URL or "").rstrip("/")
    jkey = _settings.get("JELLYFIN_API_KEY") or cfg.JELLYFIN_API_KEY or ""
    # Serve fully from cache when all requested IDs are already known
    if want.issubset(_jellyfin_item_cache):
        return jsonify(jellyfin_url=jurl or None,
                       items={iid: _jellyfin_item_cache[iid] for iid in want})
    if jurl and jkey:
        try:
            import requests as _req
            # Fetch ALL movies+series from Jellyfin with their provider IDs in one call.
            # Jellyfin does not support filtering by multiple IMDb IDs simultaneously,
            # so we pull the whole library and match locally.
            resp = _req.get(
                f"{jurl}/Items",
                params={
                    "includeItemTypes": "Movie,Series",
                    "Fields": "ProviderIds",
                    "Recursive": "true",
                    "Limit": 10000,
                },
                headers=jellyfin.auth_headers(jkey),
                timeout=15,
            )
            resp.raise_for_status()
            for it in (resp.json() or {}).get("Items") or []:
                iid = (it.get("ProviderIds") or {}).get("Imdb") or ""
                if iid:
                    _jellyfin_item_cache[iid] = it["Id"]
        except Exception as exc:
            log.debug("Jellyfin batch lookup failed: %s", exc)
    return jsonify(jellyfin_url=jurl or None,
                   items={iid: _jellyfin_item_cache.get(iid) for iid in want})


@bp.get("/ui/api/spore-minfo/<token>")
def spore_minfo_api(token: str):
    """Return .minfo sidecar data for a token as plain text key=value pairs.

    Used by the Plex transcoder wrapper when playing .strm files (no .minfo
    file path is known from the URL alone, so the wrapper fetches it here).
    No auth required: only token=hex is returned, no secrets.
    """
    item = db.get_virtual_item(token)
    if not item or not item.get("strm_path"):
        return f"token={token}\n", 404, {"Content-Type": "text/plain"}
    from pathlib import Path as _Path
    strm_path = _Path(item["strm_path"])
    minfo_path = strm_generator._spore_stub_dir(strm_path) / (strm_path.stem + ".minfo")
    if minfo_path.exists():
        try:
            return minfo_path.read_text(encoding="utf-8"), 200, {"Content-Type": "text/plain"}
        except Exception:
            pass
    return f"token={token}\n", 200, {"Content-Type": "text/plain"}


@bp.post("/ui/api/backfill-nfo")
@auth.require_auth
def ui_api_backfill_nfo():
    """Add/update <fileinfo><streamdetails> in all existing NFO files.

    For items with probed audio tracks: uses real codec/language data.
    For unprobed items: uses quality-based defaults (hevc/h264, EAC3 6ch).
    Safe to run multiple times. Triggers a Plex library refresh afterward if
    PLEX_URL and PLEX_TOKEN are configured.
    """
    if not auth.is_admin():
        return jsonify(error="admin required"), 403
    result = strm_generator.backfill_nfo_streamdetails()
    return jsonify(result)


@bp.get("/ui/api/tmdb/find")
@auth.require_auth
def ui_api_tmdb_find():
    """Resolve imdb_id to tmdb_id + media_type via TMDB /find endpoint."""
    imdb_id = request.args.get("imdb_id", "").strip()
    if not imdb_id:
        return jsonify(tmdb_id=None, media_type=None)
    # Check DB first
    with db._connect() as conn:
        row = conn.execute(
            "SELECT tmdb_id, media_type FROM requests WHERE imdb_id=? AND tmdb_id IS NOT NULL LIMIT 1",
            (imdb_id,),
        ).fetchone()
    if row:
        return jsonify(tmdb_id=row["tmdb_id"], media_type=row["media_type"])
    try:
        data = tmdb._get(f"/find/{imdb_id}", params={"external_source": "imdb_id"})
        movie_results = data.get("movie_results") or []
        tv_results    = data.get("tv_results") or []
        if movie_results:
            return jsonify(tmdb_id=movie_results[0]["id"], media_type="movie")
        if tv_results:
            return jsonify(tmdb_id=tv_results[0]["id"], media_type="tv")
    except Exception as exc:
        log.debug("TMDB find %s failed: %s", imdb_id, exc)
    return jsonify(tmdb_id=None, media_type=None)


# ── Modern SPA (React + Vite) served at /app/* ───────────────────────────────

import os as _os
from flask import send_from_directory as _send


@bp.get("/")
def root_index():
    import settings as _settings
    if LITE_MODE:
        return redirect(url_for("admin_library.ui_dashboard"))
    if not _settings.get("SETUP_COMPLETE", False):
        return redirect(url_for("setup.setup_wizard"))
    return _spa_index()


@bp.get("/app")
@bp.get("/app/")
def app_root():
    return _spa_index()


@bp.get("/app/assets/<path:filename>")
def app_assets(filename: str):
    return _send(_SPA_ASSET_DIR, filename)


@bp.get("/app/<path:subpath>")
def app_catchall(subpath: str):
    full = _os.path.join(_SPA_DIR, subpath)
    if _os.path.isfile(full):
        return _send(_SPA_DIR, subpath)
    return _spa_index()


@bp.get("/assets/<path:filename>")
def root_assets(filename: str):
    return _send(_SPA_ASSET_DIR, filename)


# __file__ is routes/spa.py, so the repo root is two dirnames up.
_DOCS_DIR = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "docs")

@bp.get("/docs/<path:filename>")
def docs_file(filename: str):
    return _send(_DOCS_DIR, filename)


@bp.get("/<path:subpath>")
def root_catchall(subpath: str):
    full = _os.path.join(_SPA_DIR, subpath)
    if _os.path.isfile(full):
        return _send(_SPA_DIR, subpath)
    return _spa_index()
