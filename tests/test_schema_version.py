import os
import sys

os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import backup
import db

from _helpers import _drop_cached_conn

_ROOT = os.path.join(os.path.dirname(__file__), "..")


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    _drop_cached_conn()
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    _drop_cached_conn()
    yield
    _drop_cached_conn()


def test_first_start_records_the_version_and_takes_no_backup(monkeypatch):
    calls = []
    monkeypatch.setattr(backup, "run", lambda: calls.append(1))
    assert db.ensure_schema_version("1.0.0") is None
    db.init()
    db.record_schema_version("1.0.0")
    assert db.get_setting("SCHEMA_VERSION") == "1.0.0" and calls == []


def test_a_version_change_backs_up_before_migrating(monkeypatch):
    calls = []
    monkeypatch.setattr(backup, "run", lambda: calls.append(1))
    db.init()
    db.record_schema_version("0.29.0")
    assert db.ensure_schema_version("1.0.0") == "0.29.0"
    assert calls == [1]
    assert db.ensure_schema_version("1.0.0") == "0.29.0" and calls == [1, 1], "still differs until recorded"
    db.record_schema_version("1.0.0")
    assert db.ensure_schema_version("1.0.0") == "1.0.0" and calls == [1, 1]


def test_a_failing_backup_does_not_block_startup(monkeypatch, caplog):
    def boom():
        raise OSError("disk full")
    monkeypatch.setattr(backup, "run", boom)
    db.init()
    db.record_schema_version("0.29.0")
    assert db.ensure_schema_version("1.0.0") == "0.29.0"
    assert "backup" in caplog.text.lower()


def test_startup_calls_ensure_before_init_and_logs_the_line():
    src = open(os.path.join(_ROOT, "app.py")).read()
    assert src.index("db.ensure_schema_version(APP_VERSION)") < src.index("db.init()")
    assert src.index("db.init()") < src.index("db.record_schema_version(APP_VERSION)")
    assert "Mycelium %s, database schema from %s" in src
