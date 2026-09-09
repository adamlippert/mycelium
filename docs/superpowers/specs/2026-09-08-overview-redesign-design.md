# Admin Overview redesign

Date: 2026-09-08. Status: approved in conversation (mockup approved),
awaiting file review. Mockup: five bands, problems first, example
numbers, in the admin's own palette.

## Goal

The Overview answers "is anything wrong right now?" first, then "what is
happening", then "what is on the shelf", with TorBox in one card and the
reference material collapsed. Four numbers join the page (titles needing
attention, pending approvals, plays today and this week, scraper state)
and the two TorBox cards merge. Nothing leaves the page.

## Decisions taken

| Question | Decision |
|---|---|
| Top of the page | Status strip: services, scrapers, TorBox adds, failures 7d, queue, attention, approvals |
| New metrics | Attention count, pending approvals, plays today and this week, scraper strip |
| Cards removed | None. TorBox quota and TorBox usage merge into one card |
| Reference material | Metrics 30d, integration endpoints and top folders collapse; open state remembered per section in localStorage |
| Requests per refresh | One aggregated endpoint for everything the database can answer, plus the two network-bound queries that already exist (service health pings, TorBox list) |

## 1. Data: `GET /ui/api/overview` (admin)

New module `overview.py` with `build() -> dict`, cached the way
`stats.get_overview` is (same TTL, `force` for tests). Every figure comes
from the database or in-memory state; nothing here calls TorBox, Jellyfin
or a scraper. Shape:

```
status:
  scrapers: [{name, state, latency_ms}]        scrapers.health_rows()
  torbox_adds: {uncached, cached, limit, resets_in_sec}   torbox.createtorrent_usage()
  failures_7d: int                             db.get_request_stats(7)["failed"]
  queue: {retry, wanted}                       len(db.get_pending_retries()), wanted active
  attention: int                               library_admin.view_counts()["attention"]
  approvals: {pending, oldest_age_sec}         requests_admin: pending count, now minus oldest created_at
activity:
  plays: {today, week, titles_today, titles_week}
  requests_7d: {total, succeeded, failed, success_rate}
  egress: {proxied_bytes, estimated_bytes}
library:
  movies, episodes, series, wanted, upcoming   as stats.get_overview today
  qualities: {label: count}
  consistency: {db_items, strm_without_db, db_without_strm,
                arr_mirrored, arr_total, last_cleanup: {ran_at, deleted} | null}
torbox:
  recent_streams: int                          egress_estimate.recent(900)
  last_429_at: iso string | null               torbox.last_429_at()
```

Services (`api.health`) and TorBox torrents, states and plan
(`api.torboxUsage`) stay separate queries because they call other
services and already carry their own caching; the page reads the stream
front flag from the health payload as today.

Definitions:

- **Plays.** One `egress_log` row with `estimated = 1` is one play of a
  redirected (MKV) title. Proxied rows (`estimated = 0`) are one play per
  distinct `(token, calendar day)`. `today` is the server's calendar day,
  `week` the last seven days. `titles_*` counts distinct tokens across
  both kinds. New `db.play_counts(days) -> {plays, titles}`.
- **Recent streams.** Tokens the redirect branch resolved in the last 15
  minutes, from `egress_estimate._last_seen`; new
  `egress_estimate.recent(window_sec) -> int`. Proxied MP4 streams are
  not in that map; the label says "titles streamed in the last 15 min".
- **Last 429.** `torbox.add_magnet` records `time.time()` when TorBox
  answers 429; `torbox.last_429_at() -> float | None`. Never persisted;
  a restart forgets it, which the tile shows as "none since start".
- **Consistency.** `library_sync.orphans()` for the three counts (the
  existing library-health payload), `db.count_requests_mirrored() ->
  (mirrored, total)` over `requests.arr_mirrored_at` for success rows,
  `db.get_last_cleanup_run()`.
- **Approvals.** `requests_admin.view_counts()["pending"]` and the
  oldest pending row's age in seconds, or null.

## 2. Page

`frontend/src/pages/admin/Overview.tsx` becomes a thin composition of
components in `frontend/src/pages/admin/overview/`:

