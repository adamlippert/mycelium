"""One tester per credentialed service and one picker per remote list.

Both the Settings page (POST /ui/api/settings/test/<service>, with the
values as typed) and the setup wizard (POST /setup/test/<kind>) call
run(); the pickers feed the root folder and quality profile dropdowns.
Every function takes the field values as a dict; a blank value falls back
to the saved setting so an untouched secret box still works. Messages
never contain a credential. Nothing here raises past run() or pick().
"""
from __future__ import annotations

import logging

import requests

import config
import settings as _settings

log = logging.getLogger(__name__)

TIMEOUT = 8


def _http(method: str, url: str, **kw):
    """The one HTTP seam; tests replace it."""
    kw.setdefault("timeout", TIMEOUT)
    return requests.request(method, url, **kw)


def _pg_connect(**kw):
    import psycopg2
    return psycopg2.connect(**kw)


def _v(values: dict, key: str) -> str:
    typed = str(values.get(key) or "").strip()
    if typed:
        return typed
    saved = _settings.get(key, getattr(config, key, ""))
    return str(saved or "").strip()


def _need(values: dict, *keys: str) -> str | None:
    """Name of the first blank required field, or None."""
    for k in keys:
        if not _v(values, k):
            return k.replace("_", " ").lower()
    return None


def _status(r) -> str:
    return f"HTTP {r.status_code}"


def _json(r) -> dict:
    try:
        body = r.json()
        return body if isinstance(body, dict) else {}
    except ValueError:
        return {}


def test_torbox(v: dict) -> dict:
    if (m := _need(v, "TORBOX_API_KEY")):
        return {"ok": False, "message": f"{m} is empty"}
    base = (_v(v, "TORBOX_BASE_URL") or config.TORBOX_BASE_URL).rstrip("/")
    r = _http("GET", f"{base}/torrents/mylist", headers={"Authorization": f"Bearer {_v(v, 'TORBOX_API_KEY')}"})
    if r.status_code < 400:
        n = len((_json(r).get("data") or []))
        return {"ok": True, "message": f"TorBox key accepted, {n} torrents in your library"}
    return {"ok": False, "message": f"TorBox refused the key ({_status(r)})"}


def test_realdebrid(v: dict) -> dict:
    if (m := _need(v, "REALDEBRID_API_KEY")):
        return {"ok": False, "message": f"{m} is empty"}
    r = _http("GET", "https://api.real-debrid.com/rest/1.0/user",
              headers={"Authorization": f"Bearer {_v(v, 'REALDEBRID_API_KEY')}"})
    if r.status_code < 400:
        d = _json(r)
        return {"ok": True, "message": f"{d.get('username', 'user')}, {d.get('type', '')} until {str(d.get('expiration', ''))[:10]}".strip()}
    return {"ok": False, "message": f"RealDebrid refused the token ({_status(r)})"}


def test_tmdb(v: dict) -> dict:
    if (m := _need(v, "TMDB_API_KEY")):
        return {"ok": False, "message": f"{m} is empty"}
    r = _http("GET", "https://api.themoviedb.org/3/configuration",
              headers={"Authorization": f"Bearer {_v(v, 'TMDB_API_KEY')}", "Accept": "application/json"})
    if r.status_code < 400:
        return {"ok": True, "message": "TMDB key accepted"}
    return {"ok": False, "message": f"TMDB refused the key ({_status(r)})"}


def test_zilean(v: dict) -> dict:
    if (m := _need(v, "ZILEAN_URL")):
        return {"ok": False, "message": f"{m} is empty"}
    r = _http("GET", f"{_v(v, 'ZILEAN_URL').rstrip('/')}/healthcheck")
    return {"ok": r.status_code < 400, "message": f"Zilean answered {_status(r)}"}


def test_zilean_pg(v: dict) -> dict:
    if (m := _need(v, "ZILEAN_PG_HOST")):
        return {"ok": False, "message": f"{m} is empty"}
    try:
        port = int(_v(v, "ZILEAN_PG_PORT") or 5432)
    except ValueError:
        return {"ok": False, "message": "postgres port is not a number"}
    try:
        with _pg_connect(host=_v(v, "ZILEAN_PG_HOST"), port=port, dbname=_v(v, "ZILEAN_PG_DB") or "zilean",
                         user=_v(v, "ZILEAN_PG_USER") or "postgres", password=_v(v, "ZILEAN_PG_PASSWORD"),
                         connect_timeout=TIMEOUT) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT version()")
                version = (cur.fetchone() or [""])[0]
        return {"ok": True, "message": str(version).split(" on ")[0] or "connected"}
    except Exception as exc:
        return {"ok": False, "message": f"could not connect: {str(exc).strip()[:120]}"}


