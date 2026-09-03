# Tier 1 Correctness and Risk Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the five correctness and account-risk gaps the ecosystem assessment identified, so that a silent data loss alerts, resolved CDN URLs stop outliving their provider window, unplayed titles carry real metadata, a fresh install with auth enabled can bootstrap, and monthly egress becomes visible before it ends the TorBox account.

**Architecture:** Five independent changes against the existing Flask/SQLite backend, plus one change in the Go streaming front. Nothing here alters the materialization flow, the scraper pipeline, or the SPA's routing. Four tasks are backend-only and single-file; Task 5 crosses the Go/Python boundary and introduces one new loopback endpoint following the pattern already set by `/internal/stream-resolve/<token>`.

**Tech Stack:** Python 3.12, Flask, SQLite (WAL), APScheduler, pytest; Go 1.22 for `spore-stream/`; React 18 + TypeScript for the admin surface.

**Spec:** Mycelium Field Report — ecosystem assessment, 2026-09-02 (published artifact; recommendations 01–05 under "Correctness and risk").

## Global Constraints

- Never use em-dashes anywhere in code, comments, copy, or commit messages. Use a spaced double hyphen or a comma.
- The repository is public. No passwords, tokens, API keys, or IP addresses in committed code, tests, fixtures, or commit messages.
- Work on branch `main` unless explicitly agreed otherwise.
- No `Co-Authored-By` lines in commit messages.
- There is no SSH access to the production VPS from the development machine. Any verification command that must run against production is handed to the user, never executed here.
- Tests must not import `app.py` (module-level Flask and APScheduler setup). Assert on route behaviour by reading `app.py` source text, following the established pattern in `tests/test_spa_shell.py` and `tests/test_region_persistence.py`.
- Every test that touches the database uses the isolated-DB fixture pattern: close the cached thread-local connection, monkeypatch `db.DB_PATH` to a `tmp_path` file, call `db.init()`, and close again on teardown. Copy the `_drop_cached_conn` helper from `tests/test_tier2_perf.py`.
- Run the full backend suite (`.venv-sdd/bin/python -m pytest tests/ -q`) before every commit. It must stay green; the current baseline is 574 passing.

---

### Task 1: Deadman switch fires when the library is empty

**Why:** On 2026-09-02 production lost its entire database and no alert fired. `_last_success_age_hours()` returns `None` when the activity log holds no successful add, and `deadman_check()` returns early on `None`. The watchdog is therefore silent in precisely the catastrophe it exists to catch: it speaks only when activity *stopped*, never when the history itself disappeared.

**Files:**
- Modify: `db.py` (add `count_virtual_items()` next to `count_wanted_episodes()` at line 615)
- Modify: `watchdog.py:60-68` (`deadman_check`)
- Test: `tests/test_watchdog_empty_library.py` (create)

**Interfaces:**
- Consumes: `db.get_setting(key)`, `db._connect()`, `watchdog._warn(metric, title, message)`, `watchdog._last_success_age_hours()`
- Produces: `db.count_virtual_items() -> int`; `watchdog.deadman_check()` keeps its existing no-argument, no-return signature

- [ ] **Step 1: Write the failing test**

Create `tests/test_watchdog_empty_library.py`:

