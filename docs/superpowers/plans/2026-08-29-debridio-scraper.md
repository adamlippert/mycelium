# Debridio Scraper Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Debridio as a third scraper, first in priority, behind a single shared orchestrator that replaces six hand-rolled call sites.

**Architecture:** Extract the stream model, parsing helpers and ranking into a
neutral `streams.py`. Add `debridio.py`, which fetches Stremio-protocol streams
and recovers the BitTorrent info hash from `behaviorHints.bingeGroup`. Add
`scrapers.py`, which fetches all enabled scrapers concurrently, merges them in
priority order, dedups by hash, and ranks. Debridio is first, so it wins ties.

**Tech Stack:** Python 3.11+, `requests`, `pytest`, SQLite, Flask, Prometheus
client. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-29-debridio-scraper-design.md`

## Global Constraints

- **Never log a Debridio URL, config token, API key, or any exception whose
  message may embed them.** The constructed URL contains both the Debridio API
  key and the user's TorBox key. Route every such value through
  `debridio.redact()` before it reaches a log, an HTTP response, or a health
  payload.
- **Send Debridio a permissive config.** Never derive its `resolutions`,
  `excludedQualities`, `maxSize` or `preferredLang` from mycelium settings.
  Mycelium's filters are soft (they self-disable rather than return nothing);
  Debridio's are hard. See the spec's "deliberately permissive" section.
- **Every scraper must set `source` explicitly.** `Stream.source` defaults to
  `"torrentio"`, so an omission is silently misattributed rather than an error.
- Run the full suite (`python -m pytest tests/ -q`) before every commit. It is
  100 tests today and must stay green throughout.
- Follow existing style: module-level `log = logging.getLogger(__name__)`,
  `settings.get(KEY, config.KEY)` for config reads, no type-checker directives.

---

### Task 1: Extract the stream model into `streams.py`

**Files:**
- Create: `streams.py`
- Modify: `torrentio.py:83-101` (remove dataclass, add re-export)
- Test: `tests/test_streams.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `streams.Stream` dataclass with fields `name: str`, `title: str`,
  `info_hash: str`, `quality: str`, `seeders: int`, `size_gb: float`,
  `is_season_pack: bool`, `languages: tuple[str, ...] = ()`,
  `source: str = "torrentio"`, `cached: bool = False`,
  `also_seen_in: tuple[str, ...] = ()`; properties `magnet` and `size`.
  `torrentio.TorrentioStream` remains a working alias for it.

- [ ] **Step 1: Write the failing test**

Create `tests/test_streams.py`:

```python
import os
import sys

os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import streams
import torrentio


def _stream(**kw):
    base = dict(name="n", title="t", info_hash="a" * 40, quality="1080p",
                seeders=10, size_gb=5.0, is_season_pack=False)
    base.update(kw)
    return streams.Stream(**base)


def test_magnet_derives_from_info_hash():
    assert _stream().magnet == "magnet:?xt=urn:btih:" + "a" * 40


def test_new_fields_default_to_empty():
    s = _stream()
    assert s.cached is False
    assert s.also_seen_in == ()


def test_new_fields_are_settable():
    s = _stream(cached=True, also_seen_in=("zilean", "torrentio"))
    assert s.cached is True
    assert s.also_seen_in == ("zilean", "torrentio")


def test_source_defaults_to_torrentio_for_backwards_compatibility():
    assert _stream().source == "torrentio"


def test_torrentio_still_exports_the_old_name():
    assert torrentio.TorrentioStream is streams.Stream


def test_size_is_blank_when_unknown():
    assert _stream(size_gb=0.0).size == ""
    assert _stream(size_gb=5.25).size == "5.25 GB"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_streams.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'streams'`

- [ ] **Step 3: Create `streams.py`**

```python
"""Shared stream model, parsing helpers and ranking for all scrapers.

Zilean, Torrentio and Debridio all produce Stream objects and are ranked by
the same function. That function used to live in torrentio.py, which made it
look Torrentio-specific; it never was.
"""
import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass
class Stream:
    name: str
    title: str
    info_hash: str
    quality: str
    seeders: int
    size_gb: float
    is_season_pack: bool
    languages: tuple[str, ...] = ()
    source: str = "torrentio"
    # True when the debrid provider already has this cached (Debridio's ⚡).
    cached: bool = False
    # Other scrapers that returned this same info_hash, in priority order.
    # Populated by scrapers.fetch_candidates during dedup.
    also_seen_in: tuple[str, ...] = ()

    @property
    def magnet(self) -> str:
        return f"magnet:?xt=urn:btih:{self.info_hash}"

    @property
    def size(self) -> str:
        """Human-readable size (used in UI)."""
        return f"{self.size_gb:.2f} GB" if self.size_gb > 0 else ""
```

- [ ] **Step 4: Replace the dataclass in `torrentio.py` with a re-export**

Delete the `@dataclass class TorrentioStream:` block (lines 82-101) and add
near the other imports:

```python
from streams import Stream

# Historical name. Six call sites and several tests import TorrentioStream
# from here; keep it working.
TorrentioStream = Stream
```

- [ ] **Step 5: Run the tests**

Run: `python -m pytest tests/test_streams.py -q && python -m pytest tests/ -q`
Expected: new tests PASS, full suite 106 passed

- [ ] **Step 6: Commit**

```bash
git add streams.py torrentio.py tests/test_streams.py
git commit -m "refactor: extract Stream model into streams.py

Adds cached and also_seen_in fields. torrentio.TorrentioStream stays as an
alias so existing call sites and tests are untouched."
```

---

### Task 2: Move the shared parsing helpers into `streams.py`

Debridio needs the same quality/size/seeder parsing Torrentio uses. Today those
regexes are private to `torrentio.py`; importing `torrentio._SIZE_RE` from
`debridio.py` would be worse than moving them.

**Files:**
- Modify: `streams.py` (add helpers)
- Modify: `torrentio.py:33,50,51,106,113,118` (import instead of define)
- Test: `tests/test_streams.py`

**Interfaces:**
- Consumes: `streams.Stream` (Task 1).
- Produces: `streams.parse_quality(text: str) -> str` returning one of
  `"2160p" | "1080p" | "720p" | "480p" | ""`;
  `streams.parse_size_gb(text: str) -> float` (0.0 when absent);
  `streams.parse_seeders(text: str) -> int` (0 when absent).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_streams.py`:

```python
def test_parse_quality_recognises_each_bucket():
    assert streams.parse_quality("Movie.2160p.WEB") == "2160p"
    assert streams.parse_quality("Movie.1080p.WEB") == "1080p"
    assert streams.parse_quality("Movie.720p.WEB") == "720p"
    assert streams.parse_quality("Movie.480p.WEB") == "480p"


def test_parse_quality_treats_4k_and_uhd_as_2160p():
    assert streams.parse_quality("Movie 4K HDR") == "2160p"
    assert streams.parse_quality("Movie UHD BluRay") == "2160p"


def test_parse_quality_returns_empty_when_unknown():
    assert streams.parse_quality("Movie.DVDRip") == ""


def test_parse_size_gb_handles_gb_and_mb():
    assert streams.parse_size_gb("⚡ 📺 4k 💾 85.37 GB") == 85.37
    assert streams.parse_size_gb("💾 700 MB") == pytest.approx(700 / 1024)


def test_parse_size_gb_returns_zero_when_absent():
    assert streams.parse_size_gb("no size here") == 0.0


def test_parse_seeders():
    assert streams.parse_seeders("👤 42 💾 5 GB") == 42
    assert streams.parse_seeders("no seeders") == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_streams.py -q`
Expected: FAIL with `AttributeError: module 'streams' has no attribute 'parse_quality'`

- [ ] **Step 3: Add the helpers to `streams.py`**

```python
import re

