"""What other services talk to: the health and metrics endpoints and the
inbound webhooks from Seerr, TorBox, Radarr, Sonarr and Jellyfin."""
import hmac
import logging
import threading

from flask import Blueprint, abort, jsonify, request

import auth
import cleanup
import db
import processor
import strm_generator
import webhook_secret
from appcore import _csrf
from config import METRICS_TOKEN
from webhook_parser import IgnoreEvent, WebhookError, parse

log = logging.getLogger("mycelium")

bp = Blueprint("integration", __name__)


# ── Auth ──────────────────────────────────────────────────────────────────────

def _effective_webhook_secret() -> str:
    """Return the active webhook secret: env var takes priority, else auto-generated."""
    return webhook_secret.effective()


def _check_auth() -> None:
    if not webhook_secret.effective():
        return
    header_secret = request.headers.get("X-Webhook-Secret")
    query_secret  = request.args.get("secret")
    provided = header_secret or query_secret
    if query_secret and not header_secret:
        # Deprecated: secret in query string leaks via access logs and proxy history.
        # Migrate to the X-Webhook-Secret header.
        log.warning("Webhook secret passed via ?secret= query param from %s"
                    " - migrate to X-Webhook-Secret header", request.remote_addr)
    matched = webhook_secret.accepts(provided)
    if matched is None:
        log.warning("Rejected webhook with bad/missing secret from %s", request.remote_addr)
        abort(401)
    if matched == "previous":
        # Still inside the rotation grace window: this sender has not been
        # updated yet. Name it so the admin knows what to fix.
        log.warning("Webhook from %s (%s) still uses the previous secret; update it before the grace window ends",
                    request.remote_addr, request.headers.get("User-Agent", "?"))


# ── Webhook ───────────────────────────────────────────────────────────────────

@bp.get("/health")
def health_simple():
    """Liveness probe used by Docker HEALTHCHECK  -  process up + DB reachable."""
    try:
        db.get_recent(1)
        return jsonify(status="ok")
    except Exception:
        return jsonify(status="degraded"), 503


@bp.get("/metrics")
def metrics_export():
    """Prometheus scrape endpoint. Requires admin session or X-Metrics-Token header."""
    if METRICS_TOKEN:
        provided = request.headers.get("X-Metrics-Token") or request.args.get("metrics_token")
        if not provided or not hmac.compare_digest(provided, METRICS_TOKEN):
            abort(401)
    elif not auth.is_admin():
        abort(401)
    import metrics_prom
    from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
    metrics_prom.refresh_gauges()
    return generate_latest(), 200, {"Content-Type": CONTENT_TYPE_LATEST}


@bp.get("/healthz")
def health_deep():
    """Real readiness probe. Returns 503 if DB unreachable OR both scrapers down."""
    import health_cache
    status = "ok"
    failures = []
    try:
        db.get_recent(1)
    except Exception as exc:
        status = "down"
        failures.append(f"db: {exc}")
    zilean_ok = health_cache.is_up("zilean")
    torrentio_ok = health_cache.is_up("torrentio")
    if not zilean_ok and not torrentio_ok:
        status = "down"
        failures.append("no scraper reachable")
    code = 200 if status == "ok" else 503
    return jsonify(status=status, failures=failures,
                    zilean=zilean_ok, torrentio=torrentio_ok), code


@bp.post("/webhook")
@_csrf.exempt
def webhook():
    _check_auth()
    payload = request.get_json(silent=True) or {}
    log.info("Received webhook: notification_type=%s subject=%s",
             payload.get("notification_type"), payload.get("subject"))
    try:
        media_request = parse(payload)
    except IgnoreEvent as exc:
        log.info("Ignoring event: %s", exc)
        return jsonify(status="ignored", reason=str(exc))
    except WebhookError as exc:
        log.error("Bad webhook payload: %s", exc)
        return jsonify(status="error", error=str(exc)), 400

    # Idempotency: dedup by imdb_id + media_type + seasons within DB
    dedup_key = f"{media_request.imdb_id}:{media_request.media_type}:{','.join(map(str, media_request.seasons))}"
    if db.webhook_seen(dedup_key):
        log.info("Webhook duplicate ignored: %s", dedup_key)
        return jsonify(status="duplicate", imdb_id=media_request.imdb_id), 200

    thread = threading.Thread(
        target=processor.process,
        args=(media_request,),
        name=f"process-{media_request.imdb_id}",
        daemon=True,
    )
    thread.start()
    return jsonify(status="accepted", imdb_id=media_request.imdb_id, title=media_request.title), 202


