"""The rest of the admin surface: health and stats JSON, settings, the
request queue, TorBox accounts, users and the service testers."""
import logging
import re
import threading

from flask import Blueprint, abort, jsonify, redirect, request, url_for

import auth
import auto_approve
import cleanup
import config as cfg
import db
import health
import library_sync
import log_buffer
import nfo_generator
import notify
import overview
import plugin_loader
import processor
import quota
import recovery
import scrapers
import shell_summary
import stats
import strm_generator
import tmdb
import torbox
import trending
import upgrader
import webhook_secret
from appcore import limiter
from routes._common import _login_flags, invalidate_series_episodes_cache
from version import RELEASES
from webhook_parser import MediaRequest

log = logging.getLogger("mycelium")

bp = Blueprint("admin_misc", __name__)


# ── New JSON APIs ─────────────────────────────────────────────────────────────

@bp.get("/ui/api/health")
def ui_api_health():
    # stream_front is live truth, not an env echo: the Go front stamps
    # X-Stream-Front on everything it proxies (and overwrites any client-sent
    # value), so if this request carries it, streams are being served by Go.
    return jsonify(services=health.check_all(),
                   stream_front=request.headers.get("X-Stream-Front") == "1")


@bp.get("/ui/api/webhook-secret")
def ui_api_webhook_secret():
    """Return the effective webhook secret for display in the admin UI. Admin only."""
    if not auth.is_admin():
        return jsonify(error="unauthorized"), 401
    return jsonify(**webhook_secret.status())


@bp.post("/ui/api/webhook-secret/rotate")
def ui_api_webhook_secret_rotate():
    """Issue a new webhook secret; the previous one keeps working for the
    grace window so Seerr and the arrs can be updated one by one."""
    if not auth.is_admin():
        return jsonify(error="unauthorized"), 401
    try:
        return jsonify(**webhook_secret.rotate())
    except RuntimeError as exc:
        return jsonify(error=str(exc)), 409


@bp.get("/ui/api/stats")
def ui_api_stats():
    return jsonify(stats.get_overview())


@bp.get("/ui/api/overview")
def ui_api_overview():
    """Everything the admin Overview reads from the database, in one call."""
    if not auth.is_admin():
        return jsonify(error="admin required"), 403
    return jsonify(overview.get())


@bp.get("/ui/api/storage")
def ui_api_storage():
    return jsonify(folders=stats.get_storage_breakdown(30))


@bp.get("/ui/api/activity")
def ui_api_activity():
    return jsonify(events=db.get_activity(50))


@bp.get("/ui/api/releases")
def ui_api_releases():
    """Release changelog for the admin Overview tab. Every /ui/api/ route is
    already behind the global auth gate, and the changelog carries no
    operator-sensitive data, so plain auth is enough here."""
    return jsonify(releases=RELEASES)


@bp.get("/ui/api/repair")
def ui_api_repair():
    """Repair history for the Maintenance tab, so it can refresh in place.

    Admin-only: repair items carry filesystem paths, and the tab that renders
    them is behind the admin gate already.
    """
    if not auth.is_admin():
        return jsonify(error="admin required"), 403
    return jsonify(stats.get_repair_overview())


@bp.get("/ui/api/shell-summary")
def ui_api_shell_summary():
    """Sidebar counts and the topbar TorBox pill, in one call."""
    user = auth.current_user_record()
    return jsonify(shell_summary.get_shell_summary((user or {}).get("id")))


@bp.get("/ui/api/me/quota")
def ui_api_me_quota():
    """Monthly request quota for the current user, for the Requests page."""
    return jsonify(quota.get_quota(auth.current_user_record()))


@bp.get("/ui/api/scraper-health")
def ui_api_scraper_health():
    """Rolling latency and state per active scraper, for the admin tab."""
    if not auth.is_admin():
        return jsonify(error="admin required"), 403
    import scrapers as _scrapers
    return jsonify(scrapers=_scrapers.health_rows())


@bp.get("/ui/api/logs")
def ui_api_logs():
    """Structured log feed for the admin Logs tab; polls at 5s while visible."""
    if not auth.is_admin():
        return jsonify(error="admin required"), 403
    limit = request.args.get("limit", default=200, type=int)
    level = request.args.get("level") or None
    return jsonify(lines=log_buffer.get_structured(limit=limit, min_level=level))