```python
"""The deadman switch was silent in the one state it exists to catch.

_last_success_age_hours() returns None when the activity log holds no
successful add, and deadman_check() returned early on None. A database that
has been wiped or is pointed at an unmounted volume therefore produced
silence, indistinguishable from a fresh install. Production lost its entire
database on 2026-09-02 and nothing alerted; it was found by clicking around.
"""
import os
import sys

os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import db
import watchdog


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
    watchdog._last_warn.clear()
    yield
    watchdog._last_warn.clear()
    _drop_cached_conn()


@pytest.fixture()
def warnings(monkeypatch):
    fired = []
    monkeypatch.setattr(watchdog, "_warn",
                        lambda metric, title, message: fired.append((metric, title, message)))
    return fired


def test_configured_but_empty_library_alerts(warnings):
    """Setup complete plus nothing in the library is a wiped or unmounted
    database, not a fresh install."""
    db.set_setting("SETUP_COMPLETE", "true")

    watchdog.deadman_check()

    assert warnings, "no alert fired for a configured but empty library"
    metric, title, message = warnings[0]
    assert metric == "empty-library"
    assert "empty" in message.lower()


def test_fresh_install_stays_quiet(warnings):
    """Before setup there is legitimately nothing, and an alert would fire on
    every first boot."""
    watchdog.deadman_check()

    assert warnings == []


def test_a_populated_library_with_recent_activity_stays_quiet(warnings):
    db.set_setting("SETUP_COMPLETE", "true")
    with db._connect() as conn:
        conn.execute(
            "INSERT INTO virtual_items (token, info_hash, magnet, title, media_type) "
            "VALUES ('a' * 16, 'f' * 40, 'magnet:?xt=x', 'Some Movie', 'movie')")
        conn.commit()
    db.log_activity("added", "Some Movie", "ok", True)

    watchdog.deadman_check()

    assert warnings == []


def test_count_virtual_items_counts_rows():
    assert db.count_virtual_items() == 0
    with db._connect() as conn:
        conn.execute(
            "INSERT INTO virtual_items (token, info_hash, magnet, title, media_type) "
            "VALUES ('b' * 16, 'f' * 40, 'magnet:?xt=x', 'Another', 'movie')")
        conn.commit()
    assert db.count_virtual_items() == 1
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv-sdd/bin/python -m pytest tests/test_watchdog_empty_library.py -q`
Expected: FAIL. `test_count_virtual_items_counts_rows` errors with `AttributeError: module 'db' has no attribute 'count_virtual_items'`, and `test_configured_but_empty_library_alerts` fails on the empty `warnings` list.

- [ ] **Step 3: Add the count helper**

In `db.py`, immediately after `count_wanted_episodes()` (which ends at line 621):

```python
def count_virtual_items() -> int:
    with _connect() as conn:
        return conn.execute(
            "SELECT COUNT(*) AS n FROM virtual_items").fetchone()["n"]
```

- [ ] **Step 4: Add the empty-library check**

Replace `deadman_check()` in `watchdog.py` (lines 60-68) with:

```python
def deadman_check() -> None:
    # An empty library on a configured install is a wiped or unmounted
    # database, and it is the state the age check below cannot see: with no
    # activity rows at all, _last_success_age_hours() returns None and this
    # function used to return silently, exactly when it mattered most.
    try:
        import settings as _settings
        configured = bool(_settings.get("SETUP_COMPLETE", False))
    except Exception:
        configured = False
    if configured:
        try:
            if db.count_virtual_items() == 0:
                _warn(
                    "empty-library",
                    "Library is empty",
                    "Setup is complete but no library items exist. The database "
                    "may be a fresh file rather than the real one: check that "
                    "the data volume is mounted before the repair jobs run.",
                )
                return
        except Exception as exc:
            log.debug("Deadman: could not count virtual items: %s", exc)

    age = _last_success_age_hours()
    if age is None or age < DEADMAN_HOURS:
        return
    _warn(
        "deadman",
        "Deadman: no activity",
        f"No successful add in the last {age:.1f} hours  -  scheduler stuck or services unreachable?",
    )
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv-sdd/bin/python -m pytest tests/test_watchdog_empty_library.py -q`
Expected: PASS, 4 tests.

- [ ] **Step 6: Run the full suite**

Run: `.venv-sdd/bin/python -m pytest tests/ -q`
Expected: PASS, 578 tests.

- [ ] **Step 7: Commit**

```bash
git add db.py watchdog.py tests/test_watchdog_empty_library.py
git commit -m "fix(watchdog): alert when a configured install has an empty library

_last_success_age_hours() returns None when the activity log holds no
successful add, and deadman_check() returned early on None. A wiped or
unmounted database therefore produced silence, indistinguishable from a
fresh install: production lost its entire database and nothing alerted.

An empty library on an install whose setup is complete is now its own
alertable state, checked before the age comparison that cannot see it."
```

