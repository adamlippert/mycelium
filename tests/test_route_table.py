"""The blueprint split moves routes; it never changes them. The fixture was
generated from app.py before the split and is refreshed only by a commit
that deliberately adds or removes a route."""
import json
import os
import sys

_ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(_ROOT, "scripts"))
import route_table  # noqa: E402


def test_registered_routes_equal_the_frozen_table():
    stored = json.load(open(os.path.join(_ROOT, "tests", "fixtures", "route_table.json")))
    assert route_table.parse(route_table.sources()) == stored


# ── url_for targets ───────────────────────────────────────────────────────────

_BLUEPRINTS = ("auth", "integration", "setup", "stream", "admin_library",
               "admin_misc", "spa")
# oidc.install() registers /login/oidc and /oidc/callback on the app object
# itself, not on a blueprint, so its endpoint name carries no prefix. It is
# the OIDC redirect URI: renaming it breaks every configured provider.
_APP_LEVEL_ENDPOINTS = {"oidc_callback"}


def _url_for_sources():
    import glob
    out = [os.path.join(_ROOT, n) for n in ("app.py", "auth.py", "oidc.py")]
    return out + sorted(glob.glob(os.path.join(_ROOT, "routes", "*.py")))


def test_every_url_for_target_names_a_blueprint_and_a_view_that_exists():
    """A url_for with a stale endpoint name raises BuildError at request
    time, not at import: the blueprint split renamed every target and only
    a source-text check catches the one that was missed."""
    import re
    targets = []
    for path in _url_for_sources():
        with open(path, encoding="utf-8") as f:
            for name in re.findall(r'url_for\(\s*"([^"]+)"', f.read()):
                targets.append((os.path.basename(path), name))
    assert targets, "no url_for calls found at all; the scan is broken"
    for where, name in targets:
        if "." not in name:
            assert name in _APP_LEVEL_ENDPOINTS, (
                f"{where}: url_for({name!r}) names no blueprint; every view "
                "moved to routes/ and needs its blueprint prefix")
            continue
        bp, _, view = name.partition(".")
        assert bp in _BLUEPRINTS, f"{where}: url_for({name!r}) names no blueprint"
        with open(os.path.join(_ROOT, "routes", f"{bp}.py"), encoding="utf-8") as f:
            module = f.read()
        assert f"def {view}(" in module, (
            f"{where}: url_for({name!r}) but routes/{bp}.py defines no {view}")


# ── registration ──────────────────────────────────────────────────────────────

def test_every_blueprint_module_is_registered_and_spa_is_last():
    """The frozen table is parsed from source, so a module that defines its
    routes but never reaches register_all would still match it while
    serving 404s. This is the half that source text cannot infer."""
    import glob
    import re
    modules = sorted(
        os.path.splitext(os.path.basename(p))[0]
        for p in glob.glob(os.path.join(_ROOT, "routes", "*.py"))
        if os.path.basename(p) not in ("__init__.py", "_common.py"))
    assert modules, "no blueprint modules found"
    for name in modules:
        with open(os.path.join(_ROOT, "routes", f"{name}.py"), encoding="utf-8") as f:
            src = f.read()
        assert f'bp = Blueprint("{name}", __name__)' in src, (
            f"routes/{name}.py names its blueprint something other than {name}")
    with open(os.path.join(_ROOT, "routes", "__init__.py"), encoding="utf-8") as f:
        init = f.read()
    listed = re.search(r"for mod in \(([^)]*)\)", init)
    assert listed, "register_all no longer iterates a tuple of modules"
    registered = [n.strip() for n in listed.group(1).split(",") if n.strip()]
    assert sorted(registered) == modules, (
        f"register_all registers {registered}, the package holds {modules}")
    assert registered[-1] == "spa", "spa owns the catch-all and must register last"
    with open(os.path.join(_ROOT, "app.py"), encoding="utf-8") as f:
        assert "routes.register_all(app)" in f.read(), "app.py registers nothing"


def test_the_image_ships_the_routes_package():
    """`COPY *.py ./` takes the top level only. Without a COPY of its own the
    package is missing from the image and every route 404s, which no test
    that reads source files can notice."""
    with open(os.path.join(_ROOT, "Dockerfile"), encoding="utf-8") as f:
        dockerfile = f.read()
    assert "COPY routes/ ./routes/" in dockerfile, (
        "the Dockerfile does not copy routes/ into the image")
