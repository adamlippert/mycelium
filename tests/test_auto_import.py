"""Mycelium must not import the whole TorBox account behind the user's back.

strm_generator.run_once() in non-catbox mode walked the entire TorBox mylist
and wrote a .strm for every torrent found, with no request row behind it. That
ran hourly on a timer and again 30 seconds after every boot, so an account with
pre-existing content quietly grew a library nobody asked for and nothing in the
UI could list or remove.
"""
import os
import sys

os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import strm_generator as sg


@pytest.fixture
def torbox(monkeypatch):
    calls = []
    monkeypatch.setattr(sg.torbox_mod, "list_torrents",
                        lambda *a, **k: calls.append("listed") or [])
    monkeypatch.setattr(sg.settings, "get",
                        lambda k, d=None: False if k == "CATBOX_MODE" else d)
    return calls


def test_unattended_runs_do_not_scan_the_torbox_account(torbox):
    """The timer and the boot task pass import_unknown=False."""
    assert sg.run_once(import_unknown=False) == 0
    assert torbox == [], "the scheduled run must not touch the TorBox mylist"


def test_a_deliberate_run_still_imports(torbox):
    """The manual button, the TorBox push webhook and recovery all rely on it."""
    sg.run_once(import_unknown=True)
    assert torbox == ["listed"]


def test_the_default_is_still_to_import(torbox):
    """Every existing caller passes no argument and expects the old behaviour."""
    sg.run_once()
    assert torbox == ["listed"]


def test_catbox_mode_never_scans_the_account_either_way(monkeypatch):
    calls = []
    monkeypatch.setattr(sg.torbox_mod, "list_torrents",
                        lambda *a, **k: calls.append("listed") or [])
    monkeypatch.setattr(sg.settings, "get",
                        lambda k, d=None: True if k == "CATBOX_MODE" else d)
    monkeypatch.setattr(sg.db, "get_all_virtual_items", lambda: [])

    sg.run_once(import_unknown=True)

    assert calls == [], "catbox mode is driven by virtual_items, not the mylist"


def test_run_and_refresh_passes_the_flag_through(monkeypatch):
    seen = {}
    monkeypatch.setattr(sg, "run_once", lambda import_unknown=True: seen.update(v=import_unknown) or 0)
    monkeypatch.setattr(sg, "_self_heal_sample", lambda: None)
    import nfo_generator
    monkeypatch.setattr(nfo_generator, "generate_all", lambda: None)

    sg.run_and_refresh(import_unknown=False)

    assert seen["v"] is False, "the flag never reached run_once"


def test_the_scheduler_and_boot_task_disable_importing():
    """Pins the two call sites. If either loses the argument the surprise
    imports come straight back, and only at runtime on someone's server."""
    import pathlib
    import re
    src = pathlib.Path(__file__).resolve().parent.parent.joinpath("app.py").read_text()

    sched = re.search(r"scheduler\.add_job\(\s*(.{0,500}?)trigger=\"interval\", hours=STRM_GENERATOR_INTERVAL_HOURS", src, re.S)
    assert sched, "scheduled strm_generator job not found"
    assert "import_unknown=False" in sched.group(1), "the hourly job still imports"

    # Line-based: the call now contains a lambda, so a [^)]* scan stops early.
    boot = next((ln for ln in src.splitlines()
                 if "_delayed(" in ln and "strm-init" in ln), None)
    assert boot, "the strm-init boot task not found"
    assert "import_unknown=False" in boot, "the boot task still imports"


# ── anything that lands in the library must be manageable ─────────────────────

def test_a_written_torrent_gets_a_request_row(monkeypatch):
    """Without one the item shows in Jellyfin but nowhere in Mycelium, so
    neither Delete nor Remove from library can reach it."""
    rows = {}
    monkeypatch.setattr(sg.db, "get_request_by_imdb", lambda i: rows.get(i))
    monkeypatch.setattr(sg.db, "insert_request",
                        lambda t, i, mt, se=None, tmdb_id=None: rows.setdefault(i, {"id": 7, "title": t, "media_type": mt})["id"])
    statuses = {}
    monkeypatch.setattr(sg.db, "update_request",
                        lambda rid, status, **kw: statuses.update({rid: status}))

    sg._ensure_request_row("tt1234567", "Some Show (2020)", True, None)

    assert rows["tt1234567"]["title"] == "Some Show (2020)"
    assert rows["tt1234567"]["media_type"] == "series"
    assert statuses[7] == "success"


def test_an_existing_request_is_not_touched(monkeypatch):
    """A normal request already has a row whose status the processor owns.
    Overwriting it here would report success for something still in flight."""
    monkeypatch.setattr(sg.db, "get_request_by_imdb", lambda i: {"id": 3, "status": "wanted"})
    called = []
    monkeypatch.setattr(sg.db, "insert_request", lambda *a, **k: called.append("insert"))
    monkeypatch.setattr(sg.db, "update_request", lambda *a, **k: called.append("update"))

    sg._ensure_request_row("tt1234567", "Some Show", True, None)

    assert called == [], "must not disturb a request that already exists"


def test_a_database_failure_does_not_lose_the_strm(monkeypatch):
    """The .strm is already on disk by this point. Bookkeeping that raises
    must not turn a successful write into an exception."""
    def boom(*a, **k):
        raise RuntimeError("db is down")
    monkeypatch.setattr(sg.db, "get_request_by_imdb", boom)

    sg._ensure_request_row("tt1234567", "Some Show", False, None)  # must not raise


def test_no_imdb_id_means_no_row(monkeypatch):
    """imdb_id is NOT NULL UNIQUE, so a nameless import cannot get a row.
    library_sync.resolve_unknowns() is what eventually gives those an identity.
    """
    called = []
    monkeypatch.setattr(sg.db, "get_request_by_imdb", lambda i: called.append(i))

    sg._ensure_request_row(None, "Some Show", False, None)

    assert called == []