def test_debridio(v: dict) -> dict:
    import base64
    import json
    if (m := _need(v, "DEBRIDIO_API_KEY")):
        return {"ok": False, "message": f"{m} is empty"}
    base = (_v(v, "DEBRIDIO_BASE_URL") or config.DEBRIDIO_BASE_URL).rstrip("/")
    token = base64.urlsafe_b64encode(json.dumps({"api_key": _v(v, "DEBRIDIO_API_KEY"), "provider": "torbox"}).encode()).decode().rstrip("=")
    r = _http("GET", f"{base}/{token}/manifest.json")
    if r.status_code < 400:
        d = _json(r)
        return {"ok": True, "message": f"{d.get('name', 'Debridio')} {d.get('version', '')}".strip()}
    return {"ok": False, "message": f"Debridio refused the key ({_status(r)})"}


def test_jellyfin(v: dict) -> dict:
    if (m := _need(v, "JELLYFIN_URL")):
        return {"ok": False, "message": f"{m} is empty"}
    key = _v(v, "JELLYFIN_API_KEY")
    r = _http("GET", f"{_v(v, 'JELLYFIN_URL').rstrip('/')}/System/Info/Public", headers={"X-Emby-Token": key} if key else {})
    if r.status_code < 400:
        d = _json(r)
        return {"ok": True, "message": f"{d.get('ServerName', 'Jellyfin')} {d.get('Version', '')}".strip()}
    return {"ok": False, "message": f"Jellyfin answered {_status(r)}"}


def test_seerr(v: dict) -> dict:
    if (m := _need(v, "SEERR_URL")):
        return {"ok": False, "message": f"{m} is empty"}
    key = _v(v, "SEERR_API_KEY")
    r = _http("GET", f"{_v(v, 'SEERR_URL').rstrip('/')}/api/v1/status", headers={"X-Api-Key": key} if key else {})
    if r.status_code < 400:
        return {"ok": True, "message": f"Seerr {_json(r).get('version', '')}".strip()}
    return {"ok": False, "message": f"Seerr answered {_status(r)}"}


def _test_arr(kind: str, v: dict) -> dict:
    p = kind.upper()
    name = kind.capitalize()
    if (m := _need(v, f"{p}_URL", f"{p}_API_KEY")):
        return {"ok": False, "message": f"{m} is empty"}
    base, headers = _v(v, f"{p}_URL").rstrip("/"), {"X-Api-Key": _v(v, f"{p}_API_KEY")}
    r = _http("GET", f"{base}/api/v3/system/status", headers=headers)
    if r.status_code >= 400:
        return {"ok": False, "message": f"{name} refused the API key ({_status(r)})"}
    version = _json(r).get("version", "")
    resource, noun = ("movie", "movies") if kind == "radarr" else ("series", "series")
    listing = _http("GET", f"{base}/api/v3/{resource}", headers=headers)
    count = len(listing.json() or []) if listing.status_code < 400 else 0
    return {"ok": True, "message": f"{name} {version}, {count} {noun}"}


def test_radarr(v: dict) -> dict:
    return _test_arr("radarr", v)


def test_sonarr(v: dict) -> dict:
    return _test_arr("sonarr", v)


def test_trakt(v: dict) -> dict:
    if (m := _need(v, "TRAKT_CLIENT_ID")):
        return {"ok": False, "message": f"{m} is empty"}
    r = _http("GET", "https://api.trakt.tv/movies/trending",
              headers={"trakt-api-key": _v(v, "TRAKT_CLIENT_ID"), "trakt-api-version": "2"})
    return {"ok": r.status_code < 400, "message": "Trakt client id accepted" if r.status_code < 400 else f"Trakt refused the client id ({_status(r)})"}


def test_opensubtitles(v: dict) -> dict:
    if (m := _need(v, "OPENSUBTITLES_API_KEY")):
        return {"ok": False, "message": f"{m} is empty"}
    r = _http("GET", "https://api.opensubtitles.com/api/v1/infos/user",
              headers={"Api-Key": _v(v, "OPENSUBTITLES_API_KEY"), "Content-Type": "application/json"})
    if r.status_code == 200:
        remaining = (_json(r).get("data") or {}).get("remaining_downloads", "?")
        return {"ok": True, "message": f"{remaining} downloads remaining today"}
    return {"ok": False, "message": f"OpenSubtitles refused the key ({_status(r)})"}


def test_discord(v: dict) -> dict:
    if (m := _need(v, "DISCORD_WEBHOOK_URL")):
        return {"ok": False, "message": f"{m} is empty"}
    r = _http("POST", _v(v, "DISCORD_WEBHOOK_URL"), json={"content": "Mycelium test message"})
    return {"ok": r.status_code < 400, "message": "test message sent" if r.status_code < 400 else f"Discord answered {_status(r)}"}


