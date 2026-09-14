"""The few helpers more than one blueprint needs.

Deliberately small: a helper with a single caller stays in that caller's
module. The SPA shell lives here because five sections serve it, and the
series-episodes cache because the purge route in admin_misc invalidates a
cache the spa route fills."""
import os as _os
import threading

import auth
import config as cfg
import oidc
from appcore import generate_csrf
from version import APP_VERSION

# __file__ is routes/_common.py, so the repo root is two dirnames up.
_SPA_DIR = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "static", "app")
_SPA_ASSET_DIR = _os.path.join(_SPA_DIR, "assets")


def _login_flags() -> dict:
    """Whether OIDC / password login are available, and which provider.
    Embedded as meta tags by _spa_index, since /ui/api/session requires a
    session and the login page needs these precisely when there isn't one
    yet."""
    return {
        "oidc_enabled": oidc.is_enabled(),
        "oidc_provider": oidc.provider_name(),
        "password_enabled": bool(cfg.AUTH_ENABLED or
                                  __import__("settings").get("AUTH_PASSWORD_HASH", "")),
    }


def _needs_first_admin() -> bool:
    """True when finishing setup would lock this install out of itself.

    With authentication on and no credential of any kind, the only way in is
    the first-admin bootstrap inside /ui/api/users/create, and that window
    closes the moment SETUP_COMPLETE is set. So while this is true the wizard
    must not set it: creating the admin does, which is what that endpoint
    already does on success.
    """
    return auth.is_enabled() and auth.no_credentials_exist()


# The series tree walk below touches every show and season folder on disk,
# so concurrent viewers share one result instead of each walking the tree.
_SERIES_EPISODES_TTL_SEC = 30
_series_episodes_cache: dict = {"ts": 0.0, "data": None}
_series_episodes_lock = threading.Lock()


def invalidate_series_episodes_cache() -> None:
    _series_episodes_cache["data"] = None
    _series_episodes_cache["ts"] = 0.0


def _spa_index():
    """Serve the SPA index with a fresh CSRF meta tag injected, plus the
    login flags (oidc/password availability, app version) the React login
    page needs before there is a session to read them from.
    Falls back to a friendly message if the build is missing."""
    from markupsafe import escape
    index_path = _os.path.join(_SPA_DIR, "index.html")
    if not _os.path.exists(index_path):
        return (
            "<h1>Mycelium SPA not built</h1>"
            "<p>Run <code>cd frontend && npm install && npm run build</code> "
            "or rebuild the Docker image.</p>"
        ), 503
    with open(index_path, encoding="utf-8") as f:
        html = f.read()
    token = generate_csrf()
    html = html.replace(
        '<meta name="csrf-token" content="" />',
        f'<meta name="csrf-token" content="{token}" />',
    )
    flags = _login_flags()
    html = html.replace(
        '<meta name="oidc-enabled" content="false" />',
        f'<meta name="oidc-enabled" content="{str(flags["oidc_enabled"]).lower()}" />',
    )
    html = html.replace(
        '<meta name="oidc-provider" content="" />',
        f'<meta name="oidc-provider" content="{escape(flags["oidc_provider"])}" />',
    )
    html = html.replace(
        '<meta name="password-enabled" content="true" />',
        f'<meta name="password-enabled" content="{str(flags["password_enabled"]).lower()}" />',
    )
    html = html.replace(
        '<meta name="app-version" content="" />',
        f'<meta name="app-version" content="{escape(APP_VERSION)}" />',
    )
    html = html.replace(
        '<meta name="needs-first-admin" content="false" />',
        f'<meta name="needs-first-admin" content="{str(_needs_first_admin()).lower()}" />',
    )
    return html, 200, {"Content-Type": "text/html; charset=utf-8"}