---

### Task 2: Resolved CDN URLs stop outliving TorBox's link window

**Why:** TorBox's `requestdl` documentation states the returned link "opens the link for 3 hours for downloads"; after that a new connection cannot be started. `catbox.py:30` caches resolved URLs for 23 hours. The liveness HEAD check and the invalidate-and-re-resolve path already compensate, but they treat the symptom: aligning the TTL removes a class of first-byte failures at the source.

**Files:**
- Modify: `catbox.py:30`
- Test: `tests/test_url_cache_ttl.py` (create)

**Interfaces:**
- Consumes: nothing new
- Produces: `catbox._URL_CACHE_TTL_SEC` remains an int of seconds; no signature changes

- [ ] **Step 1: Write the failing test**

Create `tests/test_url_cache_ttl.py`:

```python
"""TorBox's requestdl opens a returned link for three hours; after that a new
connection cannot be started against it. Caching a resolved URL for 23 hours
guaranteed a window in which every cached entry was already dead, which is
the failure the liveness check and re-resolve path were built to absorb.
"""
import os
import sys

os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import catbox

TORBOX_LINK_WINDOW_SEC = 3 * 3600


def test_url_cache_expires_inside_the_provider_window():
    assert catbox._URL_CACHE_TTL_SEC < TORBOX_LINK_WINDOW_SEC, (
        "a cached URL outlives TorBox's 3h link window and is dead on arrival")


def test_the_ttl_leaves_usable_headroom():
    """Too short and every playback pays a fresh resolve, spending the
    createtorrent budget the cache exists to protect."""
    assert catbox._URL_CACHE_TTL_SEC >= 2 * 3600
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv-sdd/bin/python -m pytest tests/test_url_cache_ttl.py -q`
Expected: FAIL on `test_url_cache_expires_inside_the_provider_window`, since 82800 is not less than 10800.

- [ ] **Step 3: Change the TTL**

In `catbox.py`, replace line 30:

```python
# TorBox's requestdl opens a returned link for 3 hours; after that a new
# connection against it is refused, though a transfer already in flight
# continues. Cache inside that window with headroom, so a cached entry is
# never dead on arrival. The liveness check below stays as the backstop for
# links that die early.
_URL_CACHE_TTL_SEC = 9000  # 2.5 hours
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv-sdd/bin/python -m pytest tests/test_url_cache_ttl.py -q`
Expected: PASS, 2 tests.

- [ ] **Step 5: Run the full suite**

Run: `.venv-sdd/bin/python -m pytest tests/ -q`
Expected: PASS. If any existing test asserts the 23 hour value, update it to reference `catbox._URL_CACHE_TTL_SEC` rather than a literal.

- [ ] **Step 6: Commit**

```bash
git add catbox.py tests/test_url_cache_ttl.py
git commit -m "fix(catbox): cache resolved URLs inside TorBox's 3h link window

requestdl opens a link for three hours; after that a new connection is
refused. Caching for 23 hours guaranteed a window where every cached
entry was already dead, which the liveness check and re-resolve path
then had to absorb on the serving path. Cache for 2.5 hours instead and
let those defences handle only links that die early."
```

---

### Task 3: NFO files carry stream details

**Why:** Jellyfin does not probe `.strm` files during library scans; duration, resolution, codec and audio stay empty until an item's first playback. Mycelium's NFOs carry only `<title>` and `<year>`, so every unplayed title shows blank technical metadata. The data is already known locally: `virtual_items` stores `quality`, `source` and `size_gb`, and `release_tags` parses codec and audio from the release name.

**Files:**
- Modify: `nfo_generator.py:60-69` (`_movie_nfo`)
- Test: `tests/test_nfo_streamdetails.py` (create)

**Interfaces:**
- Consumes: `release_tags.detect_encode(text) -> tuple[str, ...]`, `release_tags.detect_audio_channels(text) -> tuple[str, ...]`
- Produces: `nfo_generator._streamdetails_xml(quality, release_name) -> str` (returns `""` when nothing is known); `_movie_nfo(title, year, imdb_id, quality=None, release_name=None) -> str` with the two new parameters optional so existing call sites keep working

