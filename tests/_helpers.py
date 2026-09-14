"""Shared test helpers. Not a conftest: every _isolated_db fixture stays in
its own test file per the no-conftest convention; only these two
byte-identical helpers (_src in 23 files, _drop_cached_conn in 39) are
worth sharing. A variant such as the _db_modules() pattern that isolates
swapped db module objects is a different function and stays where it is."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import db  # noqa: E402

_ROOT = os.path.join(os.path.dirname(__file__), "..")


def _src(name):
    with open(os.path.join(_ROOT, name), encoding="utf-8") as f:
        return f.read()


def _drop_cached_conn():
    conn = getattr(db._tls, "conn", None)
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass
        db._tls.conn = None