@bp.get("/ui/api/torbox-list")
def ui_api_torbox_list():
    try:
        import torbox_pool
        out = []
        for acct in torbox_pool.accounts():
            for t in torbox.list_torrents(acct.id):
                out.append({
                    "id": t.get("id"),
                    "name": t.get("name"),
                    "hash": t.get("hash"),
                    "size": t.get("size"),
                    "download_state": t.get("download_state"),
                    "download_finished": t.get("download_finished"),
                    "progress": t.get("progress"),
                    "created_at": t.get("created_at"),
                    "file_count": len(t.get("files") or []),
                    "account": acct.id,
                })
        return jsonify(torrents=out)
    except Exception as exc:
        return jsonify(error=str(exc)), 500


@bp.post("/ui/torbox-delete")
def ui_torbox_delete():
    if not auth.is_admin():
        abort(403)
    torrent_id = request.form.get("torrent_id")
    if not torrent_id:
        return jsonify(error="missing torrent_id"), 400
    import torbox_pool
    account_param = request.form.get("account")
    if account_param:
        account_id = int(account_param)
    else:
        accts = torbox_pool.accounts()
        if not accts:
            return jsonify(error="no enabled TorBox account"), 503
        account_id = accts[0].id
    ok = torbox.delete_torrent(account_id, int(torrent_id))
    if not ok:
        log.warning("torbox-delete: failed to delete torrent %s (account=%s)", torrent_id, account_id)
    return redirect(url_for("admin_library.ui_dashboard") + "#torbox")


@bp.post("/ui/strm-rescan")
def ui_strm_rescan():
    if not auth.is_admin():
        abort(403)
    threading.Thread(target=strm_generator.run_and_refresh, name="strm-manual", daemon=True).start()
    return redirect(url_for("admin_library.ui_dashboard"))


@bp.post("/ui/test-notify")
def ui_test_notify():
    if not auth.is_admin():
        return jsonify(error="admin required"), 403
    results = notify.test()
    return jsonify(results)


@bp.post("/ui/api/search-candidates")
def ui_api_search_candidates():
    if not auth.is_admin():
        return jsonify(error="admin required"), 403
    imdb_id = (request.form.get("imdb_id") or "").strip()
    media_type = request.form.get("media_type", "movie")
    season = int(request.form.get("season", 1))
    episode = int(request.form.get("episode", 1))
    if not re.fullmatch(r"tt\d{6,10}", imdb_id):
        return jsonify(error="invalid imdb id"), 400

    if media_type == "movie":
        candidates = scrapers.fetch_candidates("movie", imdb_id)
    else:
        candidates = scrapers.fetch_candidates("series", imdb_id, season=season, episode=episode)

    cached_hashes = torbox.check_cached([c.info_hash for c in candidates[:30]]) if candidates else set()
    out = [{
        "name": c.name,
        "info_hash": c.info_hash,
        "magnet": c.magnet,
        "quality": c.quality,
        "size": c.size,
        "seeders": c.seeders,
        "is_season_pack": getattr(c, "is_season_pack", False),
        "cached": c.info_hash in cached_hashes,
    } for c in candidates[:30]]
    return jsonify(candidates=out)


@bp.post("/ui/add-magnet")
def ui_add_magnet():
    if not auth.is_admin():
        abort(403)
    magnet = (request.form.get("magnet") or "").strip()
    if not magnet.startswith("magnet:"):
        return redirect(url_for("admin_library.ui_dashboard") + "#search")
    try:
        import torbox_pool
        acct = torbox_pool.choose_for_add().id
        torbox.add_magnet(acct, magnet, reason="manual")
        threading.Thread(target=strm_generator.run_and_refresh, name="strm-after-add", daemon=True).start()
    except Exception as exc:
        log.warning("add-magnet failed: %s", exc)
    return redirect(url_for("admin_library.ui_dashboard") + "#search")


