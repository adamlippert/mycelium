"""Important 1: createtorrent_usage(None) sums every account's adds, so its
`limit` must scale with the number of accounts too (60 each)  -  otherwise a
two-account pool's batch jobs (retry_queue, monitor, upgrader) stop at
about 58 pool-wide adds instead of about 118. The four call sites that
gate on the budget must read usage["limit"], never the flat module
constant torbox._CREATETORRENT_LIMIT_HOUR, and torbox_pool._budget_left
(a single account's own budget) must track that same constant rather than
a hardcoded 60."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest  # noqa: E402

# A plain import: torbox_pool.py's own (lazy, per-call) `import torbox`
# resolves to the same sys.modules entry, so this must be the identical
# object for monkeypatching to reach it.
import torbox  # noqa: E402

import db  # noqa: E402
import settings  # noqa: E402
import torbox_pool as pool  # noqa: E402

from _helpers import _src, _drop_cached_conn

@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    _drop_cached_conn()
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("TORBOX_API_KEY", "k1")
    _drop_cached_conn()
    db.init()
    settings.set("TORBOX_API_KEY", "k1")
    pool.invalidate()
    pool._health.clear()
    yield
    _drop_cached_conn()


def test_pool_wide_limit_scales_with_the_number_of_accounts():
    assert torbox.createtorrent_usage()["limit"] == 60, "one account: limit stays 60"
    db.insert_torbox_account("second", "k2")
    pool.invalidate()
    assert torbox.createtorrent_usage()["limit"] == 120, "two accounts: 60 each"


def test_per_account_limit_is_unaffected_by_the_pool_size():
    db.insert_torbox_account("second", "k2")
    pool.invalidate()
    assert torbox.createtorrent_usage(1)["limit"] == 60
    assert torbox.createtorrent_usage(2)["limit"] == 60


def test_pool_wide_limit_is_at_least_sixty_with_an_empty_pool(monkeypatch):
    monkeypatch.setattr(pool, "accounts", lambda enabled_only=True: [])
    assert torbox.createtorrent_usage()["limit"] == 60


def test_budget_left_tracks_the_module_constant_not_a_hardcoded_sixty(monkeypatch):
    monkeypatch.setattr(torbox, "_CREATETORRENT_LIMIT_HOUR", 40)
    assert pool._budget_left(1) == 40


def test_batch_job_gates_read_the_pool_wide_limit_not_the_flat_module_constant():
    """Source-text guard: none of the four call sites may compare
    usage["count"] against the flat 60 constant, or the pool-wide gate is
    wrong for a multi-account install again."""
    for name in ("retry_queue.py", "monitor.py", "upgrader.py", "shell_summary.py"):
        src = _src(name)
        assert '["count"] >= torbox._CREATETORRENT_LIMIT_HOUR' not in src, \
            f"{name} must gate on usage['limit'], not the flat module constant"