_QUALITY_PATTERNS = {
    "2160p": re.compile(r"\b(2160p|4k|uhd)\b", re.IGNORECASE),
    "1080p": re.compile(r"\b1080p\b", re.IGNORECASE),
    "720p": re.compile(r"\b720p\b", re.IGNORECASE),
    "480p": re.compile(r"\b480p\b", re.IGNORECASE),
}
_SEEDERS_RE = re.compile(r"👤\s*(\d+)")
_SIZE_RE = re.compile(r"💾\s*([\d.]+)\s*(GB|MB)", re.IGNORECASE)


def parse_quality(text: str) -> str:
    """Highest-resolution bucket named in the text, or '' if none."""
    for quality, pattern in _QUALITY_PATTERNS.items():
        if pattern.search(text or ""):
            return quality
    return ""


def parse_size_gb(text: str) -> float:
    """Size in GB from a '💾 5.2 GB' marker. 0.0 when absent or unparseable."""
    m = _SIZE_RE.search(text or "")
    if not m:
        return 0.0
    value = float(m.group(1))
    # 1024, not 1000: matches torrentio._parse_size_gb, and both feed the
    # same MAX_SIZE_GB threshold and undersized check.
    return value if m.group(2).upper() == "GB" else value / 1024.0


def parse_seeders(text: str) -> int:
    """Seeder count from a '👤 42' marker. 0 when absent."""
    m = _SEEDERS_RE.search(text or "")
    return int(m.group(1)) if m else 0
```

- [ ] **Step 4: Point `torrentio.py` at them**

Delete `_QUALITY_PATTERNS`, `_SEEDERS_RE` and `_SIZE_RE` from `torrentio.py`
and import them so the existing parsing code at lines 106/113/118 keeps
working:

```python
from streams import Stream, _QUALITY_PATTERNS, _SEEDERS_RE, _SIZE_RE
```

Do not rewrite the parsing bodies in this task — the goal is a pure move that
the existing suite proves is behaviour-preserving.

- [ ] **Step 5: Run the tests**

Run: `python -m pytest tests/ -q`
Expected: 113 passed. `tests/test_torrentio_rank.py` passing unchanged is the
proof the move was behaviour-preserving.

- [ ] **Step 6: Commit**

```bash
git add streams.py torrentio.py tests/test_streams.py
git commit -m "refactor: move shared stream parsing helpers into streams.py

Debridio needs the same quality/size/seeder parsing; reaching into
torrentio._SIZE_RE from another scraper would be worse than moving them."
```

---

### Task 3: Move `rank_streams` into `streams.py`

The seven ranking regexes (`_REMUX_RE`, `_BLURAY_RE`, `_CAM_RE`, `_WEBDL_RE`,
`_HEVC_RE`, `_DV_RE`, `_HDR10_RE`) are used **only** inside `rank_streams`
(torrentio.py:243-337), and `_min_plausible_size_gb`/`_MIN_GB_PER_90MIN` only
by it, so this is a clean lift.

**Files:**
- Modify: `streams.py` (receive `rank_streams` + its private helpers)
- Modify: `torrentio.py:38-49,58-80,206-345` (remove, re-export)
- Test: `tests/test_streams.py`

**Interfaces:**
- Consumes: `streams.Stream` (Task 1).
- Produces: `streams.rank_streams(streams: list[Stream], prefer_season_pack: bool = False, override: dict | None = None) -> list[Stream]`.
  `torrentio.rank_streams` remains a working alias.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_streams.py`:

```python
def test_rank_streams_is_reexported_from_torrentio():
    assert torrentio.rank_streams is streams.rank_streams


def test_rank_streams_soft_filter_allows_remux_when_it_is_all_there_is(monkeypatch):
    # Mycelium's excludes self-disable rather than return nothing. This is the
    # property that stops us pushing filters down to Debridio; lock it in.
    import settings as _settings
    monkeypatch.setattr(_settings, "get",
                        lambda k, d=None: True if k == "EXCLUDE_REMUX" else d)
    only_remux = [_stream(name="Movie 2160p BluRay REMUX", title="Movie REMUX")]
    assert len(streams.rank_streams(only_remux)) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_streams.py -q`
Expected: FAIL with `AttributeError: module 'streams' has no attribute 'rank_streams'`

- [ ] **Step 3: Move the code**

Cut from `torrentio.py` into `streams.py`, unchanged: `_REMUX_RE`,
`_BLURAY_RE`, `_CAM_RE`, `_WEBDL_RE`, `_HEVC_RE`, `_DV_RE`, `_HDR10_RE`,
`_MIN_GB_PER_90MIN`, `_min_plausible_size_gb`, and `rank_streams`. Move the
`from config import (...)` names `rank_streams` needs — `ALLOW_4K`,
`AUDIO_LANGUAGE_PREFERENCE`, `EXCLUDE_BLURAY`, `EXCLUDE_CAM`, `EXCLUDE_DV_P5`,
`EXCLUDE_LANGUAGES`, `EXCLUDE_REMUX`, `EXCLUDE_UNDERSIZED_RELEASES`,
`MAX_SIZE_GB`, `MIN_SEEDERS`, `PREFER_HEVC`, `PREFER_WEBDL`,
`QUALITY_PREFERENCE` — into `streams.py`'s import block.

Change the body's type annotations from `TorrentioStream` to `Stream`. Change
nothing else: the soft-filter chain and its ordering (DV → remux → bluray →
cam → undersized → seeders → size → languages) must be preserved exactly.

In `torrentio.py`:

```python
from streams import Stream, rank_streams, _QUALITY_PATTERNS, _SEEDERS_RE, _SIZE_RE

TorrentioStream = Stream
```

- [ ] **Step 4: Run the tests**

Run: `python -m pytest tests/ -q`
Expected: 115 passed. `tests/test_torrentio_rank.py` must pass untouched.

- [ ] **Step 5: Commit**

```bash
git add streams.py torrentio.py tests/test_streams.py
git commit -m "refactor: move rank_streams into streams.py

It ranks streams from every scraper, not just Torrentio's. The seven
ranking regexes are used only by it, so the lift is clean.
torrentio.rank_streams stays as an alias."
```

---

### Task 4: Register the Debridio settings

**Files:**
- Modify: `config.py` (after line 42, near `TORRENTIO_BASE_URL`)
- Modify: `settings.py:19` (`_BOOL_KEYS`), `:58` (`_INT_KEYS`), `:100` (`HOT_RELOAD`), `:170` (Connections group)
- Test: `tests/test_debridio_settings.py`

**Interfaces:**
- Consumes: nothing.
- Produces: settings keys `DEBRIDIO_ENABLED` (bool, default `False`),
  `DEBRIDIO_API_KEY` (str, `""`), `DEBRIDIO_BASE_URL` (str,
  `"https://addon.debridio.com"`), `DEBRIDIO_MAX_RESULTS` (int, `100`),
  `DEBRIDIO_CONFIG_TOKEN` (str, `""`).

- [ ] **Step 1: Write the failing test**

Create `tests/test_debridio_settings.py`:

