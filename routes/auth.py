"""Signing in and out and changing a password, plus the two app-wide
hooks: the security headers on every response and the CSRF token every
template context carries."""
from flask import Blueprint, jsonify, redirect, request, url_for

import auth
from appcore import generate_csrf, limiter
from routes._common import _spa_index

bp = Blueprint("auth", __name__)


@bp.after_app_request
def _security_headers(response):
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-XSS-Protection", "1; mode=block")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
    return response


@bp.app_context_processor
def _inject_csrf_token():
    return {"csrf_token": generate_csrf}


@bp.get("/login")
def login_view():
    # Nothing to log into when auth is off: is_admin() grants everyone full
    # access in that mode, so this page would render with no password form
    # and no SSO button - a dead end that reads as "login is broken" when
    # the real story is "this deployment has no auth configured".
    if not auth.is_enabled():
        return redirect("/")
    return _spa_index()


@bp.post("/login")
@limiter.limit("5 per minute; 30 per hour")
def login_submit():
    from flask import session as _session
    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""
    nxt = request.form.get("next") or "/"
    if not nxt.startswith("/") or nxt.startswith("//"):
        nxt = "/"
    if auth.attempt_login(username, password):
        _session["user"] = username
        return redirect(nxt)
    return redirect(url_for("auth.login_view", error="1", next=nxt))


@bp.get("/logout")
def logout_view():
    from flask import session as _session
    _session.clear()
    return redirect(url_for("auth.login_view"))


@bp.post("/ui/set-password")
@auth.require_auth
def ui_set_password():
    if not auth.is_admin():
        return jsonify(error="admin required"), 403
    new_pw = request.form.get("password") or ""
    if len(new_pw) < 6:
        return redirect(url_for("admin_library.ui_dashboard") + "#settings")
    auth.set_password(new_pw)
    return redirect(url_for("admin_library.ui_dashboard") + "#settings")


@bp.post("/ui/api/me/password")
@auth.require_auth
def ui_api_me_password():
    """Let users change their own password."""
    rec = auth.current_user_record()
    if not rec or not rec.get("id"):
        return jsonify(error="not authenticated"), 401
    p = request.get_json(silent=True) or {}
    current = p.get("current", "")
    new_pw = p.get("password", "")
    if len(new_pw) < 6:
        return jsonify(error="Password must be at least 6 characters"), 400
    if not auth._verify_hashed(current, rec.get("password_hash", "")):
        return jsonify(error="Current password is incorrect"), 400
    auth.change_user_password(rec["id"], new_pw)
    return jsonify(ok=True)
