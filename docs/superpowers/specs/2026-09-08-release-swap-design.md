# Release swap: pick another release from the drawer

Date: 2026-09-08. Status: approved in conversation, awaiting file review.
Plan 3 of the Library admin work. Builds on the title drawer (0.19.0) and
the catbox auto-upgrade path, which already replaces a release behind an
existing token.

## Goal

When the automatic pick for a title is wrong (language, a cam, stutters,
missing subtitles), let an admin see the candidate list the processor
saw and choose a different release from the Library drawer. The next
play uses the new release; nothing on disk changes.

## Decisions taken

| Question | Decision |
|---|---|
| Scope | Movies and single episodes. Whole-season pack swap is a follow-up |
| Candidates | Every scraper result, kept ones first in the processor's order, then the ones the rules dropped (greyed, with the rule), cached ones badged. Blacklisted hashes excluded. Picking a dropped or uncached one is allowed with a warning |
| Mechanism | Swap behind the token (the catbox auto-upgrade path), not remove and re-add |
| Old release | Left alone unless the admin ticks "Blacklist the current release" |
| Live scrape | Runs only when the panel is opened; never in the background; not cached server side |

## 1. Data and endpoints

No schema change.

### `GET /ui/api/library/<imdb_id>/candidates` (admin)

Optional `season` and `episode` query params select one episode;
without them the title is a movie. Returns
`{current: {info_hash, quality, source}, candidates: [...]}`. Each
candidate: `info_hash, name, quality, source, size_gb, seeders,
languages, cached, scrapers, kept, rule, value, current`. `kept`,
`rule` and `value` come from the explained ranker's verdict (`rule` and
`value` are null when kept). `cached` from one `check_cached_multi`
call over the list. Order: kept candidates in the processor's order,
then dropped candidates in scraper order. Blacklisted hashes are
excluded before ranking, as the processor does.

Implementation: new `release_swap.py` with
`candidates(imdb_id, media_type, season=None, episode=None) -> dict`
built on `scrapers.merge_candidates`, `streams.rank_streams_explained`,
`blacklist.filter_candidates` and `debrid.check_cached_multi`. Scraper
failures surface as `{error}` with HTTP 502 so the panel can offer
Retry; an empty result is `{candidates: []}`.

### `POST /ui/api/library/<imdb_id>/swap` (admin)

JSON body `{info_hash, season?, episode?, blacklist_old: bool}`.
Validation: 40 hex chars; the title exists; the virtual item exists (the
movie item, or the episode item by season and episode); the hash differs
from the item's current hash. The new hash's metadata (name, quality,
source, size) comes from the candidate list fetched again server side
for that title, so the client cannot invent it; if the hash is not in
the list the swap is refused.

`release_swap.swap(item, candidate, blacklist_old) -> {ok, message}`:

1. `db.update_virtual_item_upgrade(token, info_hash, magnet, quality, source)`
   (clears torbox_id and file_id).
2. `catbox.invalidate_url_cache(token)` and remove the token's fast-start
   cache file if present.
3. `db.reset_playability_state(content_key)` for the item's key.
4. Movies only: update `requests.quality`, `source` and `info_hash`
   without touching `status` (a new narrow helper
   `db.set_request_release(row_id, quality, source, info_hash)`).
5. `strm_generator.update_nfo_streamdetails(strm_path, quality, ...)` when
   the `.nfo` exists.
6. `db.log_activity("swapped", title, "<old quality> to <new quality>", True, imdb_id)`.
7. If `blacklist_old`: `db.blacklist_hash(old_hash, "replaced by admin")`.

Returns `{ok: true, message: "next play uses <quality> <source>"}`.
Refusals return `{ok: false, message}` with HTTP 200 like the other
drawer actions, except the auth guard.

## 2. Drawer UI

**Entry points.** The Release card gets a "Pick another release" button
for movies. In the Episodes card, every present episode row in an
expanded season gets a "Swap" button. Both open the Releases panel below
the card they belong to. The button is hidden when the title has no
virtual item (a wanted title has nothing to swap) and the card says so.

**Releases panel.** A card titled "Releases" with the description "What
the scrapers found for this title; the current release is marked".
Loading state: "Asking the scrapers...". Rows: name (mono, truncated,
full name in the title attribute), quality and source, size, seeders,
languages, a "cached" badge, a "current" badge, and for dropped
candidates a muted line "dropped: <rule> = <value>" with the row greyed.
Kept first, then dropped. A "Use" button on every row except the current
one.

**Confirm strip.** Use opens an inline strip in that row: "Switch to this
release? The next play uses it; the file in Jellyfin stays the same.", a
checkbox "Blacklist the current release" (off), Confirm and Cancel. For
an uncached candidate the strip adds "TorBox does not have this yet; the
first play adds it and may wait." Confirm posts the swap, shows the
result inline, refetches the drawer and the table, and closes the panel.

**Empty and error states.** No candidates: "The scrapers returned
nothing for this title." Scraper failure: the error message and a Retry
button.

## 3. Side effects

A swap resets the item's playability record, invalidates the URL cache
and the fast-start cache for the token, and leaves the arr mirror, Seerr
and the files untouched. A stream already playing may switch to the new
file on its next range request, because the Go front resolves every
request. The old hash stays usable unless blacklisted.

## 4. Testing

Backend: `release_swap.candidates` with faked scrapers and cache check
(kept before dropped, current marked, blacklisted hashes excluded,
verdict fields on dropped rows, 502 on scraper failure);
`release_swap.swap` on a seeded movie item (hash, magnet, quality and
source replaced; torbox ids cleared; playability reset; request row's
release fields updated with status preserved; activity row; blacklist
flag honoured) and on an episode item (request row untouched); refusals
(same hash, bad hash, unknown title, unknown episode, hash not in the
candidate list); route guards on source text.

Frontend: the Release card button opens the panel; rows render badges
and the dropped reason; Use opens the confirm strip; the uncached
warning appears only for uncached rows; Confirm posts
`{info_hash, blacklist_old}` (and `season`, `episode` from the episode
button) and refetches; empty and error states with Retry; the button is
hidden without a virtual item.

## 5. Delivery

One plan, four tasks: (1) `release_swap.candidates` and the candidates
route; (2) `release_swap.swap`, the swap route, the request-release
helper and the side effects; (3) the Releases panel with the confirm
strip and the Release card button; (4) the episode Swap button, docs,
changelog. Subagent-driven with an opus whole-branch review; released as
0.21.0 on request.

## Risks

The candidates call is a live scrape, as slow and as flaky as the
scrapers, and it runs only on demand. A swap already made stays after a
rollback, and swapping back is one more click.