```python
import os
import sys

os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

sys.modules.pop("settings", None)

import pytest

import db
import settings


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    db.init()
    yield


def test_enabled_defaults_to_false():
    assert settings.get("DEBRIDIO_ENABLED") is False


def test_enabled_coerces_to_bool_not_string():
    settings.set("DEBRIDIO_ENABLED", True)
    assert settings.get("DEBRIDIO_ENABLED") is True
    settings.set("DEBRIDIO_ENABLED", False)
    assert settings.get("DEBRIDIO_ENABLED") is False


def test_max_results_coerces_to_int():
    settings.set("DEBRIDIO_MAX_RESULTS", "250")
    assert settings.get("DEBRIDIO_MAX_RESULTS") == 250


def test_base_url_has_a_default():
    assert settings.get("DEBRIDIO_BASE_URL") == "https://addon.debridio.com"


def test_secrets_are_named_so_the_ui_masks_them():
    # templates/ui.html:1233 masks a field when its key matches this pattern.
    # A secret whose name misses it renders in plaintext, pre-filled.
    import re
    predicate = re.compile(r"KEY|TOKEN|SECRET|PASSWORD")
    for key in ("DEBRIDIO_API_KEY", "DEBRIDIO_CONFIG_TOKEN"):
        assert predicate.search(key), f"{key} would render unmasked"


def test_hot_reload_covers_every_debridio_key():
    for key in ("DEBRIDIO_ENABLED", "DEBRIDIO_API_KEY", "DEBRIDIO_BASE_URL",
                "DEBRIDIO_MAX_RESULTS", "DEBRIDIO_CONFIG_TOKEN"):
        assert key in settings.HOT_RELOAD, f"{key} would need a restart"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_debridio_settings.py -q`
Expected: FAIL — `assert None is False` on the first test

- [ ] **Step 3: Add to `config.py`**

```python
DEBRIDIO_ENABLED = _env("DEBRIDIO_ENABLED", "false").lower() in ("1", "true", "yes")
DEBRIDIO_API_KEY = _env("DEBRIDIO_API_KEY", "")
DEBRIDIO_BASE_URL = _env("DEBRIDIO_BASE_URL", "https://addon.debridio.com")
DEBRIDIO_MAX_RESULTS = _env_int("DEBRIDIO_MAX_RESULTS", 100)
# Escape hatch: a full pre-built config segment, used verbatim when set. We
# build the config against an undocumented third-party schema; if Debridio
# changes it, this keeps users running without waiting for a release.
DEBRIDIO_CONFIG_TOKEN = _env("DEBRIDIO_CONFIG_TOKEN", "")
```

- [ ] **Step 4: Register in `settings.py`**

Add `"DEBRIDIO_ENABLED"` to `_BOOL_KEYS`, `"DEBRIDIO_MAX_RESULTS"` to
`_INT_KEYS`, all five keys to `HOT_RELOAD`, and to the `connections` group's
`keys` list after `"TMDB_API_KEY"`:

```python
"DEBRIDIO_ENABLED", "DEBRIDIO_API_KEY", "DEBRIDIO_BASE_URL",
"DEBRIDIO_MAX_RESULTS", "DEBRIDIO_CONFIG_TOKEN",
```

- [ ] **Step 5: Run the tests**

Run: `python -m pytest tests/ -q`
Expected: 121 passed

- [ ] **Step 6: Commit**

```bash
git add config.py settings.py tests/test_debridio_settings.py
git commit -m "feat: register Debridio settings

Key names carry KEY/TOKEN so the settings-UI masking predicate catches
them; a test locks that in, since a secret named otherwise renders in
plaintext."
```

---

### Task 5: Build the Debridio config token, with redaction

**Files:**
- Create: `debridio.py`
- Test: `tests/test_debridio.py`

**Interfaces:**
- Consumes: settings from Task 4.
- Produces: `debridio.build_config_token() -> str` (base64 config segment, `""`
  when unconfigured); `debridio.redact(text: str) -> str`;
  `debridio.is_configured() -> bool`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_debridio.py`:

```python
import base64
import json
import os
import sys

os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import debridio


@pytest.fixture
def configured(monkeypatch):
    values = {"DEBRIDIO_API_KEY": "dk" * 16, "TORBOX_API_KEY": "tb-uuid-value",
              "DEBRIDIO_BASE_URL": "https://addon.debridio.com",
              "DEBRIDIO_MAX_RESULTS": 100, "DEBRIDIO_CONFIG_TOKEN": "",
              "DEBRIDIO_ENABLED": True}
    monkeypatch.setattr(debridio._settings, "get",
                        lambda k, d=None: values.get(k, d))
    return values


def _decode(token):
    return json.loads(base64.b64decode(token))


def test_config_contains_both_credentials(configured):
    cfg = _decode(debridio.build_config_token())
    assert cfg["api_key"] == "dk" * 16
    assert cfg["providerKey"] == "tb-uuid-value"
    assert cfg["provider"] == "torbox"


def test_config_is_permissive(configured):
    # Mycelium's filters are soft and Debridio's are hard. Pushing ours down
    # would stop the "only remux available; allowing them" fallback firing.
    cfg = _decode(debridio.build_config_token())
    assert cfg["excludedQualities"] == []
    assert cfg["preferredLang"] == []
    assert cfg["maxSize"] == ""
    assert cfg["disableUncached"] is False
    assert "unknown" in cfg["resolutions"]
    for res in ("8k", "4k", "1440p", "1080p", "720p", "480p", "360p"):
        assert res in cfg["resolutions"]


def test_config_token_override_is_used_verbatim(monkeypatch):
    monkeypatch.setattr(debridio._settings, "get",
                        lambda k, d=None: "PREBUILT" if k == "DEBRIDIO_CONFIG_TOKEN" else d)
    assert debridio.build_config_token() == "PREBUILT"


def test_unconfigured_returns_empty_token(monkeypatch):
    monkeypatch.setattr(debridio._settings, "get", lambda k, d=None: d)
    assert debridio.build_config_token() == ""
    assert debridio.is_configured() is False


def test_is_configured_requires_both_keys(monkeypatch):
    monkeypatch.setattr(debridio._settings, "get",
                        lambda k, d=None: "x" if k == "DEBRIDIO_API_KEY" else d)
    assert debridio.is_configured() is False


def test_redact_removes_the_config_segment():
    url = "https://addon.debridio.com/eyJhcGlfa2V5IjoiEXAMPLE/stream/movie/tt1.json"
    out = debridio.redact(url)
    assert "eyJhcGlfa2V5" not in out
    assert "addon.debridio.com" in out


def test_redact_removes_credentials_from_a_play_url():
    url = ("https://addon.debridio.com/play/movie/torbox/"
           + "d" * 32 + "/tb-uuid-value/" + "a" * 40 + "/File.mkv")
    out = debridio.redact(url)
    assert "d" * 32 not in out
    assert "tb-uuid-value" not in out


def test_redact_handles_none_and_empty():
    assert debridio.redact("") == ""
    assert debridio.redact(None) == ""


def test_redact_scrubs_the_live_credential_values(configured):
    msg = "Error for url: https://x/" + "dk" * 16 + "/y and key tb-uuid-value"
    out = debridio.redact(msg)
    assert "dk" * 16 not in out
    assert "tb-uuid-value" not in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_debridio.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'debridio'`

- [ ] **Step 3: Create `debridio.py`**

```python
"""Debridio scraper.

Debridio is a Stremio addon: GET {base}/{config}/stream/{type}/{id}.json.
Its stream objects carry no infoHash field, but the BitTorrent hash is present
in behaviorHints.bingeGroup as 'debridio-<40 hex>' and again in the play-URL
path. Verified 702/702 consistent, with 88 of Torrentio's 111 hashes for the
same title appearing verbatim.

The config segment is base64 JSON holding the Debridio API key AND the user's
TorBox key, so the request URL is a secret. Nothing here may log it.
"""
import base64
import json
import logging
import re

import requests

import config
import settings as _settings

log = logging.getLogger(__name__)

_RESOLUTIONS = ["8k", "4k", "1440p", "1080p", "720p", "480p", "360p", "unknown"]
_HEX40_RE = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)
_B64_SEGMENT_RE = re.compile(r"/(?:ey[A-Za-z0-9+/=_-]{16,})")


def _s(key: str):
    return _settings.get(key, getattr(config, key, None))