- `StatusStrip.tsx`: seven cells. Each cell: dot, label, number, one
  reason line, and a link only when the cell is amber or red. Tones:
  services red when any service is down; scrapers amber when any enabled
  scraper is down; TorBox adds amber from 45 uncached; failures red when
  above zero; queue amber when the retry queue is non-empty; attention
  amber when above zero; approvals amber when above zero. Links:
  services to `#settings`, scrapers to `#scrapers`, failures and
  attention to `#library?view=attention`, queue to `#library?view=queue`,
  approvals to `#requests`. Under the cells, `ScraperStrip.tsx`: one
  dot, name and latency per registry scraper (disabled ones dimmed).
- `ActivityBand.tsx`: a card with five tiles (plays today, plays this
  week, requests 7d, success rate 7d, egress this month with the
  proxied and estimated split) beside the recent-activity card. Activity
  rows get a pill by event family: play, swap, upgrade, request, wanted,
  scraper, job; unknown events show no pill. The card ends with a link
  to `#logs`.
- `LibraryBand.tsx`: size tiles (movies, episodes with series count,
  wanted with upcoming, on TorBox with torrent count), the quality bars
  (share of succeeded requests per resolution, as today), and a
  consistency card (DB items, strm without DB row, DB row without strm,
  arr mirror `n/m`, last cleanup time and deleted count) with a link to
  `#maintenance`.
- `TorboxCard.tsx`: three columns: adds budget (uncached bar against the
  limit, cached count, resets-in, per-reason rows), library (torrents,
  size, plan, state rows), streaming (stream front, titles streamed in
  the last 15 min, idle cleanup minutes from settings, last 429 as
  relative time or "none since start").
- `ReferenceSection.tsx`: a `details` element per section (Metrics 30d,
  Integration endpoints, Top folders). Open state is stored under
  `mycelium.overview.<id>` in localStorage, closed by default. Each
  section fetches its data only once opened (`enabled` on the query).
  Contents are the current cards moved verbatim.

Tile and card primitives stay as they are; the status cell is a new
primitive `StatusCell` in `components/primitives` since the same shape
may serve other pages.

## 3. Behaviour and edge cases

- The aggregated query refreshes every 30 s like the current stats
  query; the activity feed every 60 s; reference sections on open.
- A failed aggregated query shows the strip with "unavailable" cells and
  keeps the rest of the page usable from the other queries.
- Every existing endpoint stays; nothing outside the Overview changes.
- Numbers keep their current formats: TB with two decimals for egress,
  GiB for the TorBox library, percentages rounded.

## 4. Testing

Backend (`tests/test_overview.py`, own `_isolated_db` fixture, faked
`scrapers.health_rows`, `torbox.createtorrent_usage`,
`library_sync.orphans`): the shape above with seeded rows; play
counting (three estimated rows and four proxied rows over two days for
one token yield the documented figures); approvals age; consistency
counts; `recent()` window and `last_429_at()`; the route guard on
source text (admin only, cached build).

Frontend (`overview/*.test.tsx` and `Overview.test.tsx`): each cell's
tone and link from a fixture payload; the scraper strip; the activity
tiles and pills; the library band values; the merged TorBox card; the
reference sections closed by default, remembered when opened, and
fetching only when opened. The existing Overview tests are rewritten
against the new structure; the guard "never resurrects the dropped
mockup tiles" is kept in spirit as a check that the old duplicate
TorBox card is gone.

## 5. Delivery

Five tasks: (1) `overview.py`, the db helpers, `egress_estimate.recent`,
`torbox.last_429_at`, the route; (2) `StatusCell`, `StatusStrip`,
`ScraperStrip`; (3) `ActivityBand` and `LibraryBand`; (4) `TorboxCard`,
`ReferenceSection`, the page composition and the rewritten page tests;
(5) docs and changelog. Subagent-driven, one opus whole-branch review,
released as 0.25.0 on request.

## Risks

The page is the first thing an admin sees; a regression there is
noticed immediately, which is also why the rewrite keeps every number's
source and format. The play count is derived from the egress rows and
inherits their known errors (a viewer who stops early still counts, two
viewers on one title at once count as one).
