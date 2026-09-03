"""Dashboard authentication.

Two flavours, both opt-in:

1. Built-in session login. AUTH_USERNAME + a scrypt-hashed AUTH_PASSWORD.
   The wizard collects a plain password and immediately hashes it; the
   plain value is wiped from settings after the hash lands.

2. Reverse-proxy header trust. If you already run Authelia, Authentik,
   Traefik forward-auth or similar in front of Mycelium, set
   TRUSTED_PROXY_AUTH=true and the user from the configured header is
   accepted as authenticated. A network whitelist guards against
   header spoofing from non-proxy clients.

Webhook, /health and /healthz stay unauthenticated so external systems
(Seerr, Synology Container Manager) keep working.
/metrics requires an admin session or a valid METRICS_TOKEN header.
/dav uses HTTP Basic Auth against the Mycelium user database.
/stream/ uses token-based access (token embedded in .strm files).
"""
from __future__ import annotations

import base64
import functools
import hashlib
import hmac
import ipaddress
import logging
import secrets

from flask import jsonify, redirect, request, session, url_for

import settings

log = logging.getLogger(__name__)

_PUBLIC_PATHS = (
    "/webhook",
    "/torbox-webhook",
    "/health",
    "/healthz",
    "/login",
    "/login/oidc",
    "/oidc/callback",
    "/logout",
    "/stream/",
    "/spore-stream/",
    "/assets",
    "/static",
)


# ─────────────────────────────────────────────────────────────────────────────
# Password hashing
# ─────────────────────────────────────────────────────────────────────────────

def hash_password(pw: str) -> str:
    salt = secrets.token_hex(16)
    h = hashlib.scrypt(pw.encode(), salt=salt.encode(), n=2 ** 14, r=8, p=1, dklen=32)
    return f"scrypt${salt}${h.hex()}"


def _verify_hashed(pw: str, stored: str) -> bool:
    try:
        _, salt, hash_hex = stored.split("$", 2)
        expected = hashlib.scrypt(pw.encode(), salt=salt.encode(),
                                   n=2 ** 14, r=8, p=1, dklen=32)
        return hmac.compare_digest(expected.hex(), hash_hex)
    except Exception:
        return False


def _verify_password(pw: str) -> bool:
    hashed = settings.get("AUTH_PASSWORD_HASH", "")
    if hashed and hashed.startswith("scrypt$"):
        return _verify_hashed(pw, hashed)
    # First-run fallback: AUTH_PASSWORD stored as plain. If it matches, upgrade.
    plain = settings.get("AUTH_PASSWORD", "")
    if plain and hmac.compare_digest(pw, plain):
        settings.set("AUTH_PASSWORD_HASH", hash_password(pw))
        settings.set("AUTH_PASSWORD", None)
        log.info("AUTH_PASSWORD upgraded to scrypt hash")
        return True
    return False


def set_password(pw: str) -> None:
    """Public helper used by the setup wizard / settings UI."""
    settings.set("AUTH_PASSWORD_HASH", hash_password(pw))
    settings.set("AUTH_PASSWORD", None)


# ─────────────────────────────────────────────────────────────────────────────
# Reverse-proxy header trust
# ─────────────────────────────────────────────────────────────────────────────

def _ip_in_trusted(remote: str | None) -> bool:
    if not remote:
        return False
    networks_raw = settings.get("TRUSTED_PROXY_NETWORKS", "127.0.0.1/32")
    if isinstance(networks_raw, list):
        nets = networks_raw
    else:
        nets = [n.strip() for n in (networks_raw or "").split(",") if n.strip()]
    try:
        ip = ipaddress.ip_address(remote)
    except ValueError:
        return False
    for n in nets:
        try:
            if ip in ipaddress.ip_network(n, strict=False):
                return True
        except ValueError:
            continue
    return False


def _proxy_user() -> str | None:
    if not settings.get("TRUSTED_PROXY_AUTH", False):
        return None
    if not _ip_in_trusted(request.remote_addr):
        return None
    header = settings.get("TRUSTED_PROXY_USER_HEADER", "X-Forwarded-User")
    return request.headers.get(header) or None


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def is_enabled() -> bool:
    if settings.get("AUTH_ENABLED", False):
        return True
    # OIDC implicitly enables auth-gating
    try:
        import oidc
        return oidc.is_enabled()
    except Exception:
        return False


