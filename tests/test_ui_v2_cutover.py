"""UI_V2 cuts the pre-auth surfaces over to the SPA, with permanent escape
hatches. The flag is an env var read at startup: a runtime toggle stored in
the database is unreachable if login is what broke. With the flag off,
today's behaviour must be byte-identical.
"""
import importlib
import os
import re
import sys

os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_ROOT = os.path.join(os.path.dirname(__file__), "..")


def _src(name):
    with open(os.path.join(_ROOT, name), encoding="utf-8") as f:
        return f.read()


def test_the_flag_defaults_off_and_parses_truthy_values(monkeypatch):
    import config
    monkeypatch.delenv("UI_V2", raising=False)
    importlib.reload(config)
    assert config.UI_V2 is False
    monkeypatch.setenv("UI_V2", "true")
    importlib.reload(config)
    assert config.UI_V2 is True
    monkeypatch.delenv("UI_V2", raising=False)
    importlib.reload(config)


def test_classic_routes_exist_and_serve_the_jinja_views():
    src = _src("app.py")
    assert '@app.get("/login/classic")' in src
    assert '@app.get("/setup/classic")' in src
    assert '@app.get("/admin/classic")' in src
    # each classic body renders the template the bare route used to
    for tpl in ("login.html", "setup.html", "ui.html"):
        assert src.count(f'render_template("{tpl}"') >= 1


def test_the_bare_routes_switch_on_the_flag():
    src = _src("app.py")
    for fn in ("login_view", "setup_wizard", "ui_dashboard"):
        m = re.search(rf"def {fn}\(.*?\n(?=@app\.|\ndef )", src, re.S)
        assert m, fn
        assert "UI_V2" in m.group(0), f"{fn} does not consult the flag"
        assert "_spa_index()" in m.group(0), f"{fn} cannot serve the SPA"


def test_login_classic_is_public():
    assert '"/login/classic"' in _src("auth.py")


def test_the_auth_gate_redirect_targets_are_flag_agnostic():
    """The gate redirects to /login; with UI_V2 on that serves the SPA login,
    off it serves Jinja. The gate itself must not hardcode a classic path."""
    src = _src("auth.py")
    assert "/login/classic?" not in src.replace('"/login/classic"', "")