- [ ] **Step 1: Write the failing test**

Create `tests/test_nfo_streamdetails.py`:

```python
"""Jellyfin never probes .strm files during a library scan: resolution, codec
and audio stay empty until an item's first playback. The data is already
known locally, so the NFO can carry it and the library reads correctly from
the moment it is scanned, with no probe and no provider contact.
"""
import os
import sys

os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import nfo_generator


def test_resolution_becomes_width_and_height():
    xml = nfo_generator._streamdetails_xml("1080p", "Some.Movie.1080p.WEB-DL.x264")

    assert "<width>1920</width>" in xml
    assert "<height>1080</height>" in xml


def test_2160p_maps_to_uhd_dimensions():
    xml = nfo_generator._streamdetails_xml("2160p", "Some.Movie.2160p.WEB-DL")

    assert "<width>3840</width>" in xml
    assert "<height>2160</height>" in xml


def test_codec_comes_from_the_release_name():
    xml = nfo_generator._streamdetails_xml("1080p", "Some.Movie.1080p.WEB-DL.HEVC")

    assert "<codec>hevc</codec>" in xml


def test_audio_channels_are_carried():
    xml = nfo_generator._streamdetails_xml("1080p", "Some.Movie.1080p.DDP.5.1")

    assert "<channels>6</channels>" in xml


def test_nothing_known_yields_no_block():
    """An empty streamdetails element is worse than none: Jellyfin would
    treat it as authoritative and never probe."""
    assert nfo_generator._streamdetails_xml(None, "") == ""


def test_movie_nfo_embeds_the_block_when_given_details():
    xml = nfo_generator._movie_nfo(
        "Some Movie", 2024, "tt1234567",
        quality="1080p", release_name="Some.Movie.1080p.WEB-DL.x264")

    assert "<fileinfo>" in xml and "<streamdetails>" in xml
    assert "<height>1080</height>" in xml
    assert xml.rstrip().endswith("</movie>")


def test_movie_nfo_without_details_is_unchanged():
    """Existing call sites pass three arguments and must keep working."""
    xml = nfo_generator._movie_nfo("Some Movie", 2024, "tt1234567")

    assert "<fileinfo>" not in xml
    assert "<title>Some Movie</title>" in xml
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv-sdd/bin/python -m pytest tests/test_nfo_streamdetails.py -q`
Expected: FAIL with `AttributeError: module 'nfo_generator' has no attribute '_streamdetails_xml'`.

- [ ] **Step 3: Implement the builder and extend the NFO**

In `nfo_generator.py`, add above `_movie_nfo` (line 60):

```python
_RESOLUTION_DIMENSIONS = {
    "2160p": (3840, 2160),
    "1080p": (1920, 1080),
    "720p": (1280, 720),
    "480p": (854, 480),
}

_CHANNEL_COUNTS = {"7.1": 8, "5.1": 6, "2.0": 2}


def _streamdetails_xml(quality: str | None, release_name: str | None) -> str:
    """A <fileinfo><streamdetails> block from what is already known locally.

    Jellyfin does not probe .strm files during a library scan, so without
    this every unplayed title shows no resolution, codec or audio at all.
    Everything here comes from the release name and the virtual_items row:
    no ffprobe, no provider request.

    Returns "" when nothing is known. An empty block would be worse than
    none, because Jellyfin would treat it as authoritative.
    """
    import release_tags

    text = release_name or ""
    parts = []

    dims = _RESOLUTION_DIMENSIONS.get(quality or "")
    encode = release_tags.detect_encode(text)
    codec = encode[0] if encode else None
    if dims or codec:
        video = ["    <video>"]
        if codec:
            video.append(f"      <codec>{_xml_escape(codec)}</codec>")
        if dims:
            video.append(f"      <width>{dims[0]}</width>")
            video.append(f"      <height>{dims[1]}</height>")
        video.append("    </video>")
        parts.append("\n".join(video))

    channels = release_tags.detect_audio_channels(text)
    count = _CHANNEL_COUNTS.get(channels[0]) if channels else None
    if count:
        parts.append("    <audio>\n"
                     f"      <channels>{count}</channels>\n"
                     "    </audio>")

    if not parts:
        return ""
    return ("  <fileinfo>\n    <streamdetails>\n"
            + "\n".join(parts)
            + "\n    </streamdetails>\n  </fileinfo>\n")
```