def is_configured() -> bool:
    """Debridio needs its own key and a TorBox key to proxy for."""
    return bool((_s("DEBRIDIO_API_KEY") or "").strip()
                and (_s("TORBOX_API_KEY") or "").strip())


def build_config_token() -> str:
    """Base64 config segment for the addon URL, or '' when unconfigured.

    Deliberately permissive: every resolution, no excluded qualities, no size
    limit. Mycelium's own filters are soft (they self-disable rather than
    return nothing) while Debridio's are hard, so pushing ours down would
    remove streams before rank_streams could decide to allow them anyway.
    """
    override = (_s("DEBRIDIO_CONFIG_TOKEN") or "").strip()
    if override:
        return override
    if not is_configured():
        return ""
    cfg = {
        "api_key": (_s("DEBRIDIO_API_KEY") or "").strip(),
        "provider": "torbox",
        "providerKey": (_s("TORBOX_API_KEY") or "").strip(),
        "disableUncached": False,
        "maxSize": "",
        "maxReturnPerQuality": str(_s("DEBRIDIO_MAX_RESULTS") or 100),
        "resolutions": list(_RESOLUTIONS),
        "excludedQualities": [],
        "preferredLang": [],
    }
    return base64.b64encode(json.dumps(cfg, separators=(",", ":")).encode()).decode()


def redact(text) -> str:
    """Strip Debridio credentials from a URL or exception message.

    Every log, HTTP response and health payload that might carry a Debridio
    URL must pass through this. The config segment and the play-URL path both
    contain the user's TorBox key.

    Scrubs the live credential values first: requests embeds URLs in exception
    messages in shapes we cannot enumerate, so matching the actual secrets is
    the only reliable protection. The pattern rules below are a backstop.
    """
    if not text:
        return ""
    out = str(text)
    for key in ("DEBRIDIO_CONFIG_TOKEN", "DEBRIDIO_API_KEY", "TORBOX_API_KEY"):
        secret = (_s(key) or "").strip()
        if len(secret) >= 8:          # too short to be a key; avoid over-scrubbing
            out = out.replace(secret, "<redacted>")
    out = _B64_SEGMENT_RE.sub("/<config>", out)
    out = re.sub(r"/play/(\w+)/(\w+)/[^/]+/[^/]+/", r"/play/\1/\2/<redacted>/<redacted>/", out)
    return out
```

- [ ] **Step 4: Run the tests**

Run: `python -m pytest tests/test_debridio.py -q`
Expected: PASS (10 tests). Full suite: 131 passed, 0 failed

- [ ] **Step 5: Commit**

```bash
git add debridio.py tests/test_debridio.py
git commit -m "feat(debridio): config token builder and credential redaction

The config embeds the user's TorBox key, so the request URL is a secret.
redact() is the single chokepoint every log path must use."
```

---

### Task 6: Fetch and parse Debridio streams

**Files:**
- Modify: `debridio.py`
- Test: `tests/test_debridio.py`

**Interfaces:**
- Consumes: `streams.Stream`, `streams.parse_quality/parse_size_gb/parse_seeders`
  (Tasks 1-2); `debridio.build_config_token`, `debridio.redact` (Task 5).
- Produces: `debridio.fetch(media_type: str, imdb_id: str, season: int | None = None, episode: int | None = None, timeout: int = 30) -> list[Stream]`.
  Signature matches `torrentio.fetch_streams`. Never raises.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_debridio.py`:

```python
import streams as streams_mod

_PAYLOAD = {"streams": [
    {"name": "[TB ⚡] \nDebridio 4k DV|HDR REMUX",
     "title": "Dune.Part.Two.2024.2160p.BluRay.Remux.mkv\n⚡ 📺 4k 💾 85.37 GB\n👤 12",
     "url": "https://addon.debridio.com/play/movie/torbox/k/p/" + "a" * 40 + "/F.mkv",
     "behaviorHints": {"bingeGroup": "debridio-" + "a" * 40,
                       "filename": "Dune.Part.Two.2024.2160p.BluRay.Remux.mkv"}},
    {"name": "Debridio 1080p",
     "title": "Show.S01E01.1080p.WEB-DL.mkv\n💾 2.10 GB",
     "url": "https://addon.debridio.com/play/series/torbox/k/p/" + "b" * 40 + "/G.mkv",
     "behaviorHints": {"filename": "Show.S01E01.1080p.WEB-DL.mkv"}},
]}


class _Resp:
    def __init__(self, payload, status=200):
        self._p, self.status_code = payload, status

    def raise_for_status(self):
        if self.status_code >= 400:
            # requests puts the full URL in its exception message. Shape this
            # like a real one: a base64 config segment starting "ey".
            raise RuntimeError(
                f"{self.status_code} Server Error for url: https://addon.debridio.com/"
                "eyJhcGlfa2V5IjoiZGtka2RrZGtka2RrZGsi/stream/movie/tt1.json")

    def json(self):
        return self._p


def test_hash_comes_from_binge_group(configured, monkeypatch):
    monkeypatch.setattr(debridio.requests, "get", lambda *a, **k: _Resp(_PAYLOAD))
    out = debridio.fetch("movie", "tt15239678")
    assert out[0].info_hash == "a" * 40


def test_hash_falls_back_to_the_url_path(configured, monkeypatch):
    monkeypatch.setattr(debridio.requests, "get", lambda *a, **k: _Resp(_PAYLOAD))
    out = debridio.fetch("series", "tt0903747", season=1, episode=1)
    assert out[1].info_hash == "b" * 40


def test_source_is_always_debridio(configured, monkeypatch):
    # Stream.source defaults to "torrentio"; forgetting this misattributes
    # every Debridio win in the Source Win Rate metric instead of erroring.
    monkeypatch.setattr(debridio.requests, "get", lambda *a, **k: _Resp(_PAYLOAD))
    assert all(s.source == "debridio" for s in debridio.fetch("movie", "tt1"))


def test_cached_flag_from_lightning_marker(configured, monkeypatch):
    monkeypatch.setattr(debridio.requests, "get", lambda *a, **k: _Resp(_PAYLOAD))
    out = debridio.fetch("movie", "tt1")
    assert out[0].cached is True
    assert out[1].cached is False


def test_quality_and_size_and_seeders_parsed(configured, monkeypatch):
    monkeypatch.setattr(debridio.requests, "get", lambda *a, **k: _Resp(_PAYLOAD))
    out = debridio.fetch("movie", "tt1")
    assert out[0].quality == "2160p"
    assert out[0].size_gb == 85.37
    assert out[0].seeders == 12
    assert out[1].quality == "1080p"


def test_streams_without_a_hash_are_skipped(configured, monkeypatch):
    payload = {"streams": [{"name": "x", "title": "y", "url": "https://x/play/a/b/c/d/e.mkv",
                            "behaviorHints": {}}]}
    monkeypatch.setattr(debridio.requests, "get", lambda *a, **k: _Resp(payload))
    assert debridio.fetch("movie", "tt1") == []


def test_series_id_is_colon_delimited(configured, monkeypatch):
    seen = {}

    def _get(url, **kw):
        seen["url"] = url
        return _Resp({"streams": []})

    monkeypatch.setattr(debridio.requests, "get", _get)
    debridio.fetch("series", "tt0903747", season=2, episode=5)
    assert "/stream/series/tt0903747:2:5.json" in seen["url"]


def test_http_error_returns_empty_and_never_raises(configured, monkeypatch):
    monkeypatch.setattr(debridio.requests, "get", lambda *a, **k: _Resp({}, status=500))
    assert debridio.fetch("movie", "tt1") == []


def test_unconfigured_returns_empty_without_calling_out(monkeypatch):
    monkeypatch.setattr(debridio._settings, "get", lambda k, d=None: d)

    def _boom(*a, **k):
        raise AssertionError("must not make a request when unconfigured")

    monkeypatch.setattr(debridio.requests, "get", _boom)
    assert debridio.fetch("movie", "tt1") == []


def test_results_are_capped(configured, monkeypatch):
    many = {"streams": [
        {"name": "n", "title": f"T.1080p.mkv\n💾 {i}.00 GB",
         "url": "https://x/play/movie/torbox/k/p/" + f"{i:040x}" + "/f.mkv",
         "behaviorHints": {"bingeGroup": "debridio-" + f"{i:040x}"}}
        for i in range(1, 60)]}
    monkeypatch.setattr(debridio.requests, "get", lambda *a, **k: _Resp(many))
    monkeypatch.setattr(debridio, "_max_results", lambda: 10)
    assert len(debridio.fetch("movie", "tt1")) == 10


def test_url_never_reaches_the_logs(configured, monkeypatch, caplog):
    monkeypatch.setattr(debridio.requests, "get", lambda *a, **k: _Resp({}, status=500))
    with caplog.at_level("DEBUG"):
        debridio.fetch("movie", "tt1")
    blob = " ".join(r.getMessage() for r in caplog.records)
    assert "dkdk" not in blob
    assert "tb-uuid-value" not in blob
    assert "eyJhcGlfa2V5" not in blob
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_debridio.py -q`
Expected: FAIL with `AttributeError: module 'debridio' has no attribute 'fetch'`