def current_user() -> str | None:
    if not is_enabled():
        return None
    return session.get("user") or _proxy_user()


def no_credentials_exist() -> bool:
    """True when nothing in this deployment can possibly authenticate.

    With AUTH_ENABLED on and no users, no legacy password hash and no OIDC,
    the login page cannot succeed and the setup wizard is gated behind it,
    so a fresh install is unusable. Callers use this to keep the setup
    surface reachable in exactly that state, and only that state.
    """
    try:
        import db
        if db.user_count() > 0:
            return False
    except Exception:
        return False
    if settings.get("AUTH_PASSWORD_HASH", ""):
        return False
    try:
        import oidc
        if oidc.is_enabled():
            return False
    except Exception:
        pass
    return True


_LEGACY_PREFS_KEY = "LEGACY_USER_PREFS"


def legacy_user_prefs() -> dict:
    """Preferences saved by the legacy single-user login, which has no
    users-table row to write to. Stored as one JSON object in settings."""
    import json
    import settings
    raw = settings.get(_LEGACY_PREFS_KEY, "") or ""
    try:
        d = json.loads(raw) if isinstance(raw, str) else raw
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def save_legacy_user_prefs(fields: dict) -> None:
    """Merge fields into the legacy login's settings-backed preferences.
    Callers validate the fields; this only persists them."""
    import json
    import settings
    prefs = legacy_user_prefs()
    prefs.update(fields)
    settings.set(_LEGACY_PREFS_KEY, json.dumps(prefs))


def current_user_record() -> dict | None:
    """Return the full users-table row for the active session, or None.

    The legacy single-user AUTH_USERNAME/AUTH_PASSWORD login explicitly sets
    session['role'] on success ('admin') and is honoured as-is. OIDC and
    trusted-proxy logins only set session['user'] with no role, so they are
    resolved (or auto-provisioned) against the real users table instead of
    being granted admin implicitly - the first user ever provisioned this way
    becomes admin (bootstrap), every subsequent one defaults to 'user'."""
    uid = session.get("user_id")
    if uid:
        import db
        u = db.get_user(uid)
        if u:
            return u
    user = current_user()
    if not user:
        return None
    legacy_role = session.get("role")
    if legacy_role:
        # Legacy single-user AUTH_USERNAME/AUTH_PASSWORD login. The synthetic
        # id=0 record matches no users-table row, so preferences saved by
        # this login live in a settings blob instead (same fix as
        # LEGACY_USER_REGION); overlay them so every reader of the record -
        # the session payload, plugin session_fields, webplayer checks -
        # sees them without knowing where they came from.
        rec = {"id": 0, "username": user, "role": legacy_role, "auto_approve": 1,
               "quota_monthly": 0, "enabled": 1, "webplayer_enabled": 1}
        rec.update(legacy_user_prefs())
        return rec
    # OIDC / trusted-proxy login: resolve or auto-provision a real DB user.
    import db
    u = db.get_user_by_username(user)
    if not u:
        # Bootstrap admin only during initial setup - once SETUP_COMPLETE is
        # set, deleting every user must not silently reopen an admin-grant
        # window for the next OIDC/proxy login.
        is_bootstrap = db.user_count() == 0 and not settings.get("SETUP_COMPLETE", False)
        role = "admin" if is_bootstrap else "user"
        new_id = db.create_user(user, "sso$disabled", role=role)
        u = db.get_user(new_id)
    if not u.get("enabled"):
        return None
    session["user_id"] = u["id"]
    db.touch_user_login(u["id"])
    return u


def is_admin() -> bool:
    # Auth disabled → single-user mode, full admin access.
    if not is_enabled():
        return True
    rec = current_user_record()
    return bool(rec and rec.get("role") == "admin")


def attempt_login(username: str, password: str) -> bool:
    """Authenticate against either the users table (multi-user) or the
    legacy single-user AUTH_USERNAME/AUTH_PASSWORD_HASH settings."""
    session.clear()
    # Try DB-backed user first
    try:
        import db
        u = db.get_user_by_username(username)
        if u and u.get("enabled") and u.get("password_hash", "").startswith("scrypt$"):
            if _verify_hashed(password, u["password_hash"]):
                session["user"] = u["username"]
                session["user_id"] = u["id"]
                session["role"] = u["role"]
                db.touch_user_login(u["id"])
                return True
    except Exception as exc:
        log.warning("DB user auth failed: %s", exc)

    # Legacy fallback
    expected_user = settings.get("AUTH_USERNAME", "admin") or "admin"
    if not hmac.compare_digest(username, expected_user):
        return False
    if _verify_password(password):
        session["user"] = expected_user
        session["role"] = "admin"
        session.pop("user_id", None)
        return True
    return False


