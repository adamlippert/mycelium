# Release Swap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an admin see the candidate releases the processor saw for a movie or a single episode and switch the title to one of them from the Library drawer, with the next play using the new release and nothing on disk changing.

**Architecture:** A new backend module `release_swap.py` with `candidates()` (live scrape through `scrapers.merge_candidates`, explained ranking for per-candidate verdicts, blacklist filtering, one TorBox cache check) and `swap()` (the catbox auto-upgrade sequence: update the virtual item behind its token, invalidate caches, reset playability, update the request row's release fields, log activity, optional blacklist of the old hash), behind two admin routes. On the frontend a `ReleasesPanel` component with a confirm strip, opened from the Release card (movies) and from each present episode row (episodes).

**Tech Stack:** Python 3.12 / Flask / SQLite, pytest; React 18 + TypeScript + Vite + Tailwind, `@tanstack/react-query`, vitest + Testing Library. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-08-release-swap-design.md`

## Global Constraints

- Never use em-dashes or `--` in code, comments, copy or docs (a hyphen inside a Tailwind class is fine).
- The repo is public: no passwords, tokens or IP addresses.
- Branch `main`. Commit trailer `Claude-Session: https://claude.ai/code/session_017Cc8iouqJoYhUcnJhhgapA`. No `Co-Authored-By`.
- Tests never import `app.py`; routes are checked on source text via a `_src()` helper. Every DB-touching test file carries its own `_isolated_db` autouse fixture (copy the block from `tests/test_library_actions.py` lines 1 to 40). No `tests/conftest.py`. No test reaches the network: fake `scrapers.merge_candidates` and `debrid.check_cached_multi` with `monkeypatch`.
- Mutation-check each new load-bearing test. Backend: `PYTHONDONTWRITEBYTECODE=1 .venv-sdd/bin/python -m pytest tests/ -q -p no:cacheprovider` (933 passed at HEAD a95fb69). Frontend: `cd frontend && npx tsc --noEmit && npx vitest run` (240 passed). `npm run build` output in `static/app/` is committed with any frontend change.
- Admin guard shape: `if not auth.is_admin(): return jsonify(error="admin required"), 403`. Drawer action routes return JSON `{ok, message}` with HTTP 200 for refusals; the candidates route returns `{error}` with HTTP 502 on scraper failure.
- Clarification against the spec: the `.nfo` stream-detail rewrite is left to the play-time probe (it needs real track info the swap does not have); the swap does not touch the nfo.
- Existing facts: `streams.Stream` fields `name, title, info_hash, quality, seeders, size_gb, is_season_pack, languages (tuple), source (the scraper name), cached, also_seen_in (tuple)`, property `magnet`. `scrapers.merge_candidates(media_type, imdb_id, season=None, episode=None, *, raise_if_inconclusive=False, timeout=None) -> list[Stream]` (unranked; `raise_if_inconclusive=True` raises `scrapers.ScrapersUnavailable`). `streams.rank_streams_explained(streams, prefer_season_pack=False, override=None) -> (kept: list[Stream], verdicts: list[filter_rules.Verdict])` where verdicts align with the input list and `Verdict` has `kept, rule, value, relaxed`. `blacklist.filter_candidates(list) -> list`. `debrid.check_cached_multi(hashes) -> {provider: set}` (may raise `torbox.RateLimited`). `release_tags.detect_sources(text) -> tuple[str, ...]`. `db.get_virtual_items_by_imdb(imdb_id, media_type=None)`, `db.get_virtual_item_by_episode(imdb_id, season, episode)`, `db.update_virtual_item_upgrade(token, info_hash, magnet, quality, source)` (clears torbox_id and file_id), `db.reset_playability_state(content_key)`, `catbox._content_key(item) -> str | None`, `catbox.invalidate_url_cache(token)`, `mp4_faststart._cache_path(token) -> Path` (asserts if `init()` was not called), `db.get_request_by_imdb`, `db.get_request(row_id)`, `db.blacklist_hash(info_hash, note)`, `db.log_activity(event, title, message, success, imdb_id=None)`, `db.get_show_override(imdb_id)`. Frontend: `library/cards/DrawerCard.tsx` exports `DrawerCard, Row, ActionButton({label, run, onDone, variant?, confirm?}), Copy`; `library/actions.ts` exports `ACTIONS` and a private `path(imdb, tail)`; `api.libraryAction(path, method?, body?) -> {ok, message}`; primitives `Button` (`variant: 'default'|'primary'|'ghost'`, `loading`).

## File structure

| File | Responsibility |
|---|---|
| `release_swap.py` (new) | `candidates(imdb_id, media_type, season=None, episode=None) -> dict`, `swap(item, candidate, blacklist_old) -> dict`, `find_item(imdb_id, season, episode)`, `candidate_by_hash(...)` |
| `db.py` | `set_request_release(row_id, quality, source, info_hash)` |
| `app.py` | `GET /ui/api/library/<imdb_id>/candidates`, `POST /ui/api/library/<imdb_id>/swap` |
| `frontend/src/api.ts` | `Candidate`, `CandidatesResponse`, `api.libraryCandidates`, `api.librarySwap` |
| `frontend/src/pages/admin/library/ReleasesPanel.tsx` | the panel with rows and the confirm strip |
| `frontend/src/pages/admin/library/cards/ReleaseCard.tsx`, `cards/EpisodesCard.tsx` | the entry buttons |
| `README.md`, `CHANGELOG.md` | docs |

---

### Task 1: `release_swap.candidates` and the candidates route

**Files:**
- Create: `release_swap.py`
- Modify: `app.py` (route after `ui_api_library_activity`)
- Test: `tests/test_release_swap.py` (new)

**Interfaces:**
- Produces: `release_swap.candidates(imdb_id, media_type, season=None, episode=None) -> dict` returning `{"current": {"info_hash", "quality", "source"} | None, "candidates": [ {info_hash, name, quality, source, size_gb, seeders, languages (list), cached, scrapers (list), kept, rule, value, current} ]}`; raises `release_swap.CandidatesUnavailable(message)` when the scrapers cannot answer. `release_swap.find_item(imdb_id, season=None, episode=None) -> dict | None`. Route `GET /ui/api/library/<imdb_id>/candidates?season=&episode=`.

- [ ] **Step 1: Failing tests**

Create `tests/test_release_swap.py`:

```python
"""release_swap: the candidate list behind "Pick another release" and the
swap that puts a different hash behind an existing token."""
import os
import sys

os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import db
import release_swap as rs
from streams import Stream

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


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    _drop_cached_conn()
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    _drop_cached_conn()
    db.init()
    yield
    _drop_cached_conn()


def _stream(name, h, quality="1080p", seeders=10, size=4.0, langs=("en",), src="torrentio", pack=False):
    return Stream(name=name, title=name, info_hash=h, quality=quality, seeders=seeders, size_gb=size,
                  is_season_pack=pack, languages=langs, source=src)


H1, H2, H3, H4 = "a" * 40, "b" * 40, "c" * 40, "d" * 40


def _item(imdb, token, info_hash, season=None, episode=None, quality="1080p"):
    with db._connect() as conn:
        conn.execute(
            "INSERT INTO virtual_items (token, info_hash, magnet, title, media_type, strm_path, imdb_id, season, episode, quality) "
            "VALUES (?, ?, ?, 'Heat', ?, ?, ?, ?, ?, ?)",
            (token, info_hash, f"magnet:?xt=urn:btih:{info_hash}", "movie" if season is None else "series",
             f"/media/{token}.strm", imdb, season, episode, quality))
        conn.commit()


@pytest.fixture
def scrapers_fake(monkeypatch):
    """Four candidates: a good WEB-DL (cached), a cam that the rules drop,
    a REMUX (uncached), and the current release."""
    streams = [
        _stream("Heat.1995.1080p.WEB-DL.x264", H1),
        _stream("Heat.1995.CAM.x264", H2, quality="720p"),
        _stream("Heat.1995.2160p.REMUX", H3, quality="2160p", size=60.0, src="zilean"),
        _stream("Heat.1995.1080p.BluRay.x264", H4),
    ]
    import scrapers
    import streams as streams_mod
    import debrid
    import filter_rules
    monkeypatch.setattr(scrapers, "merge_candidates", lambda *a, **k: list(streams))

    def fake_rank(items, prefer_season_pack=False, override=None):
        verdicts = [filter_rules.Verdict(kept=s.info_hash != H2, rule=None if s.info_hash != H2 else "SOURCE_EXCLUDED",
                                         value=None if s.info_hash != H2 else "cam") for s in items]
        kept = [s for s, v in zip(items, verdicts) if v.kept]
        kept.sort(key=lambda s: s.info_hash != H1)   # H1 first, as the processor would rank it
        return kept, verdicts
    monkeypatch.setattr(streams_mod, "rank_streams_explained", fake_rank)
    monkeypatch.setattr(debrid, "check_cached_multi", lambda hashes: {"torbox": {H1, H4}})
    return streams


def test_candidates_are_kept_first_then_dropped_with_badges(scrapers_fake):
    db.insert_request("Heat", "tt1", "movie")
    _item("tt1", "tok", H4)
    out = rs.candidates("tt1", "movie")
    assert out["current"] == {"info_hash": H4, "quality": "1080p", "source": None}
    rows = out["candidates"]
    assert [r["info_hash"] for r in rows] == [H1, H4, H3, H2], "kept in rank order, dropped last"
    by = {r["info_hash"]: r for r in rows}
    assert by[H1]["cached"] is True and by[H3]["cached"] is False
    assert by[H4]["current"] is True and by[H1]["current"] is False
    assert by[H2]["kept"] is False and by[H2]["rule"] == "SOURCE_EXCLUDED" and by[H2]["value"] == "cam"
    assert by[H1]["kept"] is True and by[H1]["rule"] is None
    assert by[H1]["source"] == "WEB-DL" and by[H3]["scrapers"] == ["zilean"]
    assert by[H1]["languages"] == ["en"] and by[H3]["size_gb"] == 60.0
    assert set(rows[0]) == {"info_hash", "name", "quality", "source", "size_gb", "seeders", "languages",
                            "cached", "scrapers", "kept", "rule", "value", "current"}


def test_blacklisted_hashes_are_excluded(scrapers_fake):
    db.insert_request("Heat", "tt1", "movie")
    db.blacklist_hash(H3, "bad")
    rows = rs.candidates("tt1", "movie")["candidates"]
    assert H3 not in [r["info_hash"] for r in rows]


def test_episode_candidates_pass_season_and_episode(monkeypatch, scrapers_fake):
    import scrapers
    seen = {}
    monkeypatch.setattr(scrapers, "merge_candidates",
                        lambda mt, imdb, season=None, episode=None, **k: seen.update(mt=mt, s=season, e=episode) or list(scrapers_fake))
    db.insert_request("Loki", "tt4", "series")
    _item("tt4", "e3", H4, season=2, episode=3)
    out = rs.candidates("tt4", "series", season=2, episode=3)
    assert seen == {"mt": "series", "s": 2, "e": 3}
    assert out["current"]["info_hash"] == H4


def test_scraper_failure_raises_and_cache_failure_degrades(monkeypatch, scrapers_fake):
    import scrapers
    import debrid
    db.insert_request("Heat", "tt1", "movie")

    def boom(*a, **k):
        raise scrapers.ScrapersUnavailable("torrentio down")
    monkeypatch.setattr(scrapers, "merge_candidates", boom)
    with pytest.raises(rs.CandidatesUnavailable):
        rs.candidates("tt1", "movie")
    monkeypatch.setattr(scrapers, "merge_candidates", lambda *a, **k: list(scrapers_fake))

    def cache_boom(hashes):
        raise RuntimeError("429")
    monkeypatch.setattr(debrid, "check_cached_multi", cache_boom)
    rows = rs.candidates("tt1", "movie")["candidates"]
    assert rows and all(r["cached"] is False for r in rows), "a failed cache check means no badges, not no list"


def test_find_item_movie_and_episode():
    _item("tt1", "tok", H4)
    _item("tt4", "e3", H1, season=2, episode=3)
    assert rs.find_item("tt1")["token"] == "tok"
    assert rs.find_item("tt4", 2, 3)["token"] == "e3"
    assert rs.find_item("tt4", 2, 4) is None and rs.find_item("tt9") is None


def test_candidates_route_exists_and_is_admin_only():
    src = _src("app.py")
    route = '@app.get("/ui/api/library/<imdb_id>/candidates")'
    assert route in src
    body = src.split(route, 1)[1].split("\n\n\n", 1)[0]
    assert "auth.is_admin()" in body and "release_swap" in body and "502" in body
```

Check `scrapers.ScrapersUnavailable` exists (grep); if the class lives elsewhere, import it from there in both test and module.

- [ ] **Step 2: Run to verify failure**

`PYTHONDONTWRITEBYTECODE=1 .venv-sdd/bin/python -m pytest tests/test_release_swap.py -q -p no:cacheprovider` fails with `ModuleNotFoundError: No module named 'release_swap'`.

- [ ] **Step 3: `release_swap.py`**

```python
"""Pick another release for a movie or one episode.

candidates() is the list the processor saw, with each candidate's rule
verdict and TorBox cache state; swap() puts a different hash behind the
item's existing token, the same move the catbox auto-upgrade makes, so
nothing on disk changes and the next play uses the new release.
"""
from __future__ import annotations

import logging
import re

import db

log = logging.getLogger(__name__)
_HASH = re.compile(r"^[0-9a-fA-F]{40}$")


class CandidatesUnavailable(Exception):
    """The scrapers could not answer; the caller can offer Retry."""


def find_item(imdb_id: str, season: int | None = None, episode: int | None = None) -> dict | None:
    if season is not None and episode is not None:
        return db.get_virtual_item_by_episode(imdb_id, season, episode)
    items = db.get_virtual_items_by_imdb(imdb_id, media_type="movie")
    return items[0] if items else None


def _release_source(name: str) -> str | None:
    import release_tags
    found = release_tags.detect_sources(name or "")
    return found[0] if found else None


def _row(s, verdict, cached: set[str], current_hash: str) -> dict:
    return {
        "info_hash": s.info_hash.lower(), "name": s.name, "quality": s.quality,
        "source": _release_source(s.name), "size_gb": s.size_gb, "seeders": s.seeders,
        "languages": list(s.languages), "cached": s.info_hash.lower() in cached,
        "scrapers": [s.source, *s.also_seen_in], "kept": verdict.kept,
        "rule": None if verdict.kept else verdict.rule, "value": None if verdict.kept else verdict.value,
        "current": s.info_hash.lower() == current_hash,
    }


def candidates(imdb_id: str, media_type: str, season: int | None = None, episode: int | None = None) -> dict:
    import blacklist
    import debrid
    import scrapers
    import streams
    try:
        found = scrapers.merge_candidates(media_type, imdb_id, season, episode, raise_if_inconclusive=True)
    except Exception as exc:
        raise CandidatesUnavailable(str(exc) or exc.__class__.__name__) from exc
    found = blacklist.filter_candidates(found)
    kept, verdicts = streams.rank_streams_explained(found, override=db.get_show_override(imdb_id) or None)
    verdict_of = {s.info_hash.lower(): v for s, v in zip(found, verdicts)}
    try:
        cached = {h.lower() for h in debrid.check_cached_multi([s.info_hash for s in found]).get("torbox", set())}
    except Exception as exc:
        log.warning("Cache check failed for %s candidates: %s", imdb_id, exc)
        cached = set()
    item = find_item(imdb_id, season, episode)
    current_hash = (item or {}).get("info_hash", "").lower() if item else ""
    current = None
    if item:
        current = {"info_hash": current_hash, "quality": item.get("quality"), "source": item.get("source")}
    kept_hashes = {s.info_hash.lower() for s in kept}
    dropped = [s for s in found if s.info_hash.lower() not in kept_hashes]
    rows = [_row(s, verdict_of[s.info_hash.lower()], cached, current_hash) for s in kept + dropped]
    return {"current": current, "candidates": rows}
```

Check how `rank_streams_explained` expects `override` (the processor passes `db.get_show_override(...)` as a dict or None; match it) and whether `virtual_items` has a `source` column (if not, drop `source` from `current` and from the test's expected dict, and say so in the report).

- [ ] **Step 4: Route** (after `ui_api_library_activity`)

```python
@app.get("/ui/api/library/<imdb_id>/candidates")
def ui_api_library_candidates(imdb_id: str):
    """The candidate releases for a movie or one episode; a live scrape."""
    if not auth.is_admin():
        return jsonify(error="admin required"), 403
    import release_swap
    req = db.get_request_by_imdb(imdb_id)
    if not req:
        return jsonify(error="not found"), 404
    season = request.args.get("season", type=int)
    episode = request.args.get("episode", type=int)
    try:
        return jsonify(release_swap.candidates(imdb_id, req["media_type"], season, episode))
    except release_swap.CandidatesUnavailable as exc:
        return jsonify(error=f"scrapers unavailable: {exc}"), 502
```

- [ ] **Step 5: Run, mutation-check, commit**

Mutation: make `candidates()` return kept and dropped in scraper order (drop the `kept + dropped` ordering): the first test must fail. Restore. Delete `__pycache__`.

```bash
git add release_swap.py app.py tests/test_release_swap.py
git commit -m "feat(library): candidate releases for a movie or episode

Claude-Session: https://claude.ai/code/session_017Cc8iouqJoYhUcnJhhgapA"
```

---

### Task 2: `release_swap.swap`, the swap route, the request-release helper

**Files:**
- Modify: `release_swap.py`, `db.py` (after `set_request_status`), `app.py` (route after the candidates route)
- Test: `tests/test_release_swap.py` (append)

**Interfaces:**
- Produces: `db.set_request_release(row_id, quality, source, info_hash)` touching only those three columns and `updated_at`; `release_swap.swap(item, candidate, blacklist_old=False) -> {ok, message}`; `release_swap.swap_by_hash(imdb_id, info_hash, season=None, episode=None, blacklist_old=False) -> {ok, message}` (validation, candidate lookup through `candidates()`, then `swap`); route `POST /ui/api/library/<imdb_id>/swap` with JSON `{info_hash, season?, episode?, blacklist_old?}`.

- [ ] **Step 1: Failing tests** (append)

```python
def _candidate(h, quality="2160p", source="REMUX", name="Heat.1995.2160p.REMUX"):
    return {"info_hash": h, "name": name, "quality": quality, "source": source, "size_gb": 60.0, "seeders": 5,
            "languages": ["en"], "cached": False, "scrapers": ["zilean"], "kept": True, "rule": None, "value": None, "current": False}


def test_swap_movie_replaces_the_release_behind_the_token(monkeypatch):
    import catbox
    rid = db.insert_request("Heat", "tt1", "movie")
    db.update_request(rid, "success", quality="1080p", source="WEB-DL", info_hash=H4)
    _item("tt1", "tok", H4)
    db.update_virtual_torbox_id("tok", 77)
    db.update_playability_fail("tt1", "cdn 404")
    invalidated = []
    monkeypatch.setattr(catbox, "invalidate_url_cache", lambda token=None: invalidated.append(token))
    out = rs.swap(rs.find_item("tt1"), _candidate(H3), blacklist_old=True)
    assert out["ok"] is True and "2160p" in out["message"]
    item = db.get_virtual_item("tok")
    assert item["info_hash"] == H3 and item["magnet"].endswith(H3) and item["quality"] == "2160p"
    assert item["torbox_id"] is None and item["file_id"] is None
    assert invalidated == ["tok"]
    assert db.get_playability_state("tt1")["status"] == "unknown"
    row = db.get_request(rid)
    assert row["status"] == "success" and row["info_hash"] == H3 and row["quality"] == "2160p" and row["source"] == "REMUX"
    assert H4 in db.get_blacklisted_hashes()
    act = db.get_activity_for_title("tt1", "Heat")[0]
    assert act["event"] == "swapped" and "1080p" in act["message"] and "2160p" in act["message"]


def test_swap_episode_leaves_the_request_row_alone(monkeypatch):
    import catbox
    monkeypatch.setattr(catbox, "invalidate_url_cache", lambda token=None: None)
    rid = db.insert_request("Loki", "tt4", "series")
    db.update_request(rid, "success", quality="1080p", source="WEB-DL", info_hash=H1)
    _item("tt4", "e3", H4, season=2, episode=3)
    db.update_playability_fail("tt4:S02E03", "timeout")
    out = rs.swap(rs.find_item("tt4", 2, 3), _candidate(H3))
    assert out["ok"] is True
    assert db.get_virtual_item("e3")["info_hash"] == H3
    assert db.get_playability_state("tt4:S02E03")["status"] == "unknown"
    row = db.get_request(rid)
    assert row["info_hash"] == H1 and row["quality"] == "1080p", "the series row keeps its own release"
    assert H4 not in db.get_blacklisted_hashes()


def test_swap_by_hash_validates(monkeypatch, scrapers_fake):
    import catbox
    monkeypatch.setattr(catbox, "invalidate_url_cache", lambda token=None: None)
    db.insert_request("Heat", "tt1", "movie")
    _item("tt1", "tok", H4)
    assert rs.swap_by_hash("tt1", "short") == {"ok": False, "message": "not a valid info hash"}
    assert rs.swap_by_hash("tt9", H1)["message"] == "unknown title"
    assert rs.swap_by_hash("tt1", H4)["message"] == "that is already the current release"
    assert rs.swap_by_hash("tt1", "e" * 40)["message"] == "that hash is not in the candidate list"
    assert rs.swap_by_hash("tt1", H1, season=1, episode=1)["message"] == "no file for that episode"
    out = rs.swap_by_hash("tt1", H1)
    assert out["ok"] is True and db.get_virtual_item("tok")["info_hash"] == H1


def test_set_request_release_keeps_status_and_error():
    rid = db.insert_request("Heat", "tt1", "movie")
    db.update_request(rid, "failed", error="old error")
    db.set_request_release(rid, "2160p", "REMUX", H3)
    row = db.get_request(rid)
    assert row["status"] == "failed" and row["error"] == "old error" and row["info_hash"] == H3


def test_swap_route_exists_and_delegates():
    src = _src("app.py")
    route = '@app.post("/ui/api/library/<imdb_id>/swap")'
    assert route in src
    body = src.split(route, 1)[1].split("\n\n\n", 1)[0]
    assert "auth.is_admin()" in body and "release_swap.swap_by_hash(" in body and "blacklist_old" in body
```

Check `db.update_virtual_torbox_id`, `db.update_playability_fail`, `db.get_playability_state`, `db.get_virtual_item`, `db.get_request` exist (all listed in earlier plans); adapt names if not.

- [ ] **Step 2: Run, verify failure** (`AttributeError: swap`).

- [ ] **Step 3: `db.set_request_release`** (after `set_request_status`)

```python
def set_request_release(row_id: int, quality: str | None, source: str | None, info_hash: str | None) -> None:
    """Replace a request's release fields only; status and error stay."""
    with _connect() as conn:
        conn.execute(
            """UPDATE requests SET quality=?, source=?, info_hash=?,
               updated_at=strftime('%Y-%m-%d %H:%M:%S','now') WHERE id=?""",
            (quality, source, info_hash, row_id))
        conn.commit()
```

- [ ] **Step 4: `swap` and `swap_by_hash`** (append to `release_swap.py`)

```python
def _drop_faststart_cache(token: str) -> None:
    try:
        import mp4_faststart
        path = mp4_faststart._cache_path(token)
        if path.exists():
            path.unlink()
    except Exception as exc:
        log.debug("No fast-start cache to drop for %s: %s", token, exc)


def swap(item: dict, candidate: dict, blacklist_old: bool = False) -> dict:
    """Put candidate's hash behind item's token. Nothing on disk changes."""
    import catbox
    old_hash = (item.get("info_hash") or "").lower()
    old_quality = item.get("quality") or "?"
    new_hash = candidate["info_hash"].lower()
    magnet = f"magnet:?xt=urn:btih:{new_hash}"
    db.update_virtual_item_upgrade(item["token"], new_hash, magnet, candidate.get("quality"), candidate.get("source"))
    catbox.invalidate_url_cache(item["token"])
    _drop_faststart_cache(item["token"])
    key = catbox._content_key(item)
    if key:
        db.reset_playability_state(key)
    if item.get("season") is None and item.get("imdb_id"):
        req = db.get_request_by_imdb(item["imdb_id"])
        if req:
            db.set_request_release(req["id"], candidate.get("quality"), candidate.get("source"), new_hash)
    title = item.get("title") or item.get("imdb_id") or "?"
    label = " ".join(x for x in (candidate.get("quality"), candidate.get("source")) if x) or new_hash[:8]
    db.log_activity("swapped", title, f"{old_quality} to {candidate.get('quality') or '?'} ({candidate.get('name') or new_hash[:8]})",
                    True, imdb_id=item.get("imdb_id"))
    if blacklist_old and old_hash:
        db.blacklist_hash(old_hash, "replaced by admin")
    return {"ok": True, "message": f"next play uses {label}"}


def swap_by_hash(imdb_id: str, info_hash: str, season: int | None = None, episode: int | None = None,
                 blacklist_old: bool = False) -> dict:
    if not _HASH.match(info_hash or ""):
        return {"ok": False, "message": "not a valid info hash"}
    req = db.get_request_by_imdb(imdb_id)
    if not req:
        return {"ok": False, "message": "unknown title"}
    item = find_item(imdb_id, season, episode)
    if not item:
        return {"ok": False, "message": "no file for that episode" if season is not None else "no file for this title"}
    if (item.get("info_hash") or "").lower() == info_hash.lower():
        return {"ok": False, "message": "that is already the current release"}
    try:
        listing = candidates(imdb_id, req["media_type"], season, episode)
    except CandidatesUnavailable as exc:
        return {"ok": False, "message": f"scrapers unavailable: {exc}"}
    match = next((c for c in listing["candidates"] if c["info_hash"] == info_hash.lower()), None)
    if not match:
        return {"ok": False, "message": "that hash is not in the candidate list"}
    return swap(item, match, blacklist_old)
```

Note `reset_playability_state(content_key)` may be a no-op when no row exists; the test seeds a row first. `catbox._content_key` needs `season` and `episode` keys on the item dict; `get_virtual_item_by_episode` returns the full row, so they are present. Check `db.update_virtual_item_upgrade` signature matches (`token, info_hash, magnet, quality, source`).

- [ ] **Step 5: Route** (after the candidates route)

```python
@app.post("/ui/api/library/<imdb_id>/swap")
def ui_api_library_swap(imdb_id: str):
    if not auth.is_admin():
        return jsonify(error="admin required"), 403
    import release_swap
    p = request.get_json(silent=True) or {}
    return jsonify(**release_swap.swap_by_hash(
        imdb_id, str(p.get("info_hash") or ""), p.get("season"), p.get("episode"),
        blacklist_old=bool(p.get("blacklist_old"))))
```

- [ ] **Step 6: Run, mutation-check, commit**

Mutation: remove the `torbox_id=NULL` effect by calling `db.update_virtual_item_upgrade` with a monkeypatch? Simpler: make `swap` skip `reset_playability_state`: the movie test must fail on the playability assertion. Restore.

```bash
git add release_swap.py db.py app.py tests/test_release_swap.py
git commit -m "feat(library): swap a title's release behind its token

Claude-Session: https://claude.ai/code/session_017Cc8iouqJoYhUcnJhhgapA"
```

---

### Task 3: Releases panel and the Release card button

**Files:**
- Modify: `frontend/src/api.ts`, `frontend/src/pages/admin/library/cards/ReleaseCard.tsx`
- Create: `frontend/src/pages/admin/library/ReleasesPanel.tsx`, `ReleasesPanel.test.tsx`
- Test: `frontend/src/pages/admin/library/cards.test.tsx` (append one case for the button)

**Interfaces:**
- `api.ts`: `Candidate { info_hash, name, quality: string | null, source: string | null, size_gb, seeders, languages: string[], cached, scrapers: string[], kept, rule: string | null, value: string | null, current }`, `CandidatesResponse { current: { info_hash, quality, source } | null; candidates: Candidate[] }`, `api.libraryCandidates(imdb, season?, episode?)`, `api.librarySwap(imdb, body: { info_hash: string; season?: number; episode?: number; blacklist_old: boolean })`.
- `ReleasesPanel({ imdb, season?, episode?, onDone, onClose })`.
- `ReleaseCard({ d, onDone })` gains "Pick another release" (movies with at least one item) toggling the panel below the card.

- [ ] **Step 1: `api.ts`**

```ts
export interface Candidate {
  info_hash: string; name: string; quality: string | null; source: string | null; size_gb: number; seeders: number;
  languages: string[]; cached: boolean; scrapers: string[]; kept: boolean; rule: string | null; value: string | null; current: boolean;
}
export interface CandidatesResponse { current: { info_hash: string; quality: string | null; source: string | null } | null; candidates: Candidate[] }
```

in `api`:

```ts
  libraryCandidates: (imdb: string, season?: number, episode?: number) => {
    const qs = season != null && episode != null ? `?season=${season}&episode=${episode}` : '';
    return http<CandidatesResponse>(`/ui/api/library/${imdb}/candidates${qs}`);
  },
  librarySwap: (imdb: string, body: { info_hash: string; season?: number; episode?: number; blacklist_old: boolean }) =>
    http<{ ok: boolean; message: string }>(`/ui/api/library/${imdb}/swap`, { method: 'POST', body: JSON.stringify(body) }),
```

- [ ] **Step 2: Failing `ReleasesPanel.test.tsx`**

```tsx
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import type { Candidate } from '../../../api';
import { ReleasesPanel } from './ReleasesPanel';

const apiMocks = vi.hoisted(() => ({ libraryCandidates: vi.fn(), librarySwap: vi.fn() }));
vi.mock('../../../api', async () => {
  const actual = await vi.importActual<typeof import('../../../api')>('../../../api');
  return { ...actual, api: { ...actual.api, ...apiMocks } };
});

const cand = (over: Partial<Candidate>): Candidate => ({
  info_hash: 'a'.repeat(40), name: 'Heat.1995.1080p.WEB-DL.x264', quality: '1080p', source: 'WEB-DL', size_gb: 4.2, seeders: 120,
  languages: ['en'], cached: true, scrapers: ['torrentio'], kept: true, rule: null, value: null, current: false, ...over,
});

function renderIt(props: Partial<React.ComponentProps<typeof ReleasesPanel>> = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const onDone = vi.fn(); const onClose = vi.fn();
  render(<QueryClientProvider client={qc}><ReleasesPanel imdb="tt1" onDone={onDone} onClose={onClose} {...props} /></QueryClientProvider>);
  return { onDone, onClose };
}

describe('ReleasesPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMocks.libraryCandidates.mockResolvedValue({ current: { info_hash: 'd'.repeat(40), quality: '1080p', source: 'BluRay' }, candidates: [
      cand({}),
      cand({ info_hash: 'd'.repeat(40), name: 'Heat.1995.1080p.BluRay.x264', source: 'BluRay', current: true }),
      cand({ info_hash: 'c'.repeat(40), name: 'Heat.1995.2160p.REMUX', quality: '2160p', source: 'REMUX', size_gb: 60, cached: false, scrapers: ['zilean'] }),
      cand({ info_hash: 'b'.repeat(40), name: 'Heat.1995.CAM.x264', quality: '720p', source: 'CAM', kept: false, rule: 'SOURCE_EXCLUDED', value: 'cam' }),
    ] });
  });

  it('shows the loading line, then rows with badges and the dropped reason, current row without Use', async () => {
    renderIt();
    expect(screen.getByText('Asking the scrapers...')).toBeInTheDocument();
    const rows = await screen.findAllByRole('listitem');
    expect(rows).toHaveLength(4);
    expect(within(rows[0]).getByText('cached')).toBeInTheDocument();
    expect(within(rows[1]).getByText('current')).toBeInTheDocument();
    expect(within(rows[1]).queryByRole('button', { name: 'Use' })).not.toBeInTheDocument();
    expect(within(rows[2]).queryByText('cached')).not.toBeInTheDocument();
    expect(within(rows[3]).getByText('dropped: SOURCE_EXCLUDED = cam')).toBeInTheDocument();
    expect(within(rows[0]).getByText('4.2 GB')).toBeInTheDocument();
    expect(apiMocks.libraryCandidates).toHaveBeenCalledWith('tt1', undefined, undefined);
  });

  it('Use opens the confirm strip, warns for an uncached one, and Confirm posts the swap', async () => {
    apiMocks.librarySwap.mockResolvedValue({ ok: true, message: 'next play uses 2160p REMUX' });
    const { onDone, onClose } = renderIt();
    const rows = await screen.findAllByRole('listitem');
    await userEvent.click(within(rows[0]).getByRole('button', { name: 'Use' }));
    expect(screen.getByText(/Switch to this release\?/)).toBeInTheDocument();
    expect(screen.queryByText(/TorBox does not have this yet/)).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(screen.queryByText(/Switch to this release\?/)).not.toBeInTheDocument();
    await userEvent.click(within(rows[2]).getByRole('button', { name: 'Use' }));
    expect(screen.getByText(/TorBox does not have this yet/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('checkbox', { name: 'Blacklist the current release' }));
    await userEvent.click(screen.getByRole('button', { name: 'Confirm' }));
    await waitFor(() => expect(apiMocks.librarySwap).toHaveBeenCalledWith('tt1', { info_hash: 'c'.repeat(40), blacklist_old: true }));
    expect(await screen.findByText('next play uses 2160p REMUX')).toBeInTheDocument();
    await waitFor(() => expect(onDone).toHaveBeenCalled());
    expect(onClose).toHaveBeenCalled();
  });

  it('passes season and episode through', async () => {
    apiMocks.librarySwap.mockResolvedValue({ ok: true, message: 'ok' });
    renderIt({ season: 2, episode: 3 });
    const rows = await screen.findAllByRole('listitem');
    expect(apiMocks.libraryCandidates).toHaveBeenCalledWith('tt1', 2, 3);
    await userEvent.click(within(rows[0]).getByRole('button', { name: 'Use' }));
    await userEvent.click(screen.getByRole('button', { name: 'Confirm' }));
    await waitFor(() => expect(apiMocks.librarySwap).toHaveBeenCalledWith('tt1', { info_hash: 'a'.repeat(40), season: 2, episode: 3, blacklist_old: false }));
  });

  it('empty and error states', async () => {
    apiMocks.libraryCandidates.mockResolvedValueOnce({ current: null, candidates: [] });
    const first = renderIt();
    expect(await screen.findByText('The scrapers returned nothing for this title.')).toBeInTheDocument();
    void first;
    apiMocks.libraryCandidates.mockRejectedValueOnce(new Error('502: scrapers unavailable: torrentio down'));
    apiMocks.libraryCandidates.mockResolvedValueOnce({ current: null, candidates: [cand({})] });
    renderIt();
    expect(await screen.findByText(/torrentio down/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(await screen.findAllByRole('listitem')).toHaveLength(1);
  });
});
```

- [ ] **Step 3: `ReleasesPanel.tsx`**

```tsx
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../../../api';
import type { Candidate } from '../../../api';
import { Button } from '../../../components/primitives';
import { DrawerCard } from './cards/DrawerCard';

function Badge({ tone, children }: { tone: 'ok' | 'muted' | 'warn'; children: React.ReactNode }) {
  const cls = { ok: 'bg-ok/20 text-ok', muted: 'bg-white/10 text-muted', warn: 'bg-warn/20 text-warn' }[tone];
  return <span className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${cls}`}>{children}</span>;
}