- [ ] **Step 3: Implement `fetch`**

Append to `debridio.py`:

```python
from streams import Stream, parse_quality, parse_seeders, parse_size_gb

_SEASON_PACK_RE = re.compile(r"\b(complete|season|s\d{1,2}(?!\s*e))\b", re.IGNORECASE)


def _max_results() -> int:
    try:
        return int(_s("DEBRIDIO_MAX_RESULTS") or 100)
    except (TypeError, ValueError):
        return 100


def _extract_hash(item: dict) -> str:
    """Recover the info hash from bingeGroup, falling back to the URL path."""
    binge = (item.get("behaviorHints") or {}).get("bingeGroup") or ""
    if binge.startswith("debridio-"):
        candidate = binge[len("debridio-"):]
        if _HEX40_RE.match(candidate):
            return candidate.lower()
    for part in (item.get("url") or "").split("/"):
        if _HEX40_RE.match(part):
            return part.lower()
    return ""


def _to_stream(item: dict) -> Stream | None:
    info_hash = _extract_hash(item)
    if not info_hash:
        return None
    name = item.get("name") or ""
    title = item.get("title") or ""
    filename = (item.get("behaviorHints") or {}).get("filename") or ""
    blob = f"{name} {title} {filename}"
    return Stream(
        name=name,
        title=title or filename,
        info_hash=info_hash,
        quality=parse_quality(blob),
        seeders=parse_seeders(title),
        size_gb=parse_size_gb(title),
        is_season_pack=bool(_SEASON_PACK_RE.search(filename or title)),
        source="debridio",
        cached="⚡" in name,
    )


def fetch(media_type: str, imdb_id: str, season: int | None = None,
          episode: int | None = None, timeout: int = 30) -> list[Stream]:
    """Return Debridio candidates. Never raises; returns [] on any failure."""
    token = build_config_token()
    if not token:
        return []
    kind = "movie" if media_type == "movie" else "series"
    stream_id = imdb_id if season is None else f"{imdb_id}:{season}:{episode or 1}"
    base = (_s("DEBRIDIO_BASE_URL") or "https://addon.debridio.com").rstrip("/")
    url = f"{base}/{token}/stream/{kind}/{stream_id}.json"

    log.info("Querying Debridio for %s (%s)", imdb_id, kind)
    try:
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
        payload = resp.json() or {}
    except Exception as exc:
        log.warning("Debridio request failed for %s: %s", imdb_id, redact(exc))
        return []

    raw = payload.get("streams") or []
    out, skipped = [], 0
    for item in raw:
        stream = _to_stream(item)
        if stream is None:
            skipped += 1
        else:
            out.append(stream)
    if skipped:
        log.warning("Debridio: %d/%d stream(s) had no recoverable info hash "
                    "for %s - the response shape may have changed",
                    skipped, len(raw), imdb_id)

    _QUALITY_ORDER = {"2160p": 0, "1080p": 1, "720p": 2, "480p": 3, "": 4}
    out.sort(key=lambda s: (_QUALITY_ORDER.get(s.quality, 4), -s.size_gb))
    capped = out[:_max_results()]
    log.info("Debridio: %d stream(s) for %s (%d after cap)", len(out), imdb_id, len(capped))
    return capped
```

- [ ] **Step 4: Run the tests**

Run: `python -m pytest tests/test_debridio.py -q && python -m pytest tests/ -q`
Expected: 21 Debridio tests PASS, full suite 142 passed, 0 failed

- [ ] **Step 5: Commit**

```bash
git add debridio.py tests/test_debridio.py
git commit -m "feat(debridio): fetch and parse streams

Hash from behaviorHints.bingeGroup, falling back to the play-URL path.
Streams with no recoverable hash are skipped and counted, so a silent
upstream shape change surfaces in the logs rather than vanishing."
```

---

### Task 7: Health probe for Debridio

**Files:**
- Modify: `health_cache.py:25-38` (`_probe`), `:41-46` (`is_up`)
- Modify: `health.py` (add entry to `check_all`)
- Test: `tests/test_debridio.py`

**Interfaces:**
- Consumes: `debridio.build_config_token`, `debridio.is_configured`,
  `debridio.redact` (Task 5).
- Produces: `health_cache.is_up("debridio") -> bool`; a `{"name": "Debridio",
  ...}` entry in `health.check_all()`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_debridio.py`:

```python
def test_is_up_false_when_disabled(monkeypatch):
    import health_cache
    monkeypatch.setattr(health_cache._settings, "get",
                        lambda k, d=None: False if k == "DEBRIDIO_ENABLED" else d)
    health_cache._cache.clear()
    assert health_cache.is_up("debridio") is False


def test_is_up_false_when_unconfigured(monkeypatch):
    import health_cache
    monkeypatch.setattr(health_cache._settings, "get",
                        lambda k, d=None: True if k == "DEBRIDIO_ENABLED" else d)
    monkeypatch.setattr(debridio, "is_configured", lambda: False)
    health_cache._cache.clear()
    assert health_cache.is_up("debridio") is False


def test_health_error_is_redacted(monkeypatch):
    # requests embeds the URL in its exception messages, and health.py:23
    # returns str(exc)[:80] straight into an HTTP response.
    import health
    monkeypatch.setattr(health.settings, "get",
                        lambda k, d=None: {"DEBRIDIO_ENABLED": True}.get(k, d))
    monkeypatch.setattr(debridio, "is_configured", lambda: True)
    monkeypatch.setattr(debridio, "build_config_token", lambda: "eyJhcGlfa2V5SECRET")

    def _boom(*a, **k):
        raise RuntimeError("failed for url: https://addon.debridio.com/eyJhcGlfa2V5SECRET/manifest.json")

    monkeypatch.setattr(health.requests, "get", _boom)
    entry = [s for s in health.check_all() if s["name"] == "Debridio"][0]
    assert "SECRET" not in str(entry)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_debridio.py -k "is_up or health" -q`
Expected: FAIL — `is_up("debridio")` returns True (unknown names fall through
to `return True` in `_probe`)

- [ ] **Step 3: Add the probe to `health_cache.py`**

In `_probe`, before the final `return True`:

```python
        if name == "debridio":
            import debridio
            token = debridio.build_config_token()
            if not token:
                return False
            base = (_settings.get("DEBRIDIO_BASE_URL", "https://addon.debridio.com") or "").rstrip("/")
            r = requests.get(f"{base}/{token}/manifest.json", timeout=3)
            return r.status_code < 500
