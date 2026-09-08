# Comet and MediaFusion as scrapers

Date: 2026-09-08. Status: approved in conversation, awaiting file review.
First half of Field Report batch B. Builds on the scraper registry in
`scrapers.py` (Debridio, Zilean, Torrentio).

## Goal

Two more candidate sources for the processor, the catbox search, the
upgrader and the swap panel: Comet and MediaFusion. Both expose a
Torznab feed, so one shared adapter serves both, and everything keyed on
the registry (concurrent fetch, dedupe, outage guard, metrics, the
Scrapers page) picks them up without changes.

## Facts from the repositories and live probes

- MediaFusion (`backend/src/routes/torznab.rs`): route `/torznab`,
  parameters `t`, `apikey`, `q`, `imdbid`, `tmdbid`, `season`, `ep`,
  `limit`, `offset`; `imdbid` gets a `tt` prefix when missing; `limit`
  clamps to 1..100, default 50; a private instance (`API_PASSWORD` set)
  requires `apikey`, a public one ignores it. Items carry `title`, `guid`
  (the hash), `link` and `enclosure` (magnet), `size`, and `torznab:attr`
  entries `category`, `size`, `infohash`, `magneturl`, `seeders`,
  `peers`, `imdb`, `tmdbid`. The public instance
  `https://mediafusion.elfhosted.com/torznab` answered `t=caps`, a movie
  search and an episode search with 50 items each on 2026-09-08; some
  items have no `seeders` attribute.
- Comet (`comet/api/endpoints/torznab.py`, `comet/core/config_validation.py`):
  route `/torznab/api`, parameters `t` (caps, search, movie, tvsearch),
  `q`, `imdbid`, `season`, `ep`, `cat`, `o`, `year`; no api key; the
  handler uses the instance's default config with torrent results
  enabled, so a self-hosted instance needs no extra configuration. Items
  carry the same attributes plus `language` and `resolution`. The public
  ElfHosted instance answers 403 on this path, so Comet is self-hosted
  only; a protected instance carries its access token in the URL path
  (`/s/<token>/torznab/api`), which the URL field accepts as typed.

## 1. Adapter and registry

New `torznab_scraper.py`:

```
fetch(name, base_url, path, media_type, imdb_id, season=None, episode=None,
      *, api_key="", timeout=30, raise_on_error=False) -> list[Stream]
```

- Movies: `GET <base><path>?t=movie&imdbid=<tt...>&limit=100`. Episodes:
  `t=tvsearch&imdbid=...&season=N&ep=M&limit=100`. `apikey=<key>` only
  when a key is set. `base_url` is used as typed, trailing slash stripped.
- Parsing with `xml.etree.ElementTree`. Per item: info hash from the
  `infohash` attribute, else a 40-hex `guid`; skipped otherwise. Size in
  bytes from the `size` attribute or element, converted to gigabytes;
  seeders from the attribute, 0 when absent; `title` as both `name` and
  `title`; quality via `parse_quality`, languages via
  `detect_languages`, season pack via the same title regex Torrentio
  uses; `source=name`; `cached=False` (Torznab carries no cache
  information; Mycelium checks TorBox itself).
- Items without a usable hash are counted and reported in one warning
  line. Request and parse failures return `[]` by default and re-raise
  with `raise_on_error=True`, so `scrapers.py`'s outage guard sees them.
- Results are deduped on hash inside one response.

Registry (`scrapers._SCRAPERS`) in this order: debridio, zilean, comet,
mediafusion, torrentio. Each new entry has a small fetch adapter reading
its URL and key from settings. Health probe (`health_cache._probe`):
`GET <base><path>?t=caps` with a three-second timeout; any status of 400
or above means down.

## 2. Settings, testers, docs

Keys (hot-reloadable, in the "Scrapers and metadata" section after the
Zilean and Debridio fields):

| Key | Kind | Default | Notes |
|---|---|---|---|
| `COMET_ENABLED` | bool | false | |
| `COMET_URL` | url | "" | required when enabled, placeholder `http://comet:8000`, `depends_on=COMET_ENABLED`, `test=comet` |
| `MEDIAFUSION_ENABLED` | bool | false | |
| `MEDIAFUSION_URL` | url | `https://mediafusion.elfhosted.com` | `depends_on=MEDIAFUSION_ENABLED`, `test=mediafusion` |
| `MEDIAFUSION_API_KEY` | secret | "" | only for a private instance, `depends_on=MEDIAFUSION_ENABLED`, `test=mediafusion` |

No wizard step. Testers `test_comet` and `test_mediafusion` fetch
`t=caps` with the values as typed and report the caps `server` title and
version; a 403 from Comet reports "this instance does not expose Torznab;
use your own Comet URL"; a blank URL reports the schema label.

Docs: a "Comet and MediaFusion" section in `docs/INTEGRATIONS.md`, the
README scraper list, the changelog.

## 3. Testing

- `tests/test_torznab_scraper.py` (faked `requests.get`): URLs and
  parameters for movie and episode, `apikey` only when set; parsing of a
  fixture derived from the captured MediaFusion feed (hash, bytes to
  gigabytes, seeders present and absent, quality, languages, season
  pack); invalid items skipped with one warning; failures return `[]` or
  raise with `raise_on_error`; in-response dedupe.
- `tests/test_scrapers.py`: order of the registry; disabled entries
  skipped; merge and `also_seen_in` across the five; the all-enabled
  fixture wires the two new fetchers to fakes.
- `tests/test_scraper_health_page.py` and the health cache test: disabled
  rows; a caps probe returning 403 shows "down".
- `tests/test_settings_schema.py`: keys placed and typed, testers named.
- Tester tests: caps parsed into the message, 403 wording, blank URL.
- Mutation check on every new test; no network in tests.

## 4. Delivery

Four tasks: (1) adapter and tests; (2) registry, probe and metrics
wiring; (3) settings, config and testers; (4) docs and changelog.
Subagent-driven, one opus whole-branch review, released as 0.24.0 on
request.

## Risks

The public MediaFusion feed is shared and may rate-limit or change shape;
its failures are contained by the outage guard and show as "down". Up to
100 more candidates per scraper per query pass through the ranker and one
batched cache check, which already handle that volume.
