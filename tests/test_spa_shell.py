"""The React SPA is the only UI. The Jinja views (templates/login.html,
setup.html, ui.html), their /classic escape-hatch routes and the UI_V2 flag
were removed once the cutover had been verified in production; the pre-auth
surfaces (/login, /setup, /admin) always serve the SPA shell now.
"""
import os
import re
import sys

os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_ROOT = os.path.join(os.path.dirname(__file__), "..")


def _src(name):
    with open(os.path.join(_ROOT, name), encoding="utf-8") as f:
        return f.read()


def test_the_jinja_ui_is_gone():
    assert not os.path.exists(os.path.join(_ROOT, "templates"))
    src = _src("app.py")
    assert "render_template" not in src
    # flash() messages were only ever rendered by ui.html; leftover calls
    # would pile up unread in the session cookie forever.
    assert "flash(" not in src


def test_the_classic_routes_are_gone():
    src = _src("app.py")
    assert "/classic" not in src
    assert "/login/classic" not in _src("auth.py")


def test_the_ui_v2_flag_is_retired():
    assert 'UI_V2 = _env' not in _src("config.py")


def test_the_bare_routes_serve_the_spa():
    src = _src("app.py")
    for fn in ("login_view", "setup_wizard", "ui_dashboard"):
        m = re.search(rf"def {fn}\(.*?\n(?=@app\.|\ndef )", src, re.S)
        assert m, fn
        assert "_spa_index()" in m.group(0), f"{fn} does not serve the SPA"


def test_session_endpoint_exposes_login_flags():
    """The SPA needs to know whether OIDC / password login are available.
    /ui/api/session is behind auth.py's before_request gate (401s for a
    logged-out visitor), so the login page actually reads these from meta
    tags _spa_index() embeds - but the session endpoint carries the same
    flags for any consumer that already holds a session."""
    src = _src("app.py")
    m = re.search(r"def ui_api_session\(.*?\n(?=@app\.|\ndef )", src, re.S)
    assert m, "ui_api_session"
    for flag in ("oidc_enabled", "oidc_provider", "password_enabled"):
        assert flag in m.group(0), f"ui_api_session does not expose {flag}"


def test_spa_index_embeds_login_flags_for_the_pre_auth_login_page():
    """_spa_index() must inject the login flags as meta tags: it is the only
    place the SPA gets them before a session cookie exists."""
    src = _src("app.py")
    m = re.search(r"def _spa_index\(.*?\n(?=@app\.|\ndef )", src, re.S)
    assert m, "_spa_index"
    for meta in ("oidc-enabled", "oidc-provider", "password-enabled", "app-version"):
        assert meta in m.group(0), f"_spa_index does not inject the {meta} meta tag"


def test_spa_index_placeholders_survive_in_both_built_and_source_html():
    """_spa_index() injects five values into the SPA shell with a literal
    str.replace() against exact meta-tag placeholders. If a rebuild changes
    whitespace, attribute order, or self-closing style on any of these tags,
    every replace() silently becomes a no-op - the csrf-token meta stays
    empty and every POST /login 400s. This derives the exact placeholder
    literals from _spa_index() and asserts each appears verbatim in both
    frontend/index.html (the source Vite builds from) and
    static/app/index.html (the checked-in build Docker serves)."""
    app_src = _src("app.py")
    m = re.search(r"def _spa_index\(.*?\n(?=@app\.|\ndef )", app_src, re.S)
    assert m, "_spa_index"
    placeholders = re.findall(r"html\.replace\(\s*\n\s*(['\"].*?['\"]),", m.group(0))
    assert len(placeholders) == 6, (
        f"expected 6 html.replace() calls in _spa_index, found {len(placeholders)}")
    literals = [eval(p) for p in placeholders]  # noqa: S307 - trusted literal from our own source

    expected = [
        '<meta name="csrf-token" content="" />',
        '<meta name="oidc-enabled" content="false" />',
        '<meta name="oidc-provider" content="" />',
        '<meta name="password-enabled" content="true" />',
        '<meta name="app-version" content="" />',
        '<meta name="needs-first-admin" content="false" />',
    ]
    assert sorted(literals) == sorted(expected)

    for name in ("frontend/index.html", "static/app/index.html"):
        html = _src(name)
        for literal in literals:
            assert literal in html, (
                f"{name} is missing the exact placeholder {literal!r} that "
                "_spa_index() replaces - a rebuild reformatted the head and "
                "every str.replace() in _spa_index() now silently no-ops.")


def test_login_redirects_home_when_auth_is_disabled():
    """With auth off, is_admin() already grants full access, so /login would
    render a page with no password form and no SSO button. That dead end
    reads as "login is broken" when the truth is "no auth is configured";
    send visitors to the app instead."""
    src = _src("app.py")
    m = re.search(r"def login_view\(\):(.*?)\n@app\.", src, re.S)
    assert m, "login_view not found"
    body = m.group(1)
    assert "auth.is_enabled()" in body, "login_view does not consult auth state"
    assert 'redirect("/")' in body, "login_view does not send disabled-auth visitors home"


def test_releases_json_covers_the_running_version():
    """releases.json is hand-maintained and feeds the admin Releases tab. It
    silently fell six versions behind (the tab still announced 0.8.4 while
    0.10.2 shipped), because nothing tied it to APP_VERSION. Now a release
    that forgets its notes fails here instead of misinforming users."""
    import json
    app_src = _src("app.py")
    m = re.search(r'APP_VERSION\s*=\s*"([^"]+)"', app_src)
    assert m, "APP_VERSION not found"
    version = m.group(1)
    with open(os.path.join(_ROOT, "releases.json"), encoding="utf-8") as f:
        releases = json.load(f)
    versions = [r["version"] for r in releases]
    assert version in versions, (
        f"APP_VERSION {version} has no releases.json entry; the admin "
        f"Releases tab would announce {versions[0]} as newest")
    assert versions[0] == version, (
        f"releases.json is not newest-first: it leads with {versions[0]}, "
        f"but the running version is {version}")
    # admin/Releases.tsx maps over notes and renders date unguarded; a
    # malformed entry blanks the tab at runtime instead of failing here.
    for r in releases:
        assert isinstance(r.get("notes"), list) and r["notes"], f"{r.get('version')}: no notes"
        assert r.get("date"), f"{r.get('version')}: no date"