```

Change the `except` clause to redact, since the exception embeds the URL:

```python
    except Exception as exc:
        import debridio
        log.debug("health probe %s failed: %s", name, debridio.redact(exc))
        return False
```

In `is_up`, alongside the Zilean guard:

```python
    if name == "debridio":
        import debridio
        if not _settings.get("DEBRIDIO_ENABLED", False) or not debridio.is_configured():
            return False
```

- [ ] **Step 4: Add the entry to `health.py::check_all`**

After the Torrentio line:

```python
    import debridio as _debridio
    if settings.get("DEBRIDIO_ENABLED", False) and _debridio.is_configured():
        base = _s("DEBRIDIO_BASE_URL").rstrip("/") or "https://addon.debridio.com"
        entry = _ping("Debridio", f"{base}/{_debridio.build_config_token()}/manifest.json")
        if entry.get("error"):
            entry["error"] = _debridio.redact(entry["error"])[:80]
        services.append(entry)
    else:
        services.append({"name": "Debridio", "status": "disabled"})
```

- [ ] **Step 5: Run the tests**

Run: `python -m pytest tests/ -q`
Expected: 145 passed, 0 failed

- [ ] **Step 6: Commit**

```bash
git add health_cache.py health.py tests/test_debridio.py
git commit -m "feat(debridio): health probe with redacted errors

requests embeds the URL in exception messages and health.py returns
str(exc) into an HTTP response, so both paths redact."
```

---

### Task 8: The `scrapers.py` orchestrator

**Files:**
- Create: `scrapers.py`
- Test: `tests/test_scrapers.py`

**Interfaces:**
- Consumes: `debridio.fetch` (Task 6), `zilean.fetch_streams(imdb_id, season, episode)`,
  `torrentio.fetch_streams(media_type, imdb_id, season, episode)`,
  `streams.rank_streams` (Task 3), `health_cache.is_up` (Task 7).
- Produces: `scrapers.fetch_candidates(media_type: str, imdb_id: str, season: int | None = None, episode: int | None = None, *, prefer_season_pack: bool = False, override: dict | None = None) -> list[Stream]`.

Note the signature mismatch this adapts: `zilean.fetch_streams` takes
`(imdb_id, season, episode, timeout)` while `torrentio.fetch_streams` takes
`(media_type, imdb_id, season, episode, timeout)`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_scrapers.py`:

```python
import os
import sys
import time

os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import scrapers
import streams as streams_mod


def _s(h, source, quality="1080p"):
    return streams_mod.Stream(name=source, title=f"T.{quality}", info_hash=h,
                              quality=quality, seeders=10, size_gb=5.0,
                              is_season_pack=False, source=source)


@pytest.fixture(autouse=True)
def _all_enabled_and_healthy(monkeypatch):
    monkeypatch.setattr(scrapers._settings, "get", lambda k, d=None: True)
    monkeypatch.setattr(scrapers.health_cache, "is_up", lambda name: True)
    monkeypatch.setattr(scrapers, "rank_streams",
                        lambda s, prefer_season_pack=False, override=None: list(s))


def _wire(monkeypatch, deb=(), zil=(), tor=()):
    monkeypatch.setattr(scrapers.debridio, "fetch", lambda *a, **k: list(deb))
    monkeypatch.setattr(scrapers.zilean, "fetch_streams", lambda *a, **k: list(zil))
    monkeypatch.setattr(scrapers.torrentio, "fetch_streams", lambda *a, **k: list(tor))


def test_debridio_wins_a_duplicate_hash(monkeypatch):
    h = "a" * 40
    _wire(monkeypatch, deb=[_s(h, "debridio")], tor=[_s(h, "torrentio")])
    out = scrapers.fetch_candidates("movie", "tt1")
    assert len(out) == 1
    assert out[0].source == "debridio"


def test_also_seen_in_records_the_other_sources_in_priority_order(monkeypatch):
    h = "a" * 40
    _wire(monkeypatch, deb=[_s(h, "debridio")], zil=[_s(h, "zilean")],
          tor=[_s(h, "torrentio")])
    out = scrapers.fetch_candidates("movie", "tt1")
    assert out[0].also_seen_in == ("zilean", "torrentio")


def test_unique_result_has_empty_also_seen_in(monkeypatch):
    _wire(monkeypatch, deb=[_s("a" * 40, "debridio")], tor=[_s("b" * 40, "torrentio")])
    out = scrapers.fetch_candidates("movie", "tt1")
    assert all(s.also_seen_in == () for s in out)


def test_all_sources_are_merged(monkeypatch):
    _wire(monkeypatch, deb=[_s("a" * 40, "debridio")], zil=[_s("b" * 40, "zilean")],
          tor=[_s("c" * 40, "torrentio")])
    assert len(scrapers.fetch_candidates("movie", "tt1")) == 3


def test_a_failing_scraper_does_not_fail_the_call(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("debridio exploded")

    monkeypatch.setattr(scrapers.debridio, "fetch", _boom)
    monkeypatch.setattr(scrapers.zilean, "fetch_streams", lambda *a, **k: [])
    monkeypatch.setattr(scrapers.torrentio, "fetch_streams",
                        lambda *a, **k: [_s("c" * 40, "torrentio")])
    out = scrapers.fetch_candidates("movie", "tt1")
    assert [s.source for s in out] == ["torrentio"]


def test_disabled_scraper_is_not_called(monkeypatch):
    monkeypatch.setattr(scrapers._settings, "get",
                        lambda k, d=None: k != "DEBRIDIO_ENABLED")

    def _boom(*a, **k):
        raise AssertionError("disabled scraper must not be called")

    monkeypatch.setattr(scrapers.debridio, "fetch", _boom)
    monkeypatch.setattr(scrapers.zilean, "fetch_streams", lambda *a, **k: [])
    monkeypatch.setattr(scrapers.torrentio, "fetch_streams", lambda *a, **k: [])
    assert scrapers.fetch_candidates("movie", "tt1") == []


def test_unhealthy_scraper_is_skipped(monkeypatch):
    monkeypatch.setattr(scrapers.health_cache, "is_up", lambda name: name != "debridio")

    def _boom(*a, **k):
        raise AssertionError("unhealthy scraper must not be called")

    monkeypatch.setattr(scrapers.debridio, "fetch", _boom)
    monkeypatch.setattr(scrapers.zilean, "fetch_streams", lambda *a, **k: [])
    monkeypatch.setattr(scrapers.torrentio, "fetch_streams", lambda *a, **k: [])
    assert scrapers.fetch_candidates("movie", "tt1") == []


def test_merge_order_is_priority_not_completion_order(monkeypatch):
    h = "a" * 40

    def _slow_debridio(*a, **k):
        time.sleep(0.15)
        return [_s(h, "debridio")]

    monkeypatch.setattr(scrapers.debridio, "fetch", _slow_debridio)
    monkeypatch.setattr(scrapers.zilean, "fetch_streams", lambda *a, **k: [])
    monkeypatch.setattr(scrapers.torrentio, "fetch_streams", lambda *a, **k: [_s(h, "torrentio")])
    out = scrapers.fetch_candidates("movie", "tt1")
    assert out[0].source == "debridio"
    assert out[0].also_seen_in == ("torrentio",)


def test_zilean_receives_no_media_type_argument(monkeypatch):
    seen = {}

    def _zilean(imdb_id, season=None, episode=None):
        seen["args"] = (imdb_id, season, episode)
        return []

    monkeypatch.setattr(scrapers.debridio, "fetch", lambda *a, **k: [])
    monkeypatch.setattr(scrapers.zilean, "fetch_streams", _zilean)
    monkeypatch.setattr(scrapers.torrentio, "fetch_streams", lambda *a, **k: [])
    scrapers.fetch_candidates("series", "tt9", season=2, episode=3)
    assert seen["args"] == ("tt9", 2, 3)


def test_empty_everywhere_returns_empty(monkeypatch):
    _wire(monkeypatch)
    assert scrapers.fetch_candidates("movie", "tt1") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_scrapers.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'scrapers'`

