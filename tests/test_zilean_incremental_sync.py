"""The native index used to download the whole 1.45 GB DMM snapshot on every
sync, four times a day, to discover the handful of pages upstream had added.

The repository is append-only: a sample of 40 consecutive commits added one
page each and modified none, so a page indexed once never has to be read
again. The sync therefore lists the tree and fetches only unseen pages,
falling back to the snapshot for the initial backfill or a gap large enough
that per-page fetches would cost more.
"""
import os
import sys

os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import zilean_index

# Real LZString payload from tests/test_zilean_index.py, so extraction runs
# for real rather than through a stub. Decodes to one entry:
# The.Matrix.1999.1080p.WEB-DL / hash "a" * 40 / 2000000000 bytes.
_VECTOR = (
    "NobwRAZglgNgpgOwIYFs5gFxgCoAs4B0AskgC4BOUAHgQIwCcjdADABzMAOBA6gKIBCAWgAiAGTAAaMLiQBnXJjBJlK1WvUbNqyWABGAT1JxZmAEzMLlywF8AukA"
)
_PAGE_HTML = f'<iframe src="https://debridmediamanager.com/hashlist#{_VECTOR}"></iframe>'
_KNOWN_HASH = "a" * 40


class _Resp:
    def __init__(self, payload=None, text="", status=200):
        self._payload = payload
        self.text = text
        self.status_code = status

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


@pytest.fixture()
def index(tmp_path, monkeypatch):
    monkeypatch.setattr(zilean_index, "_DB_PATH", str(tmp_path / "zilean.db"))
    zilean_index._tls.__dict__.clear()
    yield zilean_index._connect()
    zilean_index._tls.__dict__.clear()


def _tree(paths, truncated=False):
    return {"truncated": truncated,
            "tree": [{"path": p, "type": "blob"} for p in paths]}


def _wire(monkeypatch, tree, fetched, failing=()):
    """Route the tree listing and every raw page fetch through fakes,
    recording which page URLs were actually requested."""
    def fake_get(url, **kwargs):
        if url.startswith("https://api.github.com/"):
            return _Resp(payload=tree)
        fetched.append(url)
        if any(f in url for f in failing):
            return _Resp(text="", status=500)
        return _Resp(text=_PAGE_HTML)
    monkeypatch.setattr(zilean_index.requests, "get", fake_get)


def _no_snapshot(monkeypatch):
    """Fail loudly if the snapshot path runs: these tests assert it does not."""
    def boom(url, dest):
        raise AssertionError(f"downloaded the full snapshot: {url}")
    monkeypatch.setattr(zilean_index, "_download", boom)


# -- the incremental path -----------------------------------------------------

def test_only_unseen_pages_are_fetched(index, monkeypatch):
    index.execute("INSERT INTO seen_pages (filename) VALUES ('old.html')")
    index.commit()
    fetched = []
    _wire(monkeypatch, _tree(["old.html", "new.html"]), fetched)
    _no_snapshot(monkeypatch)

    result = zilean_index.sync(force=True)

    assert result["status"] == "ok"
    assert result["via"] == "listing"
    assert [u.rsplit("/", 1)[-1] for u in fetched] == ["new.html"]
    assert result["new_pages"] == 1


def test_a_fetched_page_is_indexed_and_marked_seen(index, monkeypatch):
    _wire(monkeypatch, _tree(["new.html"]), [])
    _no_snapshot(monkeypatch)

    zilean_index.sync(force=True)

    row = index.execute("SELECT raw_title FROM hashes WHERE info_hash=?",
                        (_KNOWN_HASH,)).fetchone()
    assert row is not None, "the page's hash was never indexed"
    assert row["raw_title"] == "The.Matrix.1999.1080p.WEB-DL"
    seen = {r["filename"] for r in index.execute("SELECT filename FROM seen_pages")}
    assert seen == {"new.html"}


def test_nothing_new_fetches_nothing(index, monkeypatch):
    index.execute("INSERT INTO seen_pages (filename) VALUES ('old.html')")
    index.commit()
    fetched = []
    _wire(monkeypatch, _tree(["old.html"]), fetched)
    _no_snapshot(monkeypatch)

    result = zilean_index.sync(force=True)

    assert fetched == []
    assert result["new_pages"] == 0
    assert result["via"] == "listing"


