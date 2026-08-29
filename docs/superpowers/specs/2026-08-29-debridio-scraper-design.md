# Debridio as the default scraper

**Date:** 2026-08-29
**Status:** approved design, not yet implemented

## Problem

Mycelium scrapes candidates from Zilean and Torrentio. We want to add
[Debridio](https://debridio.com) as a third source and make it the default —
first in priority, not a fallback.

Two things stand in the way. Debridio's stream objects have no `infoHash`
field, and mycelium's pipeline is keyed on `info_hash` end to end (dedup,
blacklist, `magnet`, the TorBox add, `virtual_items`). And there is no scraper
abstraction to add a third source to: the orchestration is hand-rolled at six
call sites in three mutually inconsistent patterns.

## Feasibility findings

Probed live against a real Debridio account on 2026-08-29, movie `tt15239678`
(Dune: Part Two) and series `tt0903747:1:1` (Breaking Bad S1E1).

The addon is `org.adobotec.debridio-scraper-TB`, `resources: ["stream"]`,
`types: ["movie","series"]`, `idPrefixes: ["tt","kitsu"]`. Every endpoint is
config-gated: `https://addon.debridio.com/<config>/stream/<type>/<id>.json`,
where `<config>` is base64 JSON containing the Debridio API key **and** the
user's TorBox key. Unconfigured paths 404.

Every stream has the shape `['behaviorHints','name','title','url']` — no
`infoHash`, no `fileIdx`. But the info hash is present in two places:

- `behaviorHints.bingeGroup` as `debridio-<40 hex>`
- the play-URL path: `/play/<type>/torbox/<apikey>/<providerkey>/<40 hex>/<filename>`

Across 702 movie streams both locations were present, agreed with each other,
and were distinct — 702/702 on all three checks. They are genuine BitTorrent
info hashes, not opaque identifiers: **88 of Torrentio's 111 hashes for the
same title appear verbatim in Debridio's set.**

| Signal | Debridio | Torrentio |
|---|---|---|
| streams returned | 702 | 111 |
| distinct info hashes | 702 | 111 |
| of Torrentio's hashes | 88 (79%) | — |
| marked cached on TorBox (`⚡`) | 282 | n/a |
| existing `_SIZE_RE` (`💾`) matches | 699/702 | — |
| existing `_SEEDERS_RE` (`👤`) matches | 408/702 | — |
| `behaviorHints.filename` present | 702/702 | — |

Debridio uses the same emoji conventions Torrentio does, so the existing
ranking parsers work with no modification.

**Conclusion: feasible.** `debridio.py` can emit ordinary stream objects with a
real `info_hash`, and every downstream stage works unchanged.

## Goals

- Add Debridio as a scraper, first in priority.
- All three scrapers are queried; results merge and dedup by hash, with
  Debridio winning ties. A lapsed or broken Debridio degrades to Zilean and
  Torrentio without failing a request.
- Replace six hand-rolled orchestration sites with one shared helper.
- Attribute wins honestly, including which sources *also* had the winner.

## Non-goals

- Kitsu IDs. Debridio accepts them; mycelium is IMDb-keyed throughout. Out of
  scope.
- Playing Debridio's resolved `url`s directly. We use Debridio purely as an
  indexer, taking the hash and feeding TorBox as today. Adopting resolved URLs
  would bypass the `.strm`/virtual-item pipeline entirely — a different
  feature, not this one.
- A general plugin system for scrapers. Three sources and one ordered list.

## Design

### `streams.py` (new) — shared model and ranking

`TorrentioStream` and `rank_streams` move here. With three sources, ranking
Debridio results by calling a function named after Torrentio is actively
misleading.

```python
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
    cached: bool = False                    # new: debrid-cached (Debridio ⚡)
    also_seen_in: tuple[str, ...] = ()      # new: other sources with this hash
```

`torrentio.py` re-exports `Stream as TorrentioStream` and `rank_streams`, so
all existing imports and tests keep working unchanged.

`source` keeps its `"torrentio"` default for backward compatibility. This is a
footgun — a new scraper that forgets to set it is silently misattributed rather
than erroring — so each scraper gets a test asserting its own `source` value.

### `debridio.py` (new)