- [ ] **Step 3: Create `scrapers.py`**

```python
"""Single entry point for candidate discovery across every scraper.

Order in _SCRAPERS is priority. All enabled, healthy scrapers are queried
concurrently, then merged in priority order (NOT completion order) so dedup is
deterministic: the highest-priority source keeps the stream and the others are
recorded in also_seen_in.
"""
import concurrent.futures
import logging

import debridio
import health_cache
import settings as _settings
import torrentio
import zilean
from streams import Stream, rank_streams

log = logging.getLogger(__name__)


def _fetch_debridio(media_type, imdb_id, season, episode):
    return debridio.fetch(media_type, imdb_id, season, episode)


def _fetch_zilean(media_type, imdb_id, season, episode):
    # zilean.fetch_streams takes no media_type.
    return zilean.fetch_streams(imdb_id, season=season, episode=episode)


def _fetch_torrentio(media_type, imdb_id, season, episode):
    kind = "movie" if media_type == "movie" else "series"
    return torrentio.fetch_streams(kind, imdb_id, season=season, episode=episode)


# (name, settings key or None if always on, fetch adapter)
_SCRAPERS = [
    ("debridio", "DEBRIDIO_ENABLED", _fetch_debridio),
    ("zilean", "ZILEAN_ENABLED", _fetch_zilean),
    ("torrentio", None, _fetch_torrentio),
]


def _active() -> list[tuple]:
    out = []
    for name, key, fn in _SCRAPERS:
        if key is not None and not _settings.get(key, False):
            continue
        if not health_cache.is_up(name):
            log.debug("Scraper %s skipped: reported down", name)
            continue
        out.append((name, fn))
    return out


def fetch_candidates(media_type: str, imdb_id: str, season: int | None = None,
                     episode: int | None = None, *, prefer_season_pack: bool = False,
                     override: dict | None = None) -> list[Stream]:
    """Fetch, merge, dedup and rank candidates from every active scraper."""
    active = _active()
    if not active:
        log.warning("No scrapers active for %s", imdb_id)
        return []

    results: dict[str, list[Stream]] = {name: [] for name, _ in active}
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(active)) as ex:
        futures = {ex.submit(fn, media_type, imdb_id, season, episode): name
                   for name, fn in active}
        for future in concurrent.futures.as_completed(futures):
            name = futures[future]
            try:
                results[name] = future.result() or []
            except Exception as exc:
                log.warning("Scraper %s failed for %s: %s", name, imdb_id, exc)

    merged: list[Stream] = []
    by_hash: dict[str, Stream] = {}
    for name, _ in active:                       # priority order, not completion
        for stream in results[name]:
            if not stream.info_hash:
                continue
            existing = by_hash.get(stream.info_hash)
            if existing is None:
                by_hash[stream.info_hash] = stream
                merged.append(stream)
            elif name not in existing.also_seen_in and name != existing.source:
                existing.also_seen_in = existing.also_seen_in + (name,)

    log.info("Candidates for %s: %s -> %d unique",
             imdb_id, {n: len(results[n]) for n, _ in active}, len(merged))
    return rank_streams(merged, prefer_season_pack=prefer_season_pack, override=override)
```

- [ ] **Step 4: Run the tests**

Run: `python -m pytest tests/test_scrapers.py -q && python -m pytest tests/ -q`
Expected: 11 scraper tests PASS, full suite 156 passed, 0 failed

- [ ] **Step 5: Commit**

```bash
git add scrapers.py tests/test_scrapers.py
git commit -m "feat: add scrapers.fetch_candidates orchestrator

Concurrent fetch, priority-ordered merge, dedup by hash with also_seen_in,
and per-scraper exception isolation."
```

---

### Task 9: Migrate the six call sites

**Files:**
- Modify: `processor.py:60-97`, `monitor.py:222-234`, `monitor.py:310-317`,
  `upgrader.py:51-70`, `cleanup.py:117-128`, `catbox.py:655-691`
- Test: `tests/test_scrapers.py`

**Interfaces:**
- Consumes: `scrapers.fetch_candidates` (Task 8).
- Produces: no new interfaces. `processor._fetch_movie_candidates` and
  `_fetch_season_candidates` keep their signatures.

This is the behaviour-changing task: `upgrader.py` and `cleanup.py` move from
short-circuit fallback to merge, and `monitor.py` gains health gating. Both are
deliberate and recorded in the spec.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_scrapers.py`:

```python
def test_every_call_site_uses_the_orchestrator():
    """No module may call a scraper's fetch directly any more; that is what
    produced three inconsistent orchestration patterns in the first place."""
    import pathlib
    import re
    root = pathlib.Path(__file__).resolve().parent.parent
    offenders = []
    allowed = {"scrapers.py", "zilean.py", "torrentio.py", "debridio.py", "catchup.py"}
    # \b would miss catbox's "_zilean.fetch_streams" alias, so match an
    # optional leading underscore-prefix instead.
    pattern = re.compile(r"\w*(?:zilean|torrentio|debridio)\.fetch(?:_streams)?\s*\(")
    for path in root.glob("*.py"):
        if path.name in allowed:
            continue
        for i, line in enumerate(path.read_text().splitlines(), 1):
            if pattern.search(line):
                offenders.append(f"{path.name}:{i}")
    assert offenders == [], f"direct scraper calls remain: {offenders}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_scrapers.py::test_every_call_site_uses_the_orchestrator -q`
Expected: FAIL listing `processor.py`, `monitor.py`, `upgrader.py`,
`cleanup.py`, `catbox.py` line numbers

- [ ] **Step 3: Migrate `processor.py`**

Replace the bodies of `_fetch_movie_candidates` and `_fetch_season_candidates`
(keeping the override construction, which the orchestrator does not do):

```python
def _fetch_movie_candidates(req: MediaRequest) -> list:
    override = dict(db.get_show_override(req.imdb_id) or {})
    override["runtime_minutes"] = _movie_runtime_minutes(req.imdb_id)
    return scrapers.fetch_candidates("movie", req.imdb_id, override=override)


def _fetch_season_candidates(req: MediaRequest, season: int, episode: int,
                             prefer_season_pack: bool = False) -> list:
    override = dict(db.get_show_override(req.imdb_id) or {})
    override["runtime_minutes"] = _episode_runtime_minutes(req.imdb_id, season, episode)
    return scrapers.fetch_candidates("series", req.imdb_id, season=season, episode=episode,
                                      prefer_season_pack=prefer_season_pack, override=override)
```

Add `import scrapers` and drop the now-unused `zilean` / `health_cache`
imports if nothing else uses them.

- [ ] **Step 4: Migrate `monitor.py`, `upgrader.py`, `cleanup.py`**

`monitor.py:222-234` becomes:

```python
    candidates = scrapers.fetch_candidates("series", imdb_id, season=season, episode=episode)
```

`monitor.py:310-317` becomes:

```python
        candidates = scrapers.fetch_candidates("series", imdb_id, season=season, episode=1,
                                                prefer_season_pack=True)
```

`upgrader.py` both helpers:

```python
def _fetch_movie_candidates(imdb_id: str) -> list:
    return scrapers.fetch_candidates("movie", imdb_id, override=_movie_runtime_override(imdb_id))


def _fetch_season_candidates(imdb_id: str, season: int) -> list:
    return scrapers.fetch_candidates("series", imdb_id, season=season, episode=1,
                                      prefer_season_pack=True,
                                      override=_episode_runtime_override(imdb_id, season))
```