export function ReleasesPanel({ imdb, season, episode, onDone, onClose }: {
  imdb: string; season?: number; episode?: number; onDone: () => void; onClose: () => void;
}) {
  const q = useQuery({ queryKey: ['library-candidates', imdb, season, episode], queryFn: () => api.libraryCandidates(imdb, season, episode), retry: false });
  const [picked, setPicked] = useState<Candidate | null>(null);
  const [blacklistOld, setBlacklistOld] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const confirm = async () => {
    if (!picked) return;
    setBusy(true);
    try {
      const body = { info_hash: picked.info_hash, ...(season != null && episode != null ? { season, episode } : {}), blacklist_old: blacklistOld };
      const r = await api.librarySwap(imdb, body);
      setMsg({ ok: r.ok, text: r.message });
      if (r.ok) { onDone(); onClose(); }
    } catch (e) {
      setMsg({ ok: false, text: e instanceof Error ? e.message : 'swap failed' });
    } finally {
      setBusy(false);
    }
  };

  return (
    <DrawerCard title="Releases" description="What the scrapers found for this title; the current release is marked.">
      {q.isLoading && <p className="text-xs text-muted">Asking the scrapers...</p>}
      {q.error && (
        <p className="text-xs text-danger">{(q.error as Error).message} <Button variant="ghost" onClick={() => q.refetch()}>Retry</Button></p>
      )}
      {q.data && q.data.candidates.length === 0 && <p className="text-xs text-muted">The scrapers returned nothing for this title.</p>}
      {q.data && q.data.candidates.length > 0 && (
        <ul className="space-y-1">
          {q.data.candidates.map((c) => (
            <li key={c.info_hash} className={`rounded border border-border p-2 text-xs ${c.kept ? '' : 'opacity-60'}`}>
              <div className="flex flex-wrap items-center gap-2">
                <span className="max-w-[22rem] truncate font-mono" title={c.name}>{c.name}</span>
                {c.cached && <Badge tone="ok">cached</Badge>}
                {c.current && <Badge tone="muted">current</Badge>}
                {!c.current && <Button onClick={() => { setPicked(c); setMsg(null); }}>Use</Button>}
              </div>
              <div className="mt-1 text-muted">
                {[c.quality, c.source].filter(Boolean).join(' ')}{c.size_gb ? ` · ${c.size_gb} GB` : ''} · {c.seeders} seeders
                {c.languages.length ? ` · ${c.languages.join(', ')}` : ''} · {c.scrapers.join(', ')}
              </div>
              {!c.kept && <div className="mt-1 text-muted">dropped: {c.rule} = {c.value}</div>}
              {picked?.info_hash === c.info_hash && (
                <div className="mt-2 space-y-1 rounded border border-border bg-bg p-2">
                  <p>Switch to this release? The next play uses it; the file in Jellyfin stays the same.</p>
                  {!c.cached && <p className="text-warn">TorBox does not have this yet; the first play adds it and may wait.</p>}
                  <label className="flex items-center gap-2">
                    <input type="checkbox" aria-label="Blacklist the current release" checked={blacklistOld} onChange={(e) => setBlacklistOld(e.target.checked)} />
                    Blacklist the current release
                  </label>
                  <div className="flex items-center gap-2">
                    <Button variant="primary" onClick={confirm} loading={busy} loadingLabel="Switching...">Confirm</Button>
                    <Button variant="ghost" onClick={() => setPicked(null)}>Cancel</Button>
                    {msg && <span className={msg.ok ? 'text-ok' : 'text-danger'}>{msg.text}</span>}
                  </div>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </DrawerCard>
  );
}
```

The `·` separators are middle dots, not dashes. Adjust the `c.size_gb` rendering so `4.2` prints as `4.2 GB` (the test expects the text `4.2 GB` in its own element: wrap it in a `<span>{c.size_gb} GB</span>`).

- [ ] **Step 4: `ReleaseCard` button**

`ReleaseCard` gains an `onDone` prop and, for a movie with at least one item, a "Pick another release" `Button` under the rows that toggles `ReleasesPanel` (rendered inside the card, below the button) with `imdb={d.request.imdb_id}`, `onDone`, `onClose={() => setOpen(false)}`. For a title with no items the card is already hidden by its early return; when `d.request.media_type !== 'movie'` no button (episodes get theirs in Task 4). Update `TitleDrawer.tsx` to pass `onDone={refresh}` to `ReleaseCard`. Append to `cards.test.tsx`: rendering `ReleaseCard` with a movie detail and one item shows the button; clicking it renders the "Releases" heading and calls `libraryCandidates` (mock it in that file's hoisted mocks).

- [ ] **Step 5: Run, build, commit**

```bash
cd frontend && npx tsc --noEmit && npx vitest run && npm run build && cd ..
git add frontend/src static/app
git commit -m "feat(ui): releases panel with confirm strip, pick another release for a movie

Claude-Session: https://claude.ai/code/session_017Cc8iouqJoYhUcnJhhgapA"
```

---

### Task 4: Episode Swap button, docs, changelog

**Files:**
- Modify: `frontend/src/pages/admin/library/cards/EpisodesCard.tsx`, `cards.test.tsx`, `README.md`, `CHANGELOG.md`

- [ ] **Step 1: Failing test** (append to `cards.test.tsx`)

In the Episodes test's season fixture, E01 is present. Add: after expanding season 2, a `Swap` button exists on the E01 row and not on the missing E03 row; clicking it renders the "Releases" heading and calls `libraryCandidates('tt4', 2, 1)`.

- [ ] **Step 2: Implement**

In `Season` (EpisodesCard.tsx): state `swapping: number | null`; on a present episode row add `<Button variant="ghost" aria-label={\`Swap S${pad(season.season)}E${pad(e.episode)}\`} onClick={() => setSwapping(e.episode)}>Swap</Button>`; below the list, when `swapping != null`, render `<ReleasesPanel imdb={d.request.imdb_id} season={season.season} episode={swapping} onDone={onDone} onClose={() => setSwapping(null)} />`. The test clicks the button named `Swap S02E01`.

- [ ] **Step 3: Docs**

`README.md` admin row: after "plus a drawer with retry, re-resolve, purge, mirror and blacklist actions" add ", and a candidate list to pick another release for a movie or an episode". `CHANGELOG.md` under `## [Unreleased]`:

```markdown
### Added

- Pick another release from the Library drawer: the Release card (movies)
  and every present episode row show the candidate list the processor
  saw, with quality, size, seeders, languages, which scrapers returned it,
  whether TorBox has it cached, and the rule that dropped a candidate.
  Choosing one swaps the release behind the existing token, so the next
  play uses it and nothing on disk changes; the old release can be
  blacklisted in the same step.
```

- [ ] **Step 4: Both suites, build, commit**

```bash
PYTHONDONTWRITEBYTECODE=1 .venv-sdd/bin/python -m pytest tests/ -q -p no:cacheprovider
cd frontend && npx tsc --noEmit && npx vitest run && npm run build && cd ..
git add -A
git commit -m "feat(ui): swap an episode's release, docs

Claude-Session: https://claude.ai/code/session_017Cc8iouqJoYhUcnJhhgapA"
```

---

## Self-review notes

- Spec coverage: section 1 (candidates route with verdicts, cache badges, blacklist exclusion, 502; swap route with validation, candidate re-fetch, the seven side-effect steps minus the nfo clarification) in Tasks 1 and 2; section 2 (entry points, panel rows, confirm strip with the uncached warning and the blacklist checkbox, empty and error states with Retry, hidden without an item) in Tasks 3 and 4; section 3 side effects in Task 2; section 4 tests spread over the tasks; docs in Task 4.
- Type consistency: the candidate dict in Task 1 matches `Candidate` in Task 3; `swap_by_hash`'s body keys match `api.librarySwap`'s body; `ReleasesPanel` props match both call sites.