Then replace `_movie_nfo` (lines 60-69) with:

```python
def _movie_nfo(title: str, year: int | None, imdb_id: str,
               quality: str | None = None, release_name: str | None = None) -> str:
    year_tag = f"\n  <year>{year}</year>" if year else ""
    details = _streamdetails_xml(quality, release_name)
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        "<movie>\n"
        f"  <title>{_xml_escape(title)}</title>{year_tag}\n"
        f'  <uniqueid type="imdb" default="true">{imdb_id}</uniqueid>\n'
        f"{details}"
        "</movie>\n"
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv-sdd/bin/python -m pytest tests/test_nfo_streamdetails.py -q`
Expected: PASS, 7 tests.

- [ ] **Step 5: Run the full suite**

Run: `.venv-sdd/bin/python -m pytest tests/ -q`
Expected: PASS, 585 tests.

- [ ] **Step 6: Commit**

```bash
git add nfo_generator.py tests/test_nfo_streamdetails.py
git commit -m "feat(nfo): carry stream details so unplayed titles are not blank

Jellyfin does not probe .strm files during a library scan, so
resolution, codec and audio stay empty until an item's first playback.
The data is already known locally: virtual_items stores quality and
size, and release_tags parses codec and audio channels from the release
name. Writing a fileinfo/streamdetails block fills the library in at
scan time with no ffprobe and no provider request."
```

---

### Task 4: A fresh install with auth enabled can bootstrap

**Why:** With `AUTH_ENABLED=true` and no users, no password hash and no OIDC, `/setup` is gated behind a login that can never succeed, and the bootstrap carve-out inside `/ui/api/users/create` is unreachable because `before_request` rejects it first. Such an install is bricked, and it is plausibly the state production reaches during recovery into a fresh database.

**Files:**
- Modify: `auth.py` (add `no_credentials_exist()` near `current_user_record()`; extend `_enforce` at line 334)
- Test: `tests/test_auth_bootstrap.py` (create)

**Interfaces:**
- Consumes: `db.user_count() -> int`, `settings.get(key, default)`, `oidc.is_enabled() -> bool`
- Produces: `auth.no_credentials_exist() -> bool`

- [ ] **Step 1: Write the failing test**

Create `tests/test_auth_bootstrap.py`:

```python
"""AUTH_ENABLED=true with no users, no password hash and no OIDC is a bricked
install: /setup is gated behind a login that cannot succeed, and the
bootstrap carve-out inside /ui/api/users/create never runs because the
request gate rejects it first. The setup surface must stay reachable while
no credential exists, and close again the moment one does.
"""
import os
import re
import sys

os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import auth
import db

_ROOT = os.path.join(os.path.dirname(__file__), "..")


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


def test_no_credentials_when_nothing_is_configured(monkeypatch):
    monkeypatch.setattr(auth.settings, "get", lambda k, d=None: d)

    assert auth.no_credentials_exist() is True


def test_a_password_hash_counts_as_a_credential(monkeypatch):
    monkeypatch.setattr(auth.settings, "get",
                        lambda k, d=None: "scrypt$x$y" if k == "AUTH_PASSWORD_HASH" else d)

    assert auth.no_credentials_exist() is False


def test_a_user_row_counts_as_a_credential(monkeypatch):
    monkeypatch.setattr(auth.settings, "get", lambda k, d=None: d)
    db.create_user("admin", "scrypt$x$y", role="admin")

    assert auth.no_credentials_exist() is False


def test_the_gate_lets_the_setup_surface_through_while_bricked():
    src = open(os.path.join(_ROOT, "auth.py"), encoding="utf-8").read()
    m = re.search(r"def _enforce\(\):(.*?)\n\ndef |def _enforce\(\):(.*)$", src, re.S)
    assert m, "_enforce not found"
    body = m.group(1) or m.group(2)
    assert "no_credentials_exist()" in body, "the gate never consults the bootstrap state"
    assert "/setup" in body, "the setup surface is not carved out"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv-sdd/bin/python -m pytest tests/test_auth_bootstrap.py -q`