`cleanup.py::_fetch_candidates` — note the series branch passes
`prefer_season_pack=True` today and must keep doing so:

```python
def _fetch_candidates(imdb_id: str, title: str, media_type: str) -> list:
    if media_type == "movie":
        return scrapers.fetch_candidates("movie", imdb_id)
    return scrapers.fetch_candidates("series", imdb_id, season=1, episode=1,
                                      prefer_season_pack=True)
```

Drop the now-unused `zilean` / `torrentio` imports from `cleanup.py` if nothing
else in the module uses them.

- [ ] **Step 5: Migrate `catbox.py`**

Replace the ThreadPoolExecutor block and the manual merge (lines 655-691) with:

```python
        import scrapers
        import debrid
        import blacklist
        media_type = item["media_type"]
        season = item.get("season")
        episode = item.get("episode")

        ranked = scrapers.fetch_candidates(
            "movie" if media_type == "movie" else "series",
            imdb_id, season=season, episode=episode,
        )
        if not ranked:
            return None
        ranked = blacklist.filter_candidates(ranked)
        log.info("Catbox search: %d candidate(s) after ranking/filter for %s",
                 len(ranked), item.get("title"))
        if not ranked:
            return None
```

The orchestrator already ranks, so the local `torrentio.rank_streams` call goes
away. **Keep `import debrid`** — `debrid.check_cached_multi(hashes)` is used a
few lines below and dropping it is a `NameError` at runtime. The now-unused
`import concurrent.futures`, `import torrentio` and `import zilean as _zilean`
in this function should go. Keep `blacklist.filter_candidates` and everything
after it.

- [ ] **Step 6: Run the tests**

Run: `python -m pytest tests/ -q`
Expected: 157 passed, 0 failed

- [ ] **Step 7: Commit**

```bash
git add processor.py monitor.py upgrader.py cleanup.py catbox.py tests/test_scrapers.py
git commit -m "refactor: route all candidate discovery through scrapers.py

Replaces six hand-rolled call sites in three inconsistent patterns.

Behaviour changes, both deliberate: upgrader and cleanup move from
short-circuit fallback (Zilean winning outright) to merge, and monitor
gains the health gating the other sites already had."
```

---

### Task 10: Record unique wins

**Files:**
- Modify: `processor.py` (the `if winner:` block that calls
  `db.record_metric("quality_added", ...)` — **locate it by content, not line
  number: Task 9 rewrites lines 60-97 above it and shifts everything down**),
  `metrics_prom.py` (after `source_wins_total`), `app.py`
  (`ui_api_metrics_summary`), `templates/ui.html` (the `source-bars` block)
- Test: `tests/test_scrapers.py`

**Interfaces:**
- Consumes: `Stream.also_seen_in` (Task 1), populated by Task 8.
- Produces: metric `source_unique_win`; Prometheus counter
  `mycelium_source_unique_wins_total{source}`; key `unique_sources` in the
  `/ui/api/metrics-summary` response.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_scrapers.py`:

```python
def test_unique_win_recorded_only_when_no_other_source_had_it(monkeypatch):
    import processor
    recorded = []
    monkeypatch.setattr(processor.db, "record_metric",
                        lambda metric, label=None, **kw: recorded.append((metric, label)))

    unique = _s("a" * 40, "debridio")
    processor._record_source_metrics(unique)
    assert ("source_win", "debridio") in recorded
    assert ("source_unique_win", "debridio") in recorded

    recorded.clear()
    shared = _s("b" * 40, "debridio")
    shared.also_seen_in = ("torrentio",)
    processor._record_source_metrics(shared)
    assert ("source_win", "debridio") in recorded
    assert ("source_unique_win", "debridio") not in recorded
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_scrapers.py -k unique_win -q`
Expected: FAIL with `AttributeError: module 'processor' has no attribute '_record_source_metrics'`

- [ ] **Step 3: Extract and extend the metric recording in `processor.py`**

Add the helper and call it from the `if winner:` block at line 696, replacing
the inline `record_metric`/`metrics_prom` calls:

```python
def _record_source_metrics(winner) -> None:
    """Record which source won, and whether it was the only one that had it.

    Win rate alone is misleading: dedup is won by merge order, and Debridio is
    both first and a ~79% superset of Torrentio, so it absorbs wins Torrentio
    would previously have recorded. source_unique_win is the honest signal.
    """
    db.record_metric("source_win", winner.source, value_int=1)
    is_unique = not getattr(winner, "also_seen_in", ())
    if is_unique:
        db.record_metric("source_unique_win", winner.source, value_int=1)
    try:
        import metrics_prom
        metrics_prom.source_wins_total.labels(source=winner.source).inc()
        if is_unique:
            metrics_prom.source_unique_wins_total.labels(source=winner.source).inc()
    except Exception as exc:
        log.debug("metrics_prom (source) failed: %s", exc)
```

The `if winner:` block becomes:

```python
        if winner:
            db.record_metric("quality_added", winner.quality, value_int=1)
            _record_source_metrics(winner)
            try:
                import metrics_prom
                metrics_prom.quality_added_total.labels(quality=winner.quality or "unknown").inc()
            except Exception as exc:
                log.debug("metrics_prom (quality) failed: %s", exc)
```

- [ ] **Step 4: Add the Prometheus counter to `metrics_prom.py`**

After `source_wins_total`:

```python
source_unique_wins_total = Counter(
    "mycelium_source_unique_wins_total",
    "Source provider that won with a release no other source returned",
    ["source"],
)
```

- [ ] **Step 5: Expose it and render it**

In `app.py::ui_api_metrics_summary`, add:

```python
        unique_sources=db.get_metric_summary("source_unique_win", days=30),
```

In `templates/ui.html`, in the source-bars block, index the unique counts and
append them to the label:

```javascript
      const uniq = {};
      (d.unique_sources || []).forEach(u => { uniq[u.label] = u.count; });
      sourceEl.innerHTML = sources.map(s => {
        const pct = (100 * s.count / max).toFixed(0);
        const u = uniq[s.label] || 0;
        return `<div class="quality-bar-row">
          <div class="quality-label">${s.label || '?'}</div>
          <div class="quality-bar-bg"><div class="quality-bar-fill" style="width:${pct}%"></div></div>
          <div class="quality-count">${s.count} <span class="dim">(${u} uniq)</span></div></div>`;
      }).join('');
```

- [ ] **Step 6: Run the tests**

Run: `python -m pytest tests/ -q`
Expected: 158 passed, 0 failed

- [ ] **Step 7: Commit**

```bash
git add processor.py metrics_prom.py app.py templates/ui.html tests/test_scrapers.py
git commit -m "feat: record source_unique_win alongside source_win

Win rate is decided by merge order, so Debridio being first and a ~79%
superset of Torrentio would show as dominance regardless of quality.
Unique wins are the number that says whether a source is earning its
place."
```

---

## Manual verification

After Task 10, before merging:

1. Set `DEBRIDIO_API_KEY` in Admin > Settings > Connections and enable
   `DEBRIDIO_ENABLED`. Confirm both secret fields render masked.
2. Request one movie and one TV title. Both should succeed, and the logs should
   show `Candidates for tt…: {'debridio': N, 'zilean': N, 'torrentio': N}`.
3. `grep` the logs for the Debridio API key and the TorBox key. Neither may
   appear. This is the check that matters most.
4. Disable `DEBRIDIO_ENABLED` and request another title. It must still succeed
   from Zilean/Torrentio — that is the whole degradation story.
5. Set a deliberately wrong `DEBRIDIO_API_KEY`. Requests must still succeed,
   and Admin > Overview should show Debridio down.
6. After a few requests, check Admin > Overview > Source Win Rate for a
   Debridio row with a `(N uniq)` count.