def test_a_failed_page_stays_unseen_for_the_next_run(index, monkeypatch):
    """A page left marked seen after a failed fetch would never be retried,
    silently losing its hashes forever."""
    fetched = []
    _wire(monkeypatch, _tree(["good.html", "bad.html"]), fetched, failing=("bad.html",))
    _no_snapshot(monkeypatch)

    result = zilean_index.sync(force=True)

    seen = {r["filename"] for r in index.execute("SELECT filename FROM seen_pages")}
    assert seen == {"good.html"}
    assert result["new_pages"] == 1
    assert len(fetched) == 2


def test_non_html_and_non_blob_entries_are_ignored(index, monkeypatch):
    tree = {"truncated": False, "tree": [
        {"path": "README.md", "type": "blob"},
        {"path": "pages", "type": "tree"},
        {"path": "real.html", "type": "blob"},
    ]}
    fetched = []
    _wire(monkeypatch, tree, fetched)
    _no_snapshot(monkeypatch)

    zilean_index.sync(force=True)

    assert [u.rsplit("/", 1)[-1] for u in fetched] == ["real.html"]


# -- falling back to the snapshot --------------------------------------------

def _snapshot_spy(monkeypatch, calls):
    monkeypatch.setattr(zilean_index, "_download", lambda url, dest: calls.append(url))
    monkeypatch.setattr(zilean_index, "_sync_from_zip",
                        lambda conn: (calls.append("zip"),
                                      {"new_pages": 0, "new_hashes": 0, "via": "snapshot"})[1])


def test_a_truncated_listing_falls_back_to_the_snapshot(index, monkeypatch):
    """GitHub truncates the tree for very large repositories; a partial
    listing would silently skip whatever it omitted."""
    calls = []
    _wire(monkeypatch, _tree(["a.html"], truncated=True), [])
    _snapshot_spy(monkeypatch, calls)

    result = zilean_index.sync(force=True)

    assert calls == ["zip"]
    assert result["via"] == "snapshot"


def test_an_empty_listing_falls_back_to_the_snapshot(index, monkeypatch):
    calls = []
    _wire(monkeypatch, _tree([]), [])
    _snapshot_spy(monkeypatch, calls)

    zilean_index.sync(force=True)

    assert calls == ["zip"]


def test_a_large_gap_falls_back_to_the_snapshot(index, monkeypatch):
    """First run, or a long outage: one archive beats thousands of requests."""
    calls = []
    many = [f"p{n}.html" for n in range(zilean_index._INCREMENTAL_MAX_PAGES + 1)]
    _wire(monkeypatch, _tree(many), [])
    _snapshot_spy(monkeypatch, calls)

    zilean_index.sync(force=True)

    assert calls == ["zip"]


def test_a_listing_failure_does_not_trigger_a_snapshot_download(index, monkeypatch):
    """A transient GitHub hiccup must not cost 1.45 GB; the run fails and the
    scheduler retries."""
    def boom(url, **kwargs):
        raise RuntimeError("connection reset")
    monkeypatch.setattr(zilean_index.requests, "get", boom)
    _no_snapshot(monkeypatch)

    result = zilean_index.sync(force=True)

    assert result["status"] == "error"
    row = index.execute("SELECT last_status FROM sync_state WHERE id=1").fetchone()
    assert row["last_status"] == "error"


# -- bookkeeping --------------------------------------------------------------

def test_sync_state_records_the_run(index, monkeypatch):
    _wire(monkeypatch, _tree(["new.html"]), [])
    _no_snapshot(monkeypatch)

    zilean_index.sync(force=True)

    row = index.execute("SELECT * FROM sync_state WHERE id=1").fetchone()
    assert row["last_status"] == "ok"
    assert row["last_synced_at"]
    assert row["last_pages_processed"] == 1
    assert row["last_error"] is None


def test_the_interval_gate_still_skips_a_recent_sync(index, monkeypatch):
    fetched = []
    _wire(monkeypatch, _tree(["new.html"]), fetched)
    _no_snapshot(monkeypatch)
    zilean_index.sync(force=True)
    fetched.clear()

    result = zilean_index.sync(force=False, min_interval_hours=6.0)

    assert result["status"] == "skipped_recent"
    assert fetched == []
