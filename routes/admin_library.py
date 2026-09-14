"""The admin dashboard shell and its Library tab: the read model, the
per-title actions, release swap and the Radarr/Sonarr import."""
import threading

from flask import Blueprint, jsonify, redirect, request, url_for

import auth
import db
from routes._common import _spa_index

bp = Blueprint("admin_library", __name__)


# ── Dashboard ─────────────────────────────────────────────────────────────────

@bp.get("/admin")
def ui_dashboard():
    import settings as _settings
    if not _settings.get("SETUP_COMPLETE", False):
        return redirect(url_for("setup.setup_wizard"))
    if not auth.is_admin():
        return redirect(url_for("auth.login_view", next="/admin"))
    return _spa_index()


@bp.get("/ui")
def ui_redirect():
    return redirect("/admin", code=301)


@bp.get("/ui/api/library")
def ui_api_library():
    """The Library tab's table: filters, views, sort and paging in SQL."""
    if not auth.is_admin():
        return jsonify(error="admin required"), 403
    import admin_query
    import library_admin
    filters = {
        "view": request.args.get("view"), "q": request.args.get("q"),
        "status": request.args.getlist("status"),
        "type": request.args.get("type"), "problem": request.args.get("problem"),
        "requester": request.args.get("requester"), "added": request.args.get("added"),
        "sort": request.args.get("sort"), "order": request.args.get("order"),
        "page": request.args.get("page"), "per_page": request.args.get("per_page"),
    }
    rows, total, page = library_admin.list_titles(filters)
    per_page = admin_query.clamp_int(request.args.get("per_page"), library_admin.DEFAULT_PER_PAGE, 1, library_admin.MAX_PER_PAGE)
    return jsonify(rows=rows, total=total, page=page, per_page=per_page)


@bp.get("/ui/api/library/views")
def ui_api_library_views():
    if not auth.is_admin():
        return jsonify(error="admin required"), 403
    import arr_sync
    import library_admin
    return jsonify(counts=library_admin.view_counts(), mirror_on=arr_sync.is_enabled())


@bp.get("/ui/api/admin/requests")
def ui_api_admin_requests():
    """The Requests tab's table: views, filters, sort and paging in SQL."""
    if not auth.is_admin():
        return jsonify(error="admin required"), 403
    import admin_query
    import requests_admin
    filters = {k: request.args.get(k) for k in
               ("view", "user", "type", "added", "q", "sort", "order", "page", "per_page")}
    rows, total, page = requests_admin.list_requests(filters)
    per_page = admin_query.clamp_int(filters["per_page"], requests_admin.DEFAULT_PER_PAGE, 1,
                                     requests_admin.MAX_PER_PAGE)
    return jsonify(rows=rows, total=total, page=page, per_page=per_page)


@bp.get("/ui/api/admin/requests/views")
def ui_api_admin_request_views():
    if not auth.is_admin():
        return jsonify(error="admin required"), 403
    import requests_admin
    return jsonify(counts=requests_admin.view_counts())


@bp.get("/ui/api/admin/quotas")
def ui_api_admin_quotas():
    if not auth.is_admin():
        return jsonify(error="admin required"), 403
    import requests_admin
    return jsonify(rows=requests_admin.quota_rows())


@bp.post("/ui/api/user-requests/<int:req_id>/reopen")
def ui_api_user_request_reopen(req_id: int):
    if not auth.is_admin():
        return jsonify(error="admin required"), 403
    if db.reopen_user_request(req_id):
        return jsonify(ok=True, message="back in the pending list")
    return jsonify(ok=False, message="only a denied request can be reopened")


@bp.get("/ui/api/library/<imdb_id>")
def ui_api_library_detail(imdb_id: str):
    if not auth.is_admin():
        return jsonify(error="admin required"), 403
    import library_admin
    d = library_admin.title_detail(imdb_id)
    if d is None:
        return jsonify(error="not found"), 404
    return jsonify(d)


@bp.get("/ui/api/library/<imdb_id>/season/<int:season>")
def ui_api_library_season(imdb_id: str, season: int):
    if not auth.is_admin():
        return jsonify(error="admin required"), 403
    import library_admin
    return jsonify(episodes=library_admin.season_episodes(imdb_id, season))


@bp.get("/ui/api/library/<imdb_id>/activity")
def ui_api_library_activity(imdb_id: str):
    if not auth.is_admin():
        return jsonify(error="admin required"), 403
    req = db.get_request_by_imdb(imdb_id)
    before = request.args.get("before", type=int)
    return jsonify(activity=db.get_activity_for_title(imdb_id, (req or {}).get("title"), limit=20, before_id=before))


@bp.get("/ui/api/library/<imdb_id>/candidates")
def ui_api_library_candidates(imdb_id: str):
    """The candidate releases for a movie, one episode, or (season without
    episode) the season packs for a whole season; a live scrape."""
    if not auth.is_admin():
        return jsonify(error="admin required"), 403
    import release_swap
    req = db.get_request_by_imdb(imdb_id)
    if not req:
        return jsonify(error="not found"), 404
    season = request.args.get("season", type=int)
    episode = request.args.get("episode", type=int)
    ref = release_swap.parse_episode_ref(season, episode)
    if ref is None:
        return jsonify(ok=False, message="season and episode must be whole numbers")
    season, episode = ref
    try:
        return jsonify(release_swap.candidates(imdb_id, req["media_type"], season, episode))
    except release_swap.CandidatesUnavailable as exc:
        return jsonify(error=f"scrapers unavailable: {exc}"), 502