def test_telegram(v: dict) -> dict:
    if (m := _need(v, "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")):
        return {"ok": False, "message": f"{m} is empty"}
    r = _http("POST", f"https://api.telegram.org/bot{_v(v, 'TELEGRAM_BOT_TOKEN')}/sendMessage",
              json={"chat_id": _v(v, "TELEGRAM_CHAT_ID"), "text": "Mycelium test message"})
    return {"ok": r.status_code < 400, "message": "test message sent" if r.status_code < 400 else f"Telegram answered {_status(r)}"}


def test_oidc(v: dict) -> dict:
    if (m := _need(v, "OIDC_ISSUER_URL")):
        return {"ok": False, "message": f"{m} is empty"}
    r = _http("GET", f"{_v(v, 'OIDC_ISSUER_URL').rstrip('/')}/.well-known/openid-configuration")
    if r.status_code >= 400:
        return {"ok": False, "message": f"discovery document not found ({_status(r)})"}
    d = _json(r)
    missing = [k for k in ("authorization_endpoint", "token_endpoint") if not d.get(k)]
    if missing:
        return {"ok": False, "message": f"discovery document lacks {', '.join(missing)}"}
    return {"ok": True, "message": f"issuer {d.get('issuer', '')}, authorization and token endpoints found"}


TESTS = {
    "torbox": test_torbox, "realdebrid": test_realdebrid, "tmdb": test_tmdb,
    "zilean": test_zilean, "zilean_pg": test_zilean_pg, "debridio": test_debridio,
    "jellyfin": test_jellyfin, "seerr": test_seerr, "radarr": test_radarr, "sonarr": test_sonarr,
    "trakt": test_trakt, "opensubtitles": test_opensubtitles,
    "discord": test_discord, "telegram": test_telegram, "oidc": test_oidc,
}


def run(service: str, values: dict) -> dict:
    """{ok, message}. KeyError for an unknown service; everything else is
    caught and reported, never logged with the values."""
    fn = TESTS[service]
    try:
        return fn(dict(values or {}))
    except requests.Timeout:
        return {"ok": False, "message": f"timed out after {TIMEOUT} s"}
    except requests.RequestException as exc:
        return {"ok": False, "message": f"could not connect: {exc.__class__.__name__}"}
    except Exception as exc:
        log.warning("Service test %s failed: %s", service, exc.__class__.__name__)
        return {"ok": False, "message": f"test failed: {exc.__class__.__name__}"}


def _free(bytes_: int | None) -> str:
    if bytes_ is None:
        return ""
    gb = bytes_ / 1024 ** 3
    return f" ({gb / 1024:.1f} TB free)" if gb >= 1024 else f" ({round(gb)} GB free)"


def _pick_root_folders(kind: str, v: dict) -> list[dict]:
    p = kind.upper()
    r = _http("GET", f"{_v(v, f'{p}_URL').rstrip('/')}/api/v3/rootfolder", headers={"X-Api-Key": _v(v, f"{p}_API_KEY")})
    r.raise_for_status()
    return [{"value": f["path"], "label": f"{f['path']}{_free(f.get('freeSpace'))}"} for f in (r.json() or []) if f.get("path")]


def _pick_quality_profiles(kind: str, v: dict) -> list[dict]:
    p = kind.upper()
    r = _http("GET", f"{_v(v, f'{p}_URL').rstrip('/')}/api/v3/qualityprofile", headers={"X-Api-Key": _v(v, f"{p}_API_KEY")})
    r.raise_for_status()
    return [{"value": q["name"], "label": q["name"]} for q in (r.json() or []) if q.get("name")]


PICKERS = {
    "radarr_root_folders": lambda v: _pick_root_folders("radarr", v),
    "sonarr_root_folders": lambda v: _pick_root_folders("sonarr", v),
    "radarr_quality_profiles": lambda v: _pick_quality_profiles("radarr", v),
    "sonarr_quality_profiles": lambda v: _pick_quality_profiles("sonarr", v),
}


def pick(name: str, values: dict) -> dict:
    """{ok: True, options} or {ok: False, error}. KeyError for an unknown picker."""
    fn = PICKERS[name]
    kind = name.split("_", 1)[0]
    p = kind.upper()
    v = dict(values or {})
    if (m := _need(v, f"{p}_URL", f"{p}_API_KEY")):
        return {"ok": False, "error": f"{m} is empty"}
    try:
        return {"ok": True, "options": fn(v)}
    except requests.Timeout:
        return {"ok": False, "error": f"timed out after {TIMEOUT} s"}
    except Exception as exc:
        log.warning("Picker %s failed: %s", name, exc.__class__.__name__)
        return {"ok": False, "error": f"{kind.capitalize()} did not answer, or refused the API key"}