```python
def fetch(media_type: str, imdb_id: str,
          season: int | None = None, episode: int | None = None) -> list[Stream]
```

- URL: `{DEBRIDIO_URL}/stream/{movie|series}/{tt…}.json`, series IDs as
  `tt0903747:1:1`.
- Hash: `behaviorHints.bingeGroup` minus the `debridio-` prefix; fall back to
  the 40-hex path segment; if neither yields `^[0-9a-f]{40}$`, skip the stream
  and increment a counter logged once per call. A silent upstream shape change
  must surface in logs, not vanish.
- `source="debridio"`, always set explicitly.
- `cached=True` when `⚡` appears in `name`.
- Quality/size/seeders parsed with the existing helpers, using
  `behaviorHints.filename` as the release name.
- Results capped at `DEBRIDIO_MAX_RESULTS` (default 100). The cap is applied
  *after* parsing and sorting by quality then size, so it keeps the best N
  rather than an arbitrary N — Debridio's own response ordering is not
  documented and must not be relied on.
- **Never logs its URL.** See Secret handling.

### `scrapers.py` (new) — the orchestrator

```python
_SCRAPERS = [   # order is priority
    ("debridio",  lambda: settings.get("DEBRIDIO_ENABLED", False), debridio.fetch),
    ("zilean",    lambda: settings.get("ZILEAN_ENABLED", False),   zilean.fetch),
    ("torrentio", lambda: True,                                     torrentio.fetch),
]

def fetch_candidates(media_type, imdb_id, season=None, episode=None, *,
                     prefer_season_pack=False, override=None) -> list[Stream]
```

Behaviour:

1. Skip scrapers that are disabled or `health_cache.is_up(name)` is false.
2. Fetch the remainder **concurrently** (a `ThreadPoolExecutor`, as
   `catbox.py` already does), so three sources cost roughly one round trip.
3. Merge results in `_SCRAPERS` order — not completion order — so dedup is
   deterministic and Debridio wins ties.
4. On a duplicate hash, keep the first stream and append the later scraper's
   name to its `also_seen_in`.
5. Isolate each scraper in `try/except`; one failing source must not fail the
   request. Today a Torrentio exception propagates out of
   `processor._fetch_movie_candidates`.
6. Return `rank_streams(merged, prefer_season_pack=…, override=…)`.

All six call sites — `processor.py` (×2), `monitor.py` (×2), `upgrader.py`
(×2), `cleanup.py`, `catbox.py` — migrate onto this.

### Settings

| Key | Default | Notes |
|---|---|---|
| `DEBRIDIO_ENABLED` | `false` | Existing installs unaffected until configured |
| `DEBRIDIO_URL` | `""` | Paste the manifest URL; we strip a trailing `/manifest.json` |
| `DEBRIDIO_MAX_RESULTS` | `100` | Caps per-query volume |

Added to `HOT_RELOAD` and the Connections group in `SETTING_GROUPS`.

### Secret handling

`DEBRIDIO_URL` embeds both the Debridio API key and the user's TorBox key. It
must be treated as sensitive as `TORBOX_API_KEY`. Three concrete leak paths
exist today and each needs closing:

1. **Settings UI.** `templates/ui.html:1233` decides to mask a field with
   `/KEY|TOKEN|SECRET|PASSWORD/.test(it.key)`. `DEBRIDIO_URL` matches none of
   them, so it would render as a plaintext pre-filled input. Add `DEBRIDIO_URL`
   to that predicate. The heuristic is fragile — a server-supplied `secret`
   flag per setting would be the real fix — but that is out of scope here and
   noted as a follow-up.
2. **Scraper logging.** `torrentio.py:189` logs its full request URL. The
   equivalent line for Debridio would write the TorBox key into the log buffer
   and the admin Logs tab. `debridio.py` logs the scraper name and result count
   only, and a `_redact(url)` helper exists so the pattern cannot be
   reintroduced by copy-paste.
3. **Health probes.** Both `health.py::_ping` and `health_cache.py::_probe` log
   or return `str(exc)`, and `requests` exception messages embed the URL. The
   Debridio probe must pass exceptions through `_redact` before logging or
   returning them.

### Health