@bp.get("/ui/api/poster/<imdb_id>")
def ui_api_poster(imdb_id: str):
    media_type = request.args.get("type", "movie")
    path = tmdb.get_poster_path(imdb_id, media_type)
    return jsonify(poster=f"https://image.tmdb.org/t/p/w154{path}" if path else None)


@bp.get("/ui/api/person/<int:person_id>")
def ui_api_person(person_id: int):
    """Actor/person detail: bio + combined filmography, for the clickable-cast view."""
    person = tmdb.person_details(person_id)
    if not person:
        return jsonify(error="not found"), 404
    return jsonify(**person)


@bp.get("/ui/api/favorite-actors")
@auth.require_auth
def ui_api_favorite_actors_list():
    rec = auth.current_user_record()
    if not rec:
        return jsonify(error="not authenticated"), 401
    return jsonify(actors=db.get_favorite_actors(rec["id"]))


@bp.post("/ui/api/favorite-actors/<int:person_id>")
@auth.require_auth
def ui_api_favorite_actors_add(person_id: int):
    rec = auth.current_user_record()
    if not rec:
        return jsonify(error="not authenticated"), 401
    p = request.get_json(silent=True) or {}
    db.add_favorite_actor(rec["id"], person_id, p.get("name") or str(person_id), p.get("profile_path"))
    return jsonify(ok=True)


@bp.post("/ui/api/favorite-actors/<int:person_id>/remove")
@auth.require_auth
def ui_api_favorite_actors_remove(person_id: int):
    rec = auth.current_user_record()
    if not rec:
        return jsonify(error="not authenticated"), 401
    db.remove_favorite_actor(rec["id"], person_id)
    return jsonify(ok=True)


@bp.get("/ui/api/genres")
def ui_api_genres():
    media_type = request.args.get("type", "movie")
    return jsonify(genres=tmdb.list_genres(media_type))


@bp.get("/ui/api/auto-approve/genre-rules")
@auth.require_auth
def ui_api_auto_approve_genre_rules_get():
    if not auth.is_admin():
        return jsonify(error="unauthorized"), 401
    return jsonify(rules=auto_approve._genre_rules())


@bp.post("/ui/api/auto-approve/genre-rules")
@auth.require_auth
def ui_api_auto_approve_genre_rules_set():
    if not auth.is_admin():
        return jsonify(error="unauthorized"), 401
    p = request.get_json(silent=True) or {}
    rules = p.get("rules")
    if not isinstance(rules, list):
        return jsonify(error="rules must be a list"), 400
    auto_approve.set_genre_rules(rules)
    return jsonify(ok=True)


@bp.post("/ui/api/auto-approve/run-now")
@auth.require_auth
def ui_api_auto_approve_run_now():
    if not auth.is_admin():
        return jsonify(error="unauthorized"), 401
    import threading
    threading.Thread(target=auto_approve.run, name="auto-approve-manual", daemon=True).start()
    return jsonify(ok=True, started=True)


# ── Upgrader / consolidation / trending triggers ──────────────────────────────

@bp.post("/ui/auto-upgrade")
def ui_auto_upgrade():
    if not auth.is_admin():
        abort(403)
    threading.Thread(target=upgrader.run_auto_upgrade, name="upgrade-manual", daemon=True).start()
    return redirect(url_for("admin_library.ui_dashboard") + "#overview")


@bp.post("/ui/pack-consolidate")
def ui_pack_consolidate():
    if not auth.is_admin():
        abort(403)
    threading.Thread(target=upgrader.run_pack_consolidation, name="pack-manual", daemon=True).start()
    return redirect(url_for("admin_library.ui_dashboard") + "#overview")


@bp.get("/ui/api/settings")
def ui_api_settings():
    if not auth.is_admin():
        return jsonify(error="admin required"), 403
    import settings
    return jsonify(groups=settings.all_for_ui(), hot_reload=list(settings.HOT_RELOAD))


@bp.get("/ui/api/settings/schema")
def ui_api_settings_schema():
    """The schema-driven Settings page: sections, fields, copy, values."""
    if not auth.is_admin():
        return jsonify(error="admin required"), 403
    import settings
    return jsonify(sections=settings.schema_for_ui(), hot_reload=list(settings.HOT_RELOAD))


