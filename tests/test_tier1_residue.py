"""Follow-ups the whole-branch review of the Tier 1 plan deferred.

Each one is small, and each closes a gap that would otherwise only be found
the hard way: a silently inert egress meter, a table that grows forever, a
carve-out looser than its sibling, and a report body that records zero
instead of refusing.
"""
import os
import re
import sys
import time

os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import auth
import db

_ROOT = os.path.join(os.path.dirname(__file__), "..")


def _src(name):
    with open(os.path.join(_ROOT, name), encoding="utf-8") as f:
        return f.read()


def _drop_cached_conn():
    conn = getattr(db._tls, "conn", None)
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass
        db._tls.conn = None


@pytest.fixture()
def isolated_db(tmp_path, monkeypatch):
    _drop_cached_conn()
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    _drop_cached_conn()
    db.init()
    yield
    _drop_cached_conn()


# -- the egress endpoint must stay exempt from CSRF ---------------------------

def test_the_stream_report_route_is_csrf_exempt():
    """The Go front is a machine caller with no token. Global CSRFProtect
    rejected every report, the front ignored the status, and the tile read
    zero forever. Nothing else can catch this: tests may not import app.py
    and the Go tests use their own stub upstream."""
    src = _src("app.py")
    m = re.search(
        r'((?:@[\w.]+(?:\([^)]*\))?\s*\n|\s*#[^\n]*\n)*)'
        r'def internal_stream_report\(', src)
    assert m, "internal_stream_report not found"
    decorators = m.group(1)
    assert "@_csrf.exempt" in decorators, (
        "the egress report endpoint lost its CSRF exemption; every report "
        "will 400 and the Overview tile will silently read zero")
    assert '@app.post("/internal/stream-report/<token>")' in decorators


def test_the_only_csrf_exemptions_are_the_machine_callers():
    """An exemption is a hole in a global protection; the set of them should
    change deliberately, not by accident."""
    src = _src("app.py")
    exempted = re.findall(
        r'@app\.(?:post|route)\(["\']([^"\']+)["\'][^)]*\)\s*\n'
        r'(?:\s*#[^\n]*\n)*\s*@_csrf\.exempt', src)
    assert sorted(exempted) == sorted([
        "/webhook", "/torbox-webhook", "/internal/stream-report/<token>"]), (
        f"the CSRF exemption set changed: {exempted}")


def test_a_falsy_non_dict_body_is_refused_not_recorded_as_zero():
    src = _src("app.py")
    m = re.search(r"def internal_stream_report\(.*?\n(.*?)\n@app\.", src, re.S)
    assert m
    body = m.group(1)
    assert "request.get_json(silent=True)\n" in body, (
        "`or {}` coerces null/0/[]/'' into a silent zero-byte report")
    assert "isinstance(payload, dict)" in body


# -- the carve-out is no looser than its sibling ------------------------------

def test_the_create_user_carve_out_is_an_exact_path():
    """/setup was tightened to an exact match; its sibling stayed a prefix,
    so /ui/api/users/createanything also matched."""
    src = _src("auth.py")
    assert 'path == "/ui/api/users/create"' in src
    assert 'path.startswith("/ui/api/users/create")' not in src


# -- epoch-timestamped tables get pruned too ----------------------------------

def test_createtorrent_log_is_pruned(isolated_db):
    """Its ts is a REAL epoch, so it cannot share the text-datetime query:
    SQLite orders every number below every string, which would delete every
    row rather than the old ones."""
    now = time.time()
    with db._connect() as conn:
        conn.execute("INSERT INTO createtorrent_log (ts, reason) VALUES (?, 'old')",
                     (now - 200 * 86400,))
        conn.execute("INSERT INTO createtorrent_log (ts, reason) VALUES (?, 'recent')",
                     (now - 3600,))
        conn.commit()

    out = db.prune_old(days=90)

    assert out.get("createtorrent_log") == 1
    with db._connect() as conn:
        rows = [r["reason"] for r in conn.execute("SELECT reason FROM createtorrent_log")]
    assert rows == ["recent"], "pruning removed the wrong rows"