`health_cache._probe` gains a `"debridio"` branch hitting
`{DEBRIDIO_URL}/manifest.json` (200 today, cheap, no stream query).
`is_up("debridio")` returns false when disabled or unset, mirroring the
existing Zilean guard. `health.py::check_all` gains a Debridio entry, reporting
`disabled` when off. A lapsed subscription returns 401/403, marks it down, and
traffic flows to the other scrapers automatically.

### Metrics

`source_win` already records `winner.source`, and the admin UI
(`ui.html:1085`), the Prometheus counter, and `assets/grafana-dashboard.json`
are all label-driven — Debridio appears automatically once `debridio.py` sets
its `source`.

But win rate alone will mislead. It measures which source survived *dedup*, and
dedup is won by merge order. Debridio is first and is a 79% superset of
Torrentio, so it will absorb wins Torrentio previously recorded for the same
torrent. The chart will show Debridio dominance within days as an artifact of
ordering, not as evidence of better content.

So alongside the existing metric we record a second one:

- `source_win` — unchanged, `winner.source`.
- `source_unique_win` — recorded only when `winner.also_seen_in` is empty, i.e.
  this source found a torrent no other source had.
- Prometheus: `mycelium_source_unique_wins_total`, `source` label.
- `/ui/api/metrics-summary` (`app.py:2073`) returns both summaries; the Source
  Win Rate card shows the unique count alongside the total (e.g.
  `142 (37 unique)`).

`source_unique_win` is the number that justifies the subscription, and the
number that reveals whether Zilean and Torrentio still earn their place.

## Behaviour changes

| Where | Today | After |
|---|---|---|
| `upgrader.py`, `cleanup.py` | Zilean wins outright; Torrentio never called | merged — more HTTP calls in background jobs |
| `monitor.py` | not health-gated | health-gated like the rest |
| all six sites | a scraper exception propagates | isolated and logged |

These are deliberate. The first is the main regression risk: both are
background jobs, so a fault surfaces slowly.

## Testing

`tests/test_debridio.py`
- hash from `bingeGroup`; hash from URL path when `bingeGroup` is absent;
  both present and disagreeing (bingeGroup wins); neither present (skipped and
  counted)
- `source == "debridio"` — guards the dataclass default footgun
- `cached` set from `⚡`
- quality/size/seeders parsed from real captured payloads
- malformed JSON, empty `streams`, HTTP error → `[]`, never raises
- `DEBRIDIO_MAX_RESULTS` respected
- the URL never appears in any log record (caplog assertion)

`tests/test_scrapers.py`
- priority order: Debridio's stream wins a duplicate hash
- `also_seen_in` accumulates the later sources, in order
- a scraper raising does not fail the call; others still contribute
- disabled and unhealthy scrapers are skipped
- all scrapers empty → `[]`
- merge order is independent of completion order (slow first scraper still wins)

Fixtures are captured from the real payload with URLs and keys stripped. No
network access in tests.

Existing suites must stay green via the `torrentio.py` re-exports.

## Risks

| Risk | Mitigation |
|---|---|
| Paid dependency in the primary path | Default off; health-gated; merge-not-replace, so lapse degrades silently |
| TorBox key leaking via URL | Three leak paths closed above, plus a caplog test |
| 6x result volume → ranking and TorBox cache-check cost | `DEBRIDIO_MAX_RESULTS` cap; user can also set `maxReturnPerQuality` in Debridio |
| `upgrader`/`cleanup` behaviour change | Covered by `test_scrapers.py`; kept as separate reviewable commits |
| New scraper forgets `source` | Explicit per-scraper assertion in tests |

## Rollout

1. Ship with `DEBRIDIO_ENABLED=false`. No migration; no existing install changes
   behaviour until configured.
2. User pastes the manifest URL into Settings and enables it.
3. Verify: request one movie and one TV title, then disable Debridio and
   confirm requests still succeed — that exercises the whole degradation path.
4. After a week, compare `source_unique_win` across the three scrapers.

## Follow-up, out of scope

- Replace the client-side `/KEY|TOKEN|SECRET|PASSWORD/` masking heuristic with
  a server-supplied `secret` flag per setting.
- Consider using Debridio's `cached` flag to skip TorBox cache-check API calls.
