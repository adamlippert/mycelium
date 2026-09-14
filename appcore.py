"""The Flask app and the extensions bolted onto it.

Every route module imports its decorators from here (the limiter, the CSRF
exemption) and never from app.py, which is what keeps routes/ out of an
import cycle with the module that registers it. app.py imports this after
db.init(): LITE_MODE reads a setting, and settings live in the database.

Nothing here registers a route."""
import logging

from flask import Flask

import config as cfg
import settings as _settings_mod
from config import WEBHOOK_SECRET

log = logging.getLogger("mycelium")

import os as _os
LITE_MODE: bool = (
    _settings_mod.get("LITE_MODE", False)
    or _os.getenv("LITE_MODE", "").lower() in ("1", "true", "yes")
)
if LITE_MODE:
    log.info("LITE_MODE enabled  -  heavy background schedulers and startup tasks disabled")

app = Flask(__name__, static_folder="static", static_url_path="/static")
import secrets as _secrets_mod
_session_secret = cfg.AUTH_SESSION_SECRET
if _session_secret == "mycelium-please-change-me":
    # Never sign session cookies with the well-known default - anyone could
    # forge an admin session. Auto-generate and persist one instead, same
    # pattern as WEBHOOK_SECRET_AUTO below.
    _session_secret = _settings_mod.get("AUTH_SESSION_SECRET_AUTO", "")
    if not _session_secret:
        _session_secret = _secrets_mod.token_urlsafe(32)
        _settings_mod.set("AUTH_SESSION_SECRET_AUTO", _session_secret)
        log.info("Auto-generated AUTH_SESSION_SECRET - set your own in the environment to keep sessions valid across DB restores")
    else:
        log.debug("Using auto-generated AUTH_SESSION_SECRET from settings")
if not WEBHOOK_SECRET:
    _stored = _settings_mod.get("WEBHOOK_SECRET_AUTO", "")
    if not _stored:
        _stored = _secrets_mod.token_urlsafe(32)
        _settings_mod.set("WEBHOOK_SECRET_AUTO", _stored)
        log.info("Auto-generated WEBHOOK_SECRET - copy from Admin > Settings > Webhooks to your Seerr config")
    else:
        log.debug("Using auto-generated WEBHOOK_SECRET from settings")
app.secret_key = _session_secret
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SECURE"] = cfg.COOKIE_SECURE

# CSRF protection on all state-changing endpoints; external webhooks opt
# out with @_csrf.exempt on their routes (routes/integration.py and the
# stream report in routes/stream.py). generate_csrf is re-exported for
# the response hook and the SPA shell.
from flask_wtf.csrf import CSRFProtect, generate_csrf
_csrf = CSRFProtect(app)


# Rate limiter  -  applied selectively to auth endpoints.
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    default_limits=[],  # opt-in per route
    # memory:// keeps the counters in this process. Correct ONLY at
    # gunicorn --workers 1 (see the Dockerfile CMD): with N workers each
    # process counts independently and the login limit silently becomes
    # 5*N/min. Multi-worker needs a shared backend (redis://).
    storage_uri="memory://",
)