def test_epoch_pruning_keeps_everything_inside_the_window(isolated_db):
    """The failure this guards against deletes the whole table."""
    now = time.time()
    with db._connect() as conn:
        for n in range(3):
            conn.execute("INSERT INTO createtorrent_log (ts, reason) VALUES (?, ?)",
                         (now - n * 3600, f"r{n}"))
        conn.commit()

    db.prune_old(days=90)

    with db._connect() as conn:
        assert conn.execute("SELECT COUNT(*) n FROM createtorrent_log").fetchone()["n"] == 3


def test_text_timestamped_tables_still_prune(isolated_db):
    """The original loop must keep working alongside the epoch one."""
    with db._connect() as conn:
        conn.execute("INSERT INTO activity_log (event, title, message, success, created_at) "
                     "VALUES ('added', 'Old', '', 1, datetime('now', '-200 days'))")
        conn.execute("INSERT INTO activity_log (event, title, message, success) "
                     "VALUES ('added', 'New', '', 1)")
        conn.commit()

    out = db.prune_old(days=90)

    assert out.get("activity_log") == 1


# -- no_credentials_exist covers every credential type ------------------------

def test_oidc_alone_counts_as_a_credential(isolated_db, monkeypatch):
    """The third credential type had no test. If OIDC is the only way in,
    the setup surface must stay closed."""
    import oidc
    monkeypatch.setattr(auth.settings, "get", lambda k, d=None: d)
    monkeypatch.setattr(oidc, "is_enabled", lambda: True)

    assert auth.no_credentials_exist() is False


def test_no_credentials_when_oidc_is_off_and_nothing_else_exists(isolated_db, monkeypatch):
    import oidc
    monkeypatch.setattr(auth.settings, "get", lambda k, d=None: d)
    monkeypatch.setattr(oidc, "is_enabled", lambda: False)

    assert auth.no_credentials_exist() is True


# -- finishing setup must not lock the install out of itself ------------------

def test_needs_first_admin_only_when_auth_is_on_and_nothing_can_log_in(isolated_db, monkeypatch):
    """A no-auth single-user install has no credential either, and must not be
    forced to create an account."""
    src = _src("app.py")
    m = re.search(r"def _needs_first_admin\(\).*?\n(.*?)\n\n@app\.", src, re.S)
    assert m, "_needs_first_admin not found"
    body = m.group(1)
    assert "auth.is_enabled()" in body, "the predicate ignores whether auth is even on"
    assert "auth.no_credentials_exist()" in body


def test_setup_save_defers_completion_until_an_admin_exists():
    """Completing setup closes the first-admin window inside
    /ui/api/users/create, so an install with auth on and no credential would
    finish the wizard with no way to log in."""
    src = _src("app.py")
    m = re.search(r"def setup_save\(\).*?\n(.*?)\n@app\.", src, re.S)
    assert m, "setup_save not found"
    body = m.group(1)
    assert "_needs_first_admin()" in body
    assert "needs_first_admin=True" in body
    guard = body.index("_needs_first_admin()")
    complete = body.index('_settings.set("SETUP_COMPLETE", True)')
    assert guard < complete, "the guard must come before setup is marked complete"


def test_setup_skip_defers_completion_too():
    """Skipping the wizard is the same trap by a shorter route."""
    src = _src("app.py")
    m = re.search(r"def setup_skip\(\).*?\n(.*?)\n\n@app\.", src, re.S)
    assert m, "setup_skip not found"
    body = m.group(1)
    assert "_needs_first_admin()" in body
    guard = body.index("_needs_first_admin()")
    complete = body.index('_settings.set("SETUP_COMPLETE", True)')
    assert guard < complete


def test_creating_the_first_admin_is_what_completes_setup():
    """The bootstrap branch already sets SETUP_COMPLETE; that is why the
    wizard can safely leave it unset."""
    src = _src("app.py")
    m = re.search(r"def ui_api_users_create\(\).*?\n(.*?)\n    if not auth\.is_admin\(\)", src, re.S)
    assert m, "the bootstrap branch of ui_api_users_create not found"
    assert '_settings.set("SETUP_COMPLETE", True)' in m.group(1)


def test_the_wizard_is_told_whether_an_admin_is_needed():
    """The wizard renders pre-auth, so it reads this from the injected meta
    tag rather than an API call."""
    src = _src("app.py")
    assert '<meta name="needs-first-admin" content="false" />' in src
    assert "_needs_first_admin()" in src
    for shell in ("frontend/index.html", "static/app/index.html"):
        assert '<meta name="needs-first-admin" content="false" />' in _src(shell), shell
