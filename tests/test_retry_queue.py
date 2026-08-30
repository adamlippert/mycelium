"""The retry queue must drain. Three paths let it grow without bound:

  - processor.process() re-queued on a mutex miss by calling db.enqueue_retry
    DIRECTLY, skipping schedule()'s give-up check and passing the attempt count
    unchanged, so a title that kept colliding re-queued every 60s forever;
  - run_due() bails when the TorBox createtorrent budget is nearly spent,
    leaving rows due but unprocessed, so their attempt never increments and
    they never reach the give-up threshold;
  - nothing pruned the table, and there was no UNIQUE on imdb_id, so one title
    could hold many rows at once.
"""
import os
import sys

os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import db


def _drop_cached_conn():
    conn = getattr(db._tls, "conn", None)
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass
        db._tls.conn = None


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    _drop_cached_conn()
    db.init()
    yield
    _drop_cached_conn()


def _pending():
    return db.get_pending_retries()


def test_one_pending_retry_per_title(_isolated_db=None):
    """Two queued retries for the same title are never useful, and duplicates
    are how a queue quietly becomes a backlog."""
    db.enqueue_retry("tt1", "Show", "series", [1], 1, 60)
    db.enqueue_retry("tt1", "Show", "series", [1], 2, 60)

    rows = [r for r in _pending() if r["imdb_id"] == "tt1"]
    assert len(rows) == 1


def test_requeueing_keeps_the_higher_attempt():
    """Otherwise a late collision re-queue resets progress toward giving up."""
    db.enqueue_retry("tt2", "Show", "series", None, 3, 60)
    db.enqueue_retry("tt2", "Show", "series", None, 1, 60)

    row = [r for r in _pending() if r["imdb_id"] == "tt2"][0]
    assert row["attempt"] == 3


def test_collisions_are_counted_and_capped():
    """A mutex miss is a scheduling collision, not a failed attempt, so it must
    not raise `attempt` - but it still needs a ceiling of its own."""
    import retry_queue
    from webhook_parser import MediaRequest
    req = MediaRequest(title="Show", media_type="series", imdb_id="tt3", seasons=[1])

    accepted = 0
    for _ in range(retry_queue.MAX_COLLISION_REQUEUES + 3):
        if retry_queue.requeue_after_collision(req, attempt=0):
            accepted += 1
            db.remove_retry(_pending()[0]["id"])  # simulate the retry firing

    assert accepted == retry_queue.MAX_COLLISION_REQUEUES
    assert _pending() == [], "the queue must be empty once collisions are capped"


def test_a_collision_does_not_raise_the_attempt_count():
    import retry_queue
    from webhook_parser import MediaRequest
    req = MediaRequest(title="Show", media_type="series", imdb_id="tt4", seasons=[1])

    retry_queue.requeue_after_collision(req, attempt=2)

    assert [r for r in _pending() if r["imdb_id"] == "tt4"][0]["attempt"] == 2


def test_stale_rows_are_pruned():
    """A row still queued days later is not going to succeed; the content is
    not coming. Left alone it sits there forever, since a row that is never
    processed never increments its attempt."""
    db.enqueue_retry("tt5", "Old", "movie", None, 1, 0)
    with db._connect() as conn:
        conn.execute("UPDATE retry_queue SET created_at = datetime('now', '-9 days') WHERE imdb_id='tt5'")
        conn.commit()
    db.enqueue_retry("tt6", "New", "movie", None, 1, 0)

    removed = db.prune_retry_queue(max_age_days=7)

    ids = {r["imdb_id"] for r in _pending()}
    assert removed == 1
    assert "tt5" not in ids
    assert "tt6" in ids, "a fresh retry must survive"


def test_clearing_the_queue_empties_it():
    db.enqueue_retry("tt7", "A", "movie", None, 1, 60)
    db.enqueue_retry("tt8", "B", "movie", None, 1, 60)

    removed = db.clear_retry_queue()

    assert removed == 2
    assert _pending() == []


def test_the_mutex_miss_path_goes_through_the_collision_cap():
    """It used to call db.enqueue_retry directly, skipping both the cap and
    schedule()'s give-up check. Pinned in source: a regression here shows up
    only as a queue that quietly never drains."""
    import pathlib
    import re
    src = pathlib.Path(__file__).resolve().parent.parent.joinpath("processor.py").read_text()
    block = re.search(r"if not got:(.*?)return False", src, re.S)
    assert block, "the mutex-miss branch was not found"
    # Comments in this branch name db.enqueue_retry to explain why it is no
    # longer called, so match on code only.
    code = "\n".join(ln for ln in block.group(1).splitlines()
                     if not ln.strip().startswith("#"))
    assert "requeue_after_collision" in code
    assert "db.enqueue_retry" not in code, \
        "the mutex miss bypasses the collision cap again"


def test_processing_a_retry_forgets_its_collisions():
    """Otherwise a title that collided a few times early keeps that count for
    the life of the process and is dropped prematurely much later."""
    import retry_queue
    retry_queue._collisions["tt9"] = retry_queue.MAX_COLLISION_REQUEUES
    retry_queue.clear_collisions("tt9")
    assert "tt9" not in retry_queue._collisions


def test_the_prune_job_is_scheduled():
    import pathlib
    src = pathlib.Path(__file__).resolve().parent.parent.joinpath("app.py").read_text()
    assert "prune_retry_queue" in src, "nothing prunes the retry queue"


def test_the_clear_button_is_reachable():
    import pathlib
    root = pathlib.Path(__file__).resolve().parent.parent
    assert "/ui/api/retry-queue/clear" in (root / "app.py").read_text()
    ui = (root / "templates" / "ui.html").read_text()
    assert "clearRetryQueue" in ui and "/ui/api/retry-queue/clear" in ui


def test_migration_collapses_duplicates_on_a_legacy_database(tmp_path, monkeypatch):
    """The unique index cannot be created while duplicates exist, and a failed
    migration means the container does not boot. Anyone upgrading with a
    backlog in the queue is exactly the person who has duplicates.
    """
    path = tmp_path / "legacy.db"
    monkeypatch.setattr(db, "DB_PATH", str(path))
    _drop_cached_conn()

    import sqlite3
    conn = sqlite3.connect(str(path))
    conn.execute("""CREATE TABLE retry_queue (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        imdb_id TEXT NOT NULL, title TEXT NOT NULL, media_type TEXT NOT NULL,
        seasons TEXT, attempt INTEGER NOT NULL DEFAULT 0,
        next_retry_at TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now')))""")
    for attempt in (1, 3, 2):
        conn.execute("INSERT INTO retry_queue (imdb_id,title,media_type,attempt,next_retry_at) "
                     "VALUES ('tt77','Dupe','series',?,datetime('now'))", (attempt,))
    conn.execute("INSERT INTO retry_queue (imdb_id,title,media_type,attempt,next_retry_at) "
                 "VALUES ('tt88','Other','movie',1,datetime('now'))")
    conn.commit(); conn.close()

    db.init()  # must not raise

    rows = db.get_pending_retries()
    dupes = [r for r in rows if r["imdb_id"] == "tt77"]
    assert len(dupes) == 1, "duplicates were not collapsed"
    assert dupes[0]["attempt"] == 3, "collapsing must keep the furthest-along attempt"
    assert any(r["imdb_id"] == "tt88" for r in rows), "unrelated rows must survive"

    # And the constraint is now actually in force.
    db.enqueue_retry("tt77", "Dupe", "series", None, 4, 60)
    assert len([r for r in db.get_pending_retries() if r["imdb_id"] == "tt77"]) == 1
    _drop_cached_conn()