Expected: FAIL with `AttributeError: module 'auth' has no attribute 'no_credentials_exist'`.

- [ ] **Step 3: Add the predicate**

In `auth.py`, immediately before `def current_user_record()`:

```python
def no_credentials_exist() -> bool:
    """True when nothing in this deployment can possibly authenticate.

    With AUTH_ENABLED on and no users, no legacy password hash and no OIDC,
    the login page cannot succeed and the setup wizard is gated behind it,
    so a fresh install is unusable. Callers use this to keep the setup
    surface reachable in exactly that state, and only that state.
    """
    try:
        import db
        if db.user_count() > 0:
            return False
    except Exception:
        return False
    if settings.get("AUTH_PASSWORD_HASH", ""):
        return False
    try:
        import oidc
        if oidc.is_enabled():
            return False
    except Exception:
        pass
    return True
```

- [ ] **Step 4: Carve the setup surface out of the gate**

In `auth.py`, inside `_enforce()`, immediately after the `_PUBLIC_PATHS` loop and before the `/stream/` check, insert:

```python
        # A deployment with auth on but no credential at all cannot log in,
        # and the setup wizard that would create the first one sits behind
        # this gate. Let the setup surface through while that is true; it
        # closes again as soon as any credential exists. The bootstrap check
        # inside /ui/api/users/create remains the authority on who may create
        # the first admin.
        if no_credentials_exist() and (
            path.startswith("/setup") or path.startswith("/ui/api/users/create")
        ):
            return None
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv-sdd/bin/python -m pytest tests/test_auth_bootstrap.py -q`
Expected: PASS, 4 tests.

- [ ] **Step 6: Run the full suite**

Run: `.venv-sdd/bin/python -m pytest tests/ -q`
Expected: PASS, 589 tests.

- [ ] **Step 7: Commit**

```bash
git add auth.py tests/test_auth_bootstrap.py
git commit -m "fix(auth): a credential-less install can reach the setup wizard

AUTH_ENABLED=true with no users, no password hash and no OIDC gated
/setup behind a login that cannot succeed, and the bootstrap carve-out
inside /ui/api/users/create never ran because before_request rejected
the request first. Such an install is bricked, which is plausibly the
state a recovery into a fresh database reaches.

The gate now lets the setup surface through while no credential exists
at all, and closes again the moment one does."
```

---

### Task 5: Monthly egress is metered against the plan floor

**Why:** TorBox enforces monthly bandwidth floors (5 TB free, 10 TB Essential, 20 TB Standard, 30 TB Pro) with a three-warning then permanent-ban policy including API key revocation. Mycelium proxies stream bytes through its own process, so it is one of the few tools that can measure egress precisely, and it currently does not. This is the only account-ending risk in the system that is invisible.

**Note on scope:** since v0.9.0 the Go front owns the byte transfer, so Python cannot count bytes by itself. The front reports totals back over the existing loopback channel.

**Files:**
- Modify: `db.py` (schema: add `egress_log`; add `record_egress()` and `egress_this_month()`)
- Modify: `app.py` (new route `/internal/stream-report/<token>`, beside `/internal/stream-resolve/<token>`)
- Modify: `spore-stream/stream.go` (report bytes after each stream completes)
- Modify: `frontend/src/pages/admin/Overview.tsx` (surface the figure)
- Test: `tests/test_egress_metering.py` (create); `spore-stream/stream_test.go` (extend)

**Interfaces:**
- Consumes: `db._connect()`, the loopback-only pattern established by `internal_stream_resolve` in `app.py`
- Produces: `db.record_egress(token: str, byte_count: int) -> None`; `db.egress_this_month() -> int`; HTTP `POST /internal/stream-report/<token>` accepting `{"bytes": <int>}` and returning `{"ok": true}`

