"""migrate_source: the one-off backfill that blanks a leftover scraper name
out of virtual_items.source and requests.source. It no longer tries to
derive a label for a row that has none; see the module docstring for why."""
import os
import sys

os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import db
import migrate_source
import settings as _settings


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
    _drop_cached_conn()
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    _drop_cached_conn()
    db.init()
    yield
    _drop_cached_conn()


def _virtual_item(token, title, imdb_id=None, media_type="movie", source="torrentio"):
    h = "a" * 40
    with db._connect() as conn:
        conn.execute(
            "INSERT INTO virtual_items (token, info_hash, magnet, title, media_type, strm_path, imdb_id, source) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (token, h, f"magnet:?xt=urn:btih:{h}", title, media_type, f"/media/{token}.strm", imdb_id, source),
        )
        conn.commit()


def _request(imdb_id, title, media_type="movie", source="torrentio"):
    rid = db.insert_request(title, imdb_id, media_type)
    db.update_request(rid, "success", quality="1080p", source=source, info_hash="a" * 40)
    return rid


def test_virtual_item_with_a_release_label_is_left_unchanged():
    """A row whose source is already a release-source label (not a leftover
    scraper name) must not be touched."""
    _virtual_item("tok1", "Heat (1995)", imdb_id="tt1", source="WEB-DL")
    out = migrate_source.migrate()
    assert out["virtual_items_blanked"] == 0
    assert out["virtual_items_unchanged"] == 1
    assert db.get_virtual_item("tok1")["source"] == "WEB-DL"


def test_virtual_item_with_a_leftover_scraper_name_is_blanked():
    """A row whose source is still a scraper name (torrentio, zilean, ...)
    must not keep that scraper name in a column that now means release
    source; the migration blanks it instead of trying to guess a label."""
    _virtual_item("tok1", "Heat (1995)", imdb_id="tt1", source="torrentio")
    out = migrate_source.migrate()
    assert out["virtual_items_blanked"] == 1
    assert out["virtual_items_unchanged"] == 0
    assert db.get_virtual_item("tok1")["source"] is None


def test_request_with_a_release_label_is_left_unchanged():
    _request("tt9", "Nothing Here", source="WEB-DL")
    out = migrate_source.migrate()
    assert out["requests_blanked"] == 0
    assert out["requests_unchanged"] == 1
    assert db.get_request_by_imdb("tt9")["source"] == "WEB-DL"


def test_request_with_a_leftover_scraper_name_is_blanked():
    _request("tt9", "Nothing Here", source="torrentio")
    out = migrate_source.migrate()
    assert out["requests_blanked"] == 1
    assert out["requests_unchanged"] == 0
    assert db.get_request_by_imdb("tt9")["source"] is None


def test_second_run_is_a_noop_once_migrated():
    _virtual_item("tok1", "Heat (1995)", imdb_id="tt1", source="torrentio")
    first = migrate_source.migrate()
    assert first["virtual_items_blanked"] == 1
    # Hand-edit after the first run to prove a second run leaves it alone -
    # a re-run that clobbers this would silently discard an admin's swap.
    with db._connect() as conn:
        conn.execute("UPDATE virtual_items SET source=? WHERE token=?", ("torrentio", "tok1"))
        conn.commit()
    second = migrate_source.migrate()
    assert second == {}
    assert db.get_virtual_item("tok1")["source"] == "torrentio"


def test_dry_run_reports_without_writing():
    _virtual_item("tok1", "Heat (1995)", imdb_id="tt1", source="torrentio")
    out = migrate_source.migrate(dry_run=True)
    assert out["virtual_items_blanked"] == 1
    assert db.get_virtual_item("tok1")["source"] == "torrentio", "dry_run must not write"
    assert _settings.get(migrate_source.MIGRATION_MARKER, False) is False


def test_wired_into_app_startup():
    root = os.path.join(os.path.dirname(__file__), "..")
    with open(os.path.join(root, "app.py"), encoding="utf-8") as f:
        src = f.read()
    assert "import migrate_source" in src
    assert "migrate_source.migrate()" in src