@bp.post("/ui/api/library/<imdb_id>/swap")
def ui_api_library_swap(imdb_id: str):
    if not auth.is_admin():
        return jsonify(error="admin required"), 403
    import release_swap
    p = request.get_json(silent=True) or {}
    ref = release_swap.parse_episode_ref(p.get("season"), p.get("episode"))
    if ref is None:
        return jsonify(ok=False, message="season and episode must be whole numbers")
    season, episode = ref
    return jsonify(**release_swap.swap_by_hash(
        imdb_id, str(p.get("info_hash") or ""), season, episode,
        blacklist_old=bool(p.get("blacklist_old"))))


def _admin_lib_action(fn, *args):
    if not auth.is_admin():
        return jsonify(error="admin required"), 403
    import library_actions
    return jsonify(**getattr(library_actions, fn)(*args))


@bp.post("/ui/api/library/<imdb_id>/mirror")
def ui_api_library_mirror(imdb_id: str):
    return _admin_lib_action("mirror", imdb_id)


@bp.post("/ui/api/library/<imdb_id>/unmirror")
def ui_api_library_unmirror(imdb_id: str):
    return _admin_lib_action("unmirror", imdb_id)


@bp.post("/ui/api/library/<imdb_id>/drop-retry")
def ui_api_library_drop_retry(imdb_id: str):
    return _admin_lib_action("drop_retry", imdb_id)


@bp.post("/ui/api/library/<imdb_id>/retry-now")
def ui_api_library_retry_now(imdb_id: str):
    return _admin_lib_action("retry_now", imdb_id)


@bp.post("/ui/api/library/<imdb_id>/recheck-series")
def ui_api_library_recheck_series(imdb_id: str):
    return _admin_lib_action("recheck_series", imdb_id)


@bp.post("/ui/api/library/<imdb_id>/episodes/<int:season>/<int:episode>/retry")
def ui_api_library_retry_episode(imdb_id: str, season: int, episode: int):
    return _admin_lib_action("retry_episode", imdb_id, season, episode)


@bp.post("/ui/api/library/hash/<info_hash>/blacklist")
def ui_api_library_blacklist(info_hash: str):
    return _admin_lib_action("blacklist", info_hash)


@bp.post("/ui/api/library/hash/<info_hash>/unblacklist")
def ui_api_library_unblacklist(info_hash: str):
    return _admin_lib_action("unblacklist", info_hash)


@bp.post("/ui/api/library/<imdb_id>/playability/reset")
def ui_api_library_reset_playability(imdb_id: str):
    return _admin_lib_action("reset_playability", imdb_id)


@bp.route("/ui/api/library/<imdb_id>/override", methods=["POST", "DELETE"])
def ui_api_library_override(imdb_id: str):
    if request.method == "DELETE":
        return _admin_lib_action("clear_override", imdb_id)
    return _admin_lib_action("save_override", imdb_id, request.get_json(silent=True) or {})


# ── Radarr / Sonarr import ───────────────────────────────────────────────────

@bp.get("/ui/api/arr-import/status")
def ui_api_arr_import_status():
    if not auth.is_admin():
        return jsonify(error="admin required"), 403
    import arr_import
    return jsonify(arr_import.get_status())


@bp.post("/ui/api/arr-import/radarr")
def ui_api_arr_import_radarr():
    if not auth.is_admin():
        return jsonify(error="admin required"), 403
    import arr_import
    only_monitored = (request.get_json(silent=True) or {}).get("only_monitored", True)
    threading.Thread(target=arr_import.import_radarr,
                      kwargs={"only_monitored": only_monitored},
                      name="radarr-import", daemon=True).start()
    return jsonify(ok=True)


@bp.post("/ui/api/arr-import/sonarr")
def ui_api_arr_import_sonarr():
    if not auth.is_admin():
        return jsonify(error="admin required"), 403
    import arr_import
    only_monitored = (request.get_json(silent=True) or {}).get("only_monitored", True)
    threading.Thread(target=arr_import.import_sonarr,
                      kwargs={"only_monitored": only_monitored},
                      name="sonarr-import", daemon=True).start()
    return jsonify(ok=True)


def _arr_values(kind: str) -> dict:
    """The old arr-import body {url, api_key} as schema values."""
    p = request.get_json(silent=True) or {}
    prefix = kind.upper()
    return {f"{prefix}_URL": p.get("url") or "", f"{prefix}_API_KEY": p.get("api_key") or ""}


@bp.post("/ui/api/arr-import/test-radarr")
def ui_api_arr_import_test_radarr():
    """Alias kept for one release; the Settings page uses /ui/api/settings/test/radarr."""
    if not auth.is_admin():
        return jsonify(error="admin required"), 403
    import service_tests
    r = service_tests.run("radarr", _arr_values("radarr"))
    return jsonify(ok=r["ok"], version=r["message"] if r["ok"] else None, error=None if r["ok"] else r["message"])


@bp.post("/ui/api/arr-import/test-sonarr")
def ui_api_arr_import_test_sonarr():
    if not auth.is_admin():
        return jsonify(error="admin required"), 403
    import service_tests
    r = service_tests.run("sonarr", _arr_values("sonarr"))
    return jsonify(ok=r["ok"], version=r["message"] if r["ok"] else None, error=None if r["ok"] else r["message"])


@bp.post("/ui/api/arr-import/root-folders-<kind>")
def ui_api_arr_import_root_folders(kind: str):
    """Alias kept for one release; the Settings page uses /ui/api/settings/picker/<kind>_root_folders."""
    if not auth.is_admin():
        return jsonify(error="admin required"), 403
    if kind not in ("radarr", "sonarr"):
        return jsonify(error="unknown arr"), 404
    import service_tests
    r = service_tests.pick(f"{kind}_root_folders", _arr_values(kind))
    if not r["ok"]:
        return jsonify(ok=False, error=r["error"])
    return jsonify(ok=True, folders=[{"path": o["value"], "free_space": None} for o in r["options"]])