- [ ] **Step 1: Write the failing test**

Create `tests/test_egress_metering.py`:

```python
"""TorBox enforces monthly bandwidth floors with a three-warning then
permanent-ban policy that includes API key revocation. Mycelium proxies the
bytes, so it can measure egress exactly; without this the only
account-ending risk in the system is invisible.
"""
import os
import re
import sys

os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import db

_ROOT = os.path.join(os.path.dirname(__file__), "..")


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


def test_recorded_bytes_accumulate():
    db.record_egress("a" * 16, 1_000)
    db.record_egress("b" * 16, 2_500)

    assert db.egress_this_month() == 3_500


def test_a_fresh_database_reports_zero():
    assert db.egress_this_month() == 0


def test_zero_and_negative_counts_are_ignored():
    """A client that hangs up before any byte, or a malformed report, must
    not create rows or skew the total."""
    db.record_egress("a" * 16, 0)
    db.record_egress("a" * 16, -5)

    assert db.egress_this_month() == 0


def test_last_month_is_excluded():
    db.record_egress("a" * 16, 900)
    with db._connect() as conn:
        conn.execute("UPDATE egress_log SET created_at = datetime('now', '-45 days')")
        conn.commit()

    assert db.egress_this_month() == 0


def test_the_report_endpoint_is_loopback_only():
    src = open(os.path.join(_ROOT, "app.py"), encoding="utf-8").read()
    m = re.search(r'@app\.post\(["\']/internal/stream-report/<token>["\']\)(.{0,600})',
                  src, re.S)
    assert m, "no /internal/stream-report route"
    body = m.group(1)
    assert '"127.0.0.1"' in body, "the report endpoint is not loopback gated"
    assert "403" in body


def test_the_go_front_reports_bytes():
    src = open(os.path.join(_ROOT, "spore-stream", "stream.go"), encoding="utf-8").read()
    assert "/internal/stream-report/" in src, "the front never reports what it sent"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv-sdd/bin/python -m pytest tests/test_egress_metering.py -q`
Expected: FAIL with `AttributeError: module 'db' has no attribute 'record_egress'`.

- [ ] **Step 3: Add the schema and helpers**

In `db.py`, add to the `_DDL` string beside the other tables:

```sql
CREATE TABLE IF NOT EXISTS egress_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    token      TEXT    NOT NULL,
    bytes      INTEGER NOT NULL,
    created_at TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_egress_created ON egress_log(created_at);
```

Then add beside `count_virtual_items()`:

```python
def record_egress(token: str, byte_count: int) -> None:
    """Record bytes served for one stream. Called by the Go front after each
    transfer, so the monthly total reflects real egress rather than an
    estimate."""
    if byte_count <= 0:
        return
    with _connect() as conn:
        conn.execute("INSERT INTO egress_log (token, bytes) VALUES (?, ?)",
                     (token, int(byte_count)))
        conn.commit()


def egress_this_month() -> int:
    """Bytes served since the start of the current calendar month. TorBox's
    bandwidth floors are monthly, so the window matches the policy."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(bytes), 0) AS n FROM egress_log "
            "WHERE created_at >= strftime('%Y-%m-01 00:00:00', 'now')"
        ).fetchone()
        return int(row["n"])
```

- [ ] **Step 4: Add the loopback report endpoint**

In `app.py`, immediately after `internal_stream_resolve`:

```python
@app.post("/internal/stream-report/<token>")
def internal_stream_report(token: str):
    """Byte count for one finished stream, reported by the Go front.

    Loopback-only for the same reason as the resolve endpoint: the front
    talks to gunicorn over 127.0.0.1, and when the front is disabled
    gunicorn is exposed directly, where this must not be reachable."""
    if request.remote_addr not in ("127.0.0.1", "::1"):
        abort(403)
    payload = request.get_json(silent=True) or {}
    try:
        db.record_egress(token, int(payload.get("bytes", 0)))
    except (TypeError, ValueError):
        return jsonify(error="bytes must be an integer"), 400
    return jsonify(ok=True)
```