@bp.post("/torbox-webhook")
@_csrf.exempt
def torbox_webhook():
    """Endpoint for TorBox to push completion notifications.
    Triggers strm_generator to catch the newly-ready torrent."""
    _check_auth()
    payload = request.get_json(silent=True) or {}
    log.info("TorBox webhook: %s", payload)
    threading.Thread(target=strm_generator.run_and_refresh, name="torbox-push", daemon=True).start()
    return jsonify(status="ok")


@bp.post("/webhook/arr")
@_csrf.exempt
def arr_webhook_route():
    """Delete notifications from Radarr (MovieDelete), Sonarr (SeriesDelete)
    and the Jellyfin webhook plugin (ItemDeleted). Same secret as /webhook.

    A title Mycelium does not own is answered with "ignored" and no purge:
    that is how the echo of our own mirror_remove, and Jellyfin's ItemDeleted
    after our own purge, are kept from looping."""
    _check_auth()
    import arr_webhook
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify(status="error", error="expected a JSON object"), 400
    try:
        ev = arr_webhook.parse(payload)
    except ValueError as exc:
        log.warning("Arr webhook: %s", exc)
        return jsonify(status="error", error=str(exc)), 400
    if ev is None:
        return jsonify(status="ignored", reason="not a title deletion")
    # Ownership first, locally. Jellyfin fires ItemDeleted for every title in
    # every library, so a tmdb id that matches nothing of ours is answered
    # without a TMDB round trip. Only a payload with neither an imdb nor a
    # tmdb id (Sonarr with tvdb only) still resolves remotely.
    imdb_id = ev.imdb_id or db.imdb_for_tmdb(ev.tmdb_id)
    if not imdb_id and ev.tmdb_id:
        log.info("Arr webhook: %s %s for tmdb %s ignored: unknown title", ev.source, ev.event, ev.tmdb_id)
        return jsonify(status="ignored", reason="unknown title", tmdb_id=ev.tmdb_id)
    if not imdb_id:
        imdb_id = arr_webhook.resolve_imdb(ev)
    if not imdb_id:
        log.warning("Arr webhook: could not resolve %s %s to an imdb id", ev.source, ev.event)
        return jsonify(status="error", error="unresolvable id"), 400
    req_row = db.get_request_by_imdb(imdb_id)
    items = db.get_virtual_items_by_imdb(imdb_id)
    if not req_row and not items:
        log.info("Arr webhook: %s %s for %s ignored: unknown title", ev.source, ev.event, imdb_id)
        return jsonify(status="ignored", reason="unknown title", imdb_id=imdb_id)
    # A targeted refresh can report a repair/upgrade's old path as Deleted while
    # a fresh .strm for the same title still exists. A person deleting in
    # Jellyfin removes the .strm too (the containers share PUID), so only the
    # echo case has files left; arr events hold no files and keep purging.
    if ev.source == "jellyfin" and arr_webhook.files_still_present(items):
        log.info("Arr webhook: %s %s for %s ignored: files still present", ev.source, ev.event, imdb_id)
        return jsonify(status="ignored", reason="files still present", imdb_id=imdb_id)
    log.info("Arr webhook: %s %s -> purging %s", ev.source, ev.event, imdb_id)
    threading.Thread(
        target=cleanup.purge_title,
        args=(imdb_id,), kwargs={"row_id": req_row["id"] if req_row else None},
        name=f"arr-purge-{imdb_id}", daemon=True,
    ).start()
    return jsonify(status="accepted", imdb_id=imdb_id, source=ev.source), 202