_NOTIFICATION_KEYS = {"NOTIFY_ON_SUCCESS", "NOTIFY_ON_FAILURE",
                      "DISCORD_WEBHOOK_URL", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"}


@bp.post("/ui/api/settings/notifications")
@auth.require_auth
def ui_api_settings_notifications_set():
    """Focused write endpoint for the React Settings page's Notifications card."""
    if not auth.is_admin():
        return jsonify(error="unauthorized"), 401
    import settings as _s
    p = request.get_json(silent=True) or {}
    for key, value in p.items():
        if key not in _NOTIFICATION_KEYS:
            continue
        if key in _s._BOOL_KEYS:
            _s.set(key, bool(value))
        else:
            _s.set(key, value)
    return jsonify(ok=True)


@bp.post("/ui/settings")
def ui_save_settings():
    if not auth.is_admin():
        abort(403)
    import settings
    saved = 0
    for raw_key, raw_value in request.form.items():
        if not raw_key.startswith("setting_"):
            continue
        key = raw_key[8:]
        # Checkbox semantics: only the box's value if checked; we emit hidden "false"
        # before each checkbox so the value always arrives. Handle multi-value here.
        values = request.form.getlist(raw_key)
        value = values[-1] if values else raw_value
        try:
            if key in settings._BOOL_KEYS:
                settings.set(key, str(value).lower() in ("1", "true", "yes", "on"))
            elif value == "":
                settings.set(key, None)
            else:
                settings.set(key, value)
            saved += 1
        except ValueError as exc:
            log.warning("settings save rejected %s: %s", key, exc)
    return redirect(url_for("admin_library.ui_dashboard") + "#settings")


@bp.get("/ui/api/orphans")
def ui_api_orphans():
    return jsonify(library_sync.orphans())


def _library_import_and_resolve():
    library_sync.import_existing()
    library_sync.resolve_unknowns()
    library_sync.import_series_to_monitored()
    nfo_generator.generate_all()
    nfo_generator.fetch_local_images()


@bp.post("/ui/library-import")
def ui_library_import():
    if not auth.is_admin():
        abort(403)
    threading.Thread(target=_library_import_and_resolve,
                     name="lib-import", daemon=True).start()
    return redirect(url_for("admin_library.ui_dashboard") + "#overview")


@bp.post("/ui/recovery")
def ui_recovery():
    if not auth.is_admin():
        abort(403)
    threading.Thread(target=recovery.run, name="recovery-wizard", daemon=True).start()
    return redirect(url_for("admin_library.ui_dashboard") + "#overview")


@bp.post("/ui/db-vacuum")
def ui_db_vacuum():
    if not auth.is_admin():
        abort(403)
    threading.Thread(target=db.vacuum, name="db-vacuum", daemon=True).start()
    return redirect(url_for("admin_library.ui_dashboard") + "#overview")


@bp.post("/ui/api/retry-queue/clear")
@auth.require_role("admin")
def ui_api_clear_retry_queue():
    """Empty the retry queue. Visible in the dashboard but until now with no
    way to act on it."""
    removed = db.clear_retry_queue()
    log.info("Retry queue cleared by admin: %d row(s) removed", removed)
    return jsonify(ok=True, removed=removed)


@bp.get("/ui/api/retry-queue")
def ui_api_retry_queue():
    return jsonify(items=db.get_pending_retries())


@bp.get("/ui/api/requests/status")
def ui_api_request_status():
    imdb_id = request.args.get("imdb_id")
    if not imdb_id:
        return jsonify(error="imdb_id required"), 400
    row = db.get_request_by_imdb(imdb_id)
    if not row:
        return jsonify(status="not_found")
    return jsonify(status=row.get("status"), imdb_id=imdb_id)


@bp.get("/ui/api/requests/failed")
def ui_api_failed_requests():
    # Every logged-in user polls this; filter in SQL (indexed on status)
    # instead of pulling 500 full rows per poll and filtering in Python.
    return jsonify(items=db.get_failed_requests(50))


@bp.post("/ui/api/requests/<int:row_id>/retry")
def ui_api_retry_request(row_id: int):
    if not auth.is_admin():
        return jsonify(error="admin required"), 403
    r = db.get_request(row_id)
    if not r:
        return jsonify(error="not found"), 404
    seasons = [int(s) for s in (r.get("seasons") or "").split(",") if s.strip().isdigit()]
    media_request = MediaRequest(
        title=r["title"], media_type=r["media_type"], imdb_id=r["imdb_id"], seasons=seasons,
    )
    db.set_request_status(row_id, "pending")
    threading.Thread(target=processor.process, args=(media_request,),
                     name=f"retry-{r['imdb_id']}", daemon=True).start()
    return jsonify(ok=True, title=r["title"])


@bp.post("/ui/api/requests/<int:row_id>/delete")
def ui_api_delete_request(row_id: int):
    """Forget the request record. Leaves the .strm files in the library.

    Also drops the webhook dedup keys for this title: without that, requesting
    it again within 24h is silently answered "duplicate" and never processed."""
    if not auth.is_admin():
        return jsonify(error="admin required"), 403
    if not db.delete_request(row_id):
        return jsonify(error="not found"), 404
    return jsonify(ok=True)


@bp.post("/ui/api/requests/<int:row_id>/purge")
def ui_api_purge_request(row_id: int):
    """Remove the title from the library: .strm files, virtual_items, the
    monitoring rows that would regenerate them, and the request itself."""
    if not auth.is_admin():
        return jsonify(error="admin required"), 403
    r = db.get_request(row_id)
    if not r:
        return jsonify(error="not found"), 404
    imdb_id = r["imdb_id"]
    import cleanup
    result = cleanup.purge_title(imdb_id, row_id=row_id)
    invalidate_series_episodes_cache()
    db.log_activity("purged", r["title"],
                    f"{result['strms']} strm(s) removed ({imdb_id})", True, imdb_id=imdb_id)
    return jsonify(ok=True, **result)


@bp.get("/ui/api/torbox-usage")
def ui_api_torbox_usage():
    import torbox_pool
    # Reports the first enabled account only; usage and plan per account
    # is not broken out here yet.
    accts = torbox_pool.accounts()
    if not accts:
        return jsonify(error="no enabled TorBox account"), 503
    acct_id = accts[0].id
    try:
        summary = torbox.get_usage_summary(acct_id)
    except torbox.AuthFailed as exc:
        log.warning("torbox-usage: account %s auth failed: %s", acct_id, exc)
        summary = {"torrent_count": 0, "total_bytes": 0, "total_gb": 0, "states": {}}
    try:
        user = torbox.get_user_info(acct_id) or {}
    except torbox.AuthFailed as exc:
        log.warning("torbox-usage: account %s auth failed: %s", acct_id, exc)
        user = {}
    return jsonify(usage=summary, plan=user.get("plan") if isinstance(user, dict) else None)


@bp.get("/ui/api/torbox-accounts")
def ui_api_torbox_accounts():
    if not auth.is_admin():
        return jsonify(error="admin required"), 403
    import torbox_accounts_api
    return jsonify(accounts=torbox_accounts_api.list_accounts())


@bp.post("/ui/api/torbox-accounts")
def ui_api_torbox_accounts_add():
    if not auth.is_admin():
        return jsonify(error="admin required"), 403
    import torbox_accounts_api
    p = request.get_json(silent=True) or {}
    return jsonify(**torbox_accounts_api.add(str(p.get("label") or ""), str(p.get("api_key") or "")))


@bp.post("/ui/api/torbox-accounts/<int:account_id>")
def ui_api_torbox_accounts_update(account_id: int):
    if not auth.is_admin():
        return jsonify(error="admin required"), 403
    import torbox_accounts_api
    p = request.get_json(silent=True) or {}
    return jsonify(**torbox_accounts_api.update(
        account_id, label=p.get("label"), api_key=p.get("api_key"),
        enabled=None if p.get("enabled") is None else bool(p.get("enabled"))))


@bp.delete("/ui/api/torbox-accounts/<int:account_id>")
def ui_api_torbox_accounts_delete(account_id: int):
    if not auth.is_admin():
        return jsonify(error="admin required"), 403
    import torbox_accounts_api
    return jsonify(**torbox_accounts_api.delete(account_id))


@bp.post("/ui/api/torbox-accounts/<int:account_id>/test")
def ui_api_torbox_accounts_test(account_id: int):
    if not auth.is_admin():
        return jsonify(error="admin required"), 403
    import torbox_accounts_api
    return jsonify(**torbox_accounts_api.test(account_id))


@bp.get("/ui/api/metrics-summary")
def ui_api_metrics_summary():
    return jsonify(
        quality=db.get_metric_summary("quality_added", days=30),
        sources=db.get_metric_summary("source_win", days=30),
        unique_sources=db.get_metric_summary("source_unique_win", days=30),
        latency=db.get_metric_summary("latency_seconds", days=30),
        failures=db.get_metric_summary("request_failed", days=30),
    )


@bp.get("/ui/api/show-overrides")
def ui_api_show_overrides():
    return jsonify(items=db.get_all_show_overrides())


@bp.post("/ui/show-override")
def ui_show_override():
    if not auth.is_admin():
        abort(403)
    imdb_id = (request.form.get("imdb_id") or "").strip()
    if not re.fullmatch(r"tt\d{6,10}", imdb_id):
        return redirect(url_for("admin_library.ui_dashboard") + "#overrides")
    quality = request.form.get("quality_preference") or None
    allow_4k_raw = request.form.get("allow_4k")
    prefer_hevc_raw = request.form.get("prefer_hevc")
    allow_4k = None if not allow_4k_raw else allow_4k_raw == "true"
    prefer_hevc = None if not prefer_hevc_raw else prefer_hevc_raw == "true"
    notes = request.form.get("notes") or None
    db.upsert_show_override(imdb_id, quality, allow_4k, prefer_hevc, notes)
    return redirect(url_for("admin_library.ui_dashboard") + "#overrides")


@bp.post("/ui/show-override-delete/<imdb_id>")
def ui_show_override_delete(imdb_id: str):
    if not auth.is_admin():
        abort(403)
    db.delete_show_override(imdb_id)
    return redirect(url_for("admin_library.ui_dashboard") + "#overrides")


@bp.get("/ui/api/session")
def ui_api_session():
    """Current session info: who am I, what role, do I have auto_approve.
    Also carries the login flags (oidc_enabled, oidc_provider,
    password_enabled) for consumers that already hold a session; the React
    login page itself cannot rely on this endpoint (it 401s pre-auth) and
    reads the same flags from the SPA index's meta tags instead, see
    _login_flags() / _spa_index()."""
    rec = auth.current_user_record()
    if not rec:
        return jsonify(authenticated=False, user=None, **_login_flags())
    import settings as _settings
    # region: a real users-table row (rec["id"] >= 1) carries its own region
    # column. The legacy single-user login's shim (id=0, auth.py:170) has no
    # such column - its choice lives in the LEGACY_USER_REGION runtime
    # setting instead (see ui_api_me_region below). Either way, a value that
    # was never set falls back to "US", not the old hardcoded "NL".
    if rec.get("id"):
        region = rec.get("region") or "US"
    else:
        region = rec.get("region") or _settings.get("LEGACY_USER_REGION", "US")
    user: dict = {
        "id": rec.get("id"),
        "username": rec.get("username"),
        "role": rec.get("role"),
        "auto_approve": bool(rec.get("auto_approve")),
        "region": region,
        "library_click_jellyfin": bool(rec.get("library_click_jellyfin")),
        "discover_language_include": rec.get("discover_language_include") or "",
        "discover_language_exclude": rec.get("discover_language_exclude") or "",
    }
    user.update(plugin_loader.session_fields(rec))
    jellyfin_url = (_settings.get("JELLYFIN_URL") or cfg.JELLYFIN_URL or "").rstrip("/")
    return jsonify(authenticated=True, user=user, jellyfin_url=jellyfin_url or None,
                   **_login_flags())


@bp.get("/ui/api/plugins")
def ui_api_plugins():
    return jsonify(plugins=plugin_loader.loaded_plugins())


@bp.get("/ui/api/users")
def ui_api_users():
    if not auth.is_admin():
        return jsonify(error="admin required"), 403
    return jsonify(users=db.list_users())


@bp.post("/ui/api/users/create")
def ui_api_users_create():
    import settings as _settings
    # Bootstrap: only allow unauthenticated first-admin creation when no users exist AND
    # SETUP_COMPLETE has never been set. This prevents re-opening the window if all
    # users are somehow deleted after initial setup.
    setup_done = bool(_settings.get("SETUP_COMPLETE", False))
    if db.user_count() == 0 and not setup_done:
        p = request.get_json(silent=True) or {}
        username = (p.get("username") or "").strip()
        password = p.get("password") or ""
        if not username or len(password) < 4:
            return jsonify(error="username + password (≥4 chars) required"), 400
        try:
            uid = auth.create_user_account(username, password, role="admin",
                                            auto_approve=True)
            _settings.set("SETUP_COMPLETE", True)
            log.info("Bootstrap: first admin '%s' created, setup_complete=true", username)
            return jsonify(ok=True, user_id=uid, message="first admin created")
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
    if not auth.is_admin():
        return jsonify(error="admin required"), 403
    p = request.get_json(silent=True) or {}
    username = (p.get("username") or "").strip()
    password = p.get("password") or ""
    role = p.get("role") or "user"
    auto = bool(p.get("auto_approve"))
    if not username or len(password) < 4:
        return jsonify(error="username + password (≥4 chars) required"), 400
    try:
        uid = auth.create_user_account(username, password, role=role, auto_approve=auto)
        return jsonify(ok=True, user_id=uid)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400


@bp.post("/ui/api/users/<int:user_id>/update")
def ui_api_users_update(user_id: int):
    if not auth.is_admin():
        return jsonify(error="admin required"), 403
    p = request.get_json(silent=True) or {}
    fields: dict = {}
    if "role" in p: fields["role"] = p["role"]
    if "quota_monthly" in p: fields["quota_monthly"] = int(p["quota_monthly"])
    if "auto_approve" in p: fields["auto_approve"] = 1 if p["auto_approve"] else 0
    if "enabled" in p: fields["enabled"] = 1 if p["enabled"] else 0
    if "region" in p: fields["region"] = str(p["region"]).upper()[:5]
    for field in plugin_loader.user_fields():
        if field in p: fields[field] = 1 if p[field] else 0
    if p.get("password"):
        if len(p["password"]) < 4:
            return jsonify(error="password too short"), 400
        fields["password_hash"] = auth.hash_password(p["password"])
    db.update_user(user_id, **fields)
    return jsonify(ok=True)


@bp.post("/ui/api/users/<int:user_id>/delete")
def ui_api_users_delete(user_id: int):
    if not auth.is_admin():
        return jsonify(error="admin required"), 403
    db.delete_user(user_id)
    return jsonify(ok=True)


# ── Auto-add now (trigger immediately) ───────────────────────────────────────

@bp.post("/ui/api/auto-add-now")
def ui_api_auto_add_now():
    if not auth.is_admin():
        return jsonify(error="admin required"), 403
    threading.Thread(target=trending.run, name="auto-add-manual", daemon=True).start()
    return jsonify(ok=True, message="auto-add started in background")


@bp.post("/ui/api/settings/test/<service>")
@limiter.limit("30 per minute")
def ui_api_settings_test(service: str):
    """Test one integration with the values as typed on the Settings page.
    Body: {"values": {KEY: value}}. Blank values fall back to saved ones."""
    if not auth.is_admin():
        return jsonify(error="admin required"), 403
    import service_tests
    if service not in service_tests.TESTS:
        return jsonify(ok=False, message="unknown service"), 404
    p = request.get_json(silent=True) or {}
    return jsonify(**service_tests.run(service, p.get("values") or {}))


@bp.post("/ui/api/settings/picker/<name>")
@limiter.limit("30 per minute")
def ui_api_settings_picker(name: str):
    """Options for a field whose values come from a service, for example
    Radarr's root folders. Body: {"values": {KEY: value}}."""
    if not auth.is_admin():
        return jsonify(error="admin required"), 403
    import service_tests
    if name not in service_tests.PICKERS:
        return jsonify(ok=False, error="unknown picker"), 404
    p = request.get_json(silent=True) or {}
    return jsonify(**service_tests.pick(name, p.get("values") or {}))