- [ ] **Step 5: Report bytes from the Go front**

In `spore-stream/stream.go`, add to the `streamer` struct methods:

```go
// reportEgress tells Python how many bytes this stream actually served, so
// monthly usage can be measured against the provider's bandwidth floor.
// Fire and forget: a failed report must never affect playback.
func (s *streamer) reportEgress(token string, sent int64) {
	if sent <= 0 {
		return
	}
	body := strings.NewReader(fmt.Sprintf(`{"bytes":%d}`, sent))
	req, err := http.NewRequest(http.MethodPost,
		s.upstream+"/internal/stream-report/"+token, body)
	if err != nil {
		return
	}
	req.Header.Set("Content-Type", "application/json")
	resp, err := s.resolveClient.Do(req)
	if err != nil {
		log.Printf("stream: egress report failed for %s: %v", token, err)
		return
	}
	resp.Body.Close()
}
```

Then call it at the end of `serveCold` and `serveWarm`, immediately after each existing final `log.Printf`:

```go
	go s.reportEgress(token, sent)
```

- [ ] **Step 6: Run the Go tests**

Run: `cd spore-stream && gofmt -w . && go vet ./... && go test ./...`
Expected: PASS. The existing tests point at an upstream stub that returns 404 for unknown paths; the fire-and-forget report tolerates that.

- [ ] **Step 7: Surface it on the Overview**

In `stats.py`, inside `_build_overview()`, add the field beside `movies_pending` (line 49):

```python
        "movies_pending": db.count_media_items_pending("movie"),
        "egress_bytes_month": db.egress_this_month(),
```

In `frontend/src/api.ts`, add `egress_bytes_month: number;` to the stats response type. In `frontend/src/pages/admin/Overview.tsx`, add a tile beside the existing TorBox tiles:

```tsx
<StatTile
  value={stats ? `${(stats.egress_bytes_month / 1e12).toFixed(2)} TB` : '-'}
  label="Egress this month"
  sub="TorBox plan floors start at 5 TB"
/>
```

- [ ] **Step 8: Run every suite**

Run: `.venv-sdd/bin/python -m pytest tests/ -q && cd frontend && npx vitest run && cd ../spore-stream && go test ./...`
Expected: all PASS. Rebuild the SPA with `cd frontend && npm run build` and include the built assets in the commit, per the project convention.

- [ ] **Step 9: Commit**

```bash
git add db.py app.py stats.py spore-stream/stream.go frontend/src static/app tests/test_egress_metering.py
git commit -m "feat(metrics): meter monthly egress against the TorBox plan floor

TorBox enforces monthly bandwidth floors with a three-warning then
permanent-ban policy that revokes the API key. Mycelium proxies the
bytes, so it can measure egress exactly, and this was the only
account-ending risk in the system that was invisible.

The Go front reports what each stream actually served to a new
loopback-only endpoint, following the pattern of the resolve endpoint;
Python accumulates it in egress_log and the admin Overview shows the
month's total against the plan's floor. The report is fire and forget,
so a failure to record can never affect playback."
```

---

## Out of scope for this plan

The assessment's remaining recommendations belong in their own plans, because each produces working software on its own and each touches a different subsystem:

- **Resilience against providers** (recommendations 06 to 08): adding Comet and MediaFusion as scrapers, a provider substitution layer, and confirming probe results are never re-fetched on boot. One plan, scraper and debrid layers.
- **Administration** (recommendations 09 to 12): debrid-aware Prometheus gauges, restore documentation and a restore action, TorBox-versus-library reconciliation, and renaming the Spore streaming path. One plan, admin and observability surfaces.

## Verification after deployment

These cannot run here; hand them to the user.

- Confirm the empty-library alert reaches Discord or Telegram by pointing a throwaway container at an empty database.
- After a redeploy, confirm a Jellyfin library refresh shows resolution and codec on titles that have never been played.
- Confirm `Egress this month` on the admin Overview grows after playback, and matches TorBox's own usage figure closely enough to be trusted.
