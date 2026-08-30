"""The admin dashboard reloaded itself every two minutes.

templates/ui.html ran `setInterval(() => location.reload(), 120000)`, gated on
ten seconds of idleness that only `click` and `keydown` reset. Scrolling and
reading never counted, so the reload was effectively unconditional: every two
minutes the page threw away scroll position, the open tab, and any half-typed
input.

Three of the four timers already patch the DOM in place. The reload existed for
one thing only: the repair half of the Maintenance tab, which is server-rendered
and had no JSON endpoint behind it. These tests pin the endpoint, the patcher,
and the absence of the reload.
"""
import os
import re
import sys

os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import db
import stats

_ROOT = os.path.join(os.path.dirname(__file__), "..")


def _drop_cached_conn():
    """db caches one sqlite connection per thread, so repointing db.DB_PATH is
    only honoured once that cached handle is gone."""
    conn = getattr(db._tls, "conn", None)
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass
        db._tls.conn = None


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    _drop_cached_conn()
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    _drop_cached_conn()
    db.init()
    yield
    _drop_cached_conn()


def _ui_html():
    with open(os.path.join(_ROOT, "templates", "ui.html"), encoding="utf-8") as f:
        return f.read()


def _app_py():
    with open(os.path.join(_ROOT, "app.py"), encoding="utf-8") as f:
        return f.read()


def _fn_body(src, name):
    """The source of one JS function, up to the next top-level declaration."""
    m = re.search(r"(?:async )?function %s\s*\(" % re.escape(name), src)
    assert m, f"{name} is not defined in ui.html"
    tail = src[m.end():]
    nxt = re.search(r"\n  (?:async )?function ", tail)
    return tail[: nxt.start()] if nxt else tail


# ── the payload ───────────────────────────────────────────────────────────────

def test_repair_overview_on_a_fresh_database():
    """Nothing has run yet. The patcher must be able to render that state, so
    the keys are always present and last_cleanup is explicitly None."""
    d = stats.get_repair_overview()
    assert d == {"items": [], "last_cleanup": None}


def test_repair_overview_returns_the_last_run_and_its_items():
    run_id = db.insert_cleanup_run()
    db.update_cleanup_run(run_id, scanned=12, repaired=3, deleted=1, unfixable=2)
    db.insert_repair_item(run_id, "/media/movies/Dune (2021)/Dune (2021).strm",
                          "Dune", "movie", "old-1", "a" * 40, "repaired", None)

    d = stats.get_repair_overview()

    assert d["last_cleanup"]["scanned"] == 12
    assert d["last_cleanup"]["repaired"] == 3
    assert d["last_cleanup"]["unfixable"] == 2
    assert [i["title"] for i in d["items"]] == ["Dune"]


def test_repair_overview_returns_only_the_most_recent_run():
    """The summary block shows one run. A second run must replace the first,
    not sit behind it."""
    first = db.insert_cleanup_run()
    db.update_cleanup_run(first, scanned=1, repaired=0, deleted=0, unfixable=0)
    second = db.insert_cleanup_run()
    db.update_cleanup_run(second, scanned=99, repaired=0, deleted=0, unfixable=0)

    assert stats.get_repair_overview()["last_cleanup"]["scanned"] == 99


def test_repair_overview_honours_the_limit():
    run_id = db.insert_cleanup_run()
    for n in range(5):
        db.insert_repair_item(run_id, f"/media/movies/M{n}/M{n}.strm",
                              f"M{n}", "movie", None, None, "repaired", None)

    assert len(stats.get_repair_overview(limit=2)["items"]) == 2


# ── the endpoint ──────────────────────────────────────────────────────────────

def test_the_repair_endpoint_is_registered():
    assert re.search(r'@app\.get\(["\']/ui/api/repair["\']\)', _app_py())


def test_the_repair_endpoint_is_admin_only():
    """Repair items carry filesystem paths. The Maintenance tab is admin-gated;
    the endpoint behind it must be too, or the gate is decorative."""
    src = _app_py()
    m = re.search(r'@app\.get\(["\']/ui/api/repair["\']\)(.{0,400})', src, re.S)
    assert m, "no /ui/api/repair route"
    assert "auth.is_admin()" in m.group(1)
    assert "403" in m.group(1)


# ── the reload is gone ────────────────────────────────────────────────────────

def _without_js_comments(src):
    """Comment lines explaining the old reload are wanted; a call is not."""
    return "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("//"))


def test_the_dashboard_never_reloads_itself():
    """The bug. A reload destroys scroll position, the open tab and in-flight
    form state. Nothing on this page needs one."""
    assert "location.reload" not in _without_js_comments(_ui_html())


def test_the_two_minute_timer_patches_the_repair_tab_instead():
    """The reload's cadence is kept; only what it does changes."""
    src = _ui_html()
    m = re.search(r"setInterval\((.{0,120}?),\s*120000\)", src, re.S)
    assert m, "the two-minute timer is gone entirely"
    assert "refreshRepair()" in m.group(1)


# ── the patcher ───────────────────────────────────────────────────────────────

def test_the_repair_summary_has_a_stable_container():
    """The template only renders the five stat tiles when a cleanup has run, so
    the patcher cannot update them in place. It replaces a container that is
    always present."""
    assert 'id="repair-summary"' in _ui_html()


def test_the_patcher_targets_both_halves():
    body = _fn_body(_ui_html(), "refreshRepair")
    assert "repair-summary" in body
    assert "repair-body" in body
    assert "/ui/api/repair" in body


def test_the_patcher_reapplies_the_active_search_filter():
    """Replacing the rows drops the display:none the filter set on them. Without
    this the search box silently stops filtering after the first refresh."""
    body = _fn_body(_ui_html(), "refreshRepair")
    assert 'data-filter="repair-table"' in body
    assert "dispatchEvent" in body


def test_the_patcher_escapes_the_values_it_interpolates():
    """Jinja auto-escaped these. Titles, paths and reasons come from torrent
    names and the filesystem, so hand-built HTML must escape them too."""
    src = _ui_html()
    row = _fn_body(src, "_repairRowHtml")
    unescaped = re.findall(r"\$\{(?!esc\()([^}]*)\}", row)
    unescaped = [u for u in unescaped if not u.strip().startswith("hash")]
    assert unescaped == [], f"interpolated without esc(): {unescaped}"


def test_the_escape_helper_covers_the_html_metacharacters():
    body = _fn_body(_ui_html(), "esc")
    for ch in ("&amp;", "&lt;", "&gt;", "&quot;", "&#39;"):
        assert ch in body, f"esc() does not produce {ch}"