def create_user_account(username: str, password: str, role: str = "user",
                         auto_approve: bool = False) -> int:
    import db
    if db.get_user_by_username(username):
        raise ValueError(f"User '{username}' already exists")
    return db.create_user(username, hash_password(password), role=role,
                          auto_approve=auto_approve)


def change_user_password(user_id: int, new_password: str) -> None:
    import db
    db.update_user(user_id, password_hash=hash_password(new_password))


def require_role(role: str):
    """Decorator: require a specific role (e.g. 'admin')."""
    def deco(view):
        @functools.wraps(view)
        def wrapped(*args, **kwargs):
            if not is_enabled():
                return view(*args, **kwargs)
            rec = current_user_record()
            if not rec:
                if request.path.startswith("/ui/api/") or request.headers.get("Accept", "").startswith("application/json"):
                    return jsonify(error="unauthorized"), 401
                return redirect(url_for("login_view", next=request.path))
            if rec.get("role") != role and role != "user":
                return jsonify(error="forbidden"), 403
            return view(*args, **kwargs)
        return wrapped
    return deco


def require_auth(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if not is_enabled():
            return view(*args, **kwargs)
        if session.get("user"):
            return view(*args, **kwargs)
        if _proxy_user():
            session["user"] = _proxy_user()
            return view(*args, **kwargs)
        # Not authenticated
        if request.path.startswith("/ui/api/") or request.headers.get("Accept", "").startswith("application/json"):
            return jsonify(error="unauthorized"), 401
        return redirect(url_for("login_view", next=request.path))
    return wrapped


def _enforce_basic_auth():
    """Return a 401 WWW-Authenticate challenge unless valid Basic Auth is provided."""
    header = request.headers.get("Authorization", "")
    if header.startswith("Basic "):
        try:
            decoded = base64.b64decode(header[6:]).decode("utf-8")
            username, password = decoded.split(":", 1)
            import db as _db
            user = _db.get_user_by_username(username)
            if user and user.get("enabled") and _verify_hashed(password, user.get("password_hash", "")):
                return None
        except Exception:
            pass
    from flask import Response
    return Response(
        "Authentication required",
        status=401,
        headers={"WWW-Authenticate": 'Basic realm="Mycelium WebDAV"'},
    )


def install_before_request(app) -> None:
    """Apply auth as a before_request hook so every UI route is covered."""
    @app.before_request
    def _enforce():
        if not is_enabled():
            return None
        path = request.path
        # Public paths are always allowed
        for prefix in _PUBLIC_PATHS:
            if path == prefix or path.startswith(prefix + "/") or path == prefix.rstrip("/"):
                return None
        # A deployment with auth on but no credential at all cannot log in,
        # and the setup wizard that would create the first one sits behind
        # this gate. Let the setup surface through while that is true; it
        # closes again as soon as any credential exists. The bootstrap check
        # inside /ui/api/users/create remains the authority on who may create
        # the first admin.
        if no_credentials_exist() and (
            path.startswith("/setup") or path.startswith("/ui/api/users/create")
        ):
            return None
        if path.startswith("/stream/") or path.startswith("/spore-stream/") or path.startswith("/spore-nfs/"):
            return None
        # The Go streaming front's resolve calls arrive over loopback with no
        # session; the route itself rejects anything not from 127.0.0.1.
        if path.startswith("/internal/"):
            return None
        if path.startswith("/dav"):
            return _enforce_basic_auth()
        if session.get("user"):
            return None
        proxy_user = _proxy_user()
        if proxy_user:
            session["user"] = proxy_user
            return None
        if path.startswith("/ui/api/") or request.headers.get("Accept", "").startswith("application/json"):
            return jsonify(error="unauthorized"), 401
        if path.startswith("/admin"):
            return redirect(url_for("login_view", next=path))
        return redirect("/login?next=" + path)
