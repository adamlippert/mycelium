# Catbox comparison: Mycelium vs ElfHosted's CatBox

Research only. Nothing in this report is built. Written against the code as
it stands on 2026-09-14, before the planned split of `catbox.py` into
`catbox_jobs.py` and `catbox_packs.py` and of `app.py` into `routes/`.
Mycelium functions are cited by module and function name, not line number,
so this stays valid after that move.

## 1. Sources

Read 2026-09-14:

- https://docs.elfhosted.com/app/catbox/ (redirects, 301, to the store page below)
- https://docs.elfhosted.com/guides/media/jellyfin-torbox-aars/
- https://docs.elfhosted.com/guides/media/torbox/
- https://store.elfhosted.com/product/catbox/
- https://docs.elfhosted.com/guides/media/plex-torbox-aars/ (linked from the guides above)
- https://docs.elfhosted.com/guides/media/emby-torbox-aars/ (linked from the guides above)

Labels used after each behaviour below: `jellyfin-torbox-aars` = the Jellyfin guide, `torbox` or `torbox guide` = the TorBox guide, `store` = the store page, `plex guide` = the Plex guide, `emby guide` = the Emby guide, each the URL listed above.

All six loaded. Further links found on these pages but not fetched, because
they lead away from the CatBox mechanism itself: the Real-Debrid-to-TorBox
migration guide, a general FAQ page, a "Jellyfin + Gelato" alternative
guide, a support page, and a store category page for Plex personal stacks.
None of the four pages that were fetched pointed to a dedicated changelog.

## 2. What ElfHosted's CatBox does

- Radarr/Sonarr (and Lidarr/Readarr/Prowlarr) submit releases to CatBox through a qBittorrent-compatible API; nothing is added to TorBox at that point. (jellyfin-torbox-aars, store)
- CatBox virtualizes the library: a symlink in the media server's folder points into a virtual WebDAV path (`/storage/torbox/...`); the media server's filesystem monitor picks it up on its own. (jellyfin-torbox-aars, store)
- When the media server probes a file for codec, resolution, runtime or chapter data, CatBox answers from a pool of synthetic or crowdsourced probe data shared across every CatBox tenant, so TorBox is never touched by a probe. (all four core pages, Plex and Emby guides)
- An item materializes in the TorBox account only when actual playback starts: CatBox adds the torrent, fetches a presigned URL, and proxies the stream. (jellyfin-torbox-aars, store)
- After playback ends, CatBox removes the item from the TorBox account again. The symlink and the library entry stay, so the title still appears; TorBox just no longer holds it against the account. (jellyfin-torbox-aars, torbox, store, plex guide)
- For a direct-play request, CatBox can redirect straight to a signed TorBox CDN URL so bytes go client to TorBox, bypassing ElfHosted's own infrastructure. (jellyfin-torbox-aars, store, "DirectStream")
- When the media server needs to transcode, remux or serve HLS segments, CatBox falls back to normal proxying through the media server instead of the CDN redirect, so playback behaves like a regular stream. Stated for Jellyfin and repeated for Plex. (jellyfin-torbox-aars, plex guide)
- Plex cannot use `.strm` files at all, so CatBox is FUSE-backed there rather than using the lighter streaming-URL method Jellyfin and Emby get. (plex guide)
- New torrents are added cached-only by default (TorBox's `add_only_if_cached`); an optional UI toggle allows uncached fetches, kept separate from the playback queue. (store)
- CatBox exposes its own Torznab indexer endpoint (`/torznab`) so Prowlarr can search what it already has cached, and runs background availability checking that flags items no longer available. (store)
- Each CatBox tenant keeps a small SQLite catalog of release state and settings; symlinks live under `/storage/symlinks/downloads/<category>/`. (store)
- The reason CatBox exists at all: TorBox's policy forbids automated tools from artificially keeping items in a user's library past 30 days, and unrestricted media-server probing against raw TorBox content would re-assert items on every scan and extend retention indefinitely. The virtual-library design is built around that constraint. (torbox guide, store)
- The standalone product is a hosted, single-account (or bring-your-own-key) service; the documentation describes no multi-account or multi-debrid pooling, only a one-way migration guide from RealDebrid to TorBox. (store, torbox guide)

## 3. Mapping

| Behaviour | ElfHosted | Mycelium | Verdict | Where in Mycelium |
|---|---|---|---|---|
| Lazy materialization on first play | Torrent stays virtual until an actual play event | `materialize()` / `_materialize_locked()` do the same on play, but `CATBOX_PRELOAD` (default true) also adds the torrent in the background right after the `.strm` is registered, so most titles are already warm before the first play | different by design | `catbox.py` `materialize`, `_materialize_locked`; `strm_generator.py` `_preload_torrent`, `create_lazy_movie_strm`, `create_lazy_episode_strm` |
| Metadata probe answered before first play | Synthetic/crowdsourced probe data, TorBox never touched | None. Jellyfin gets real codec, language and subtitle data only after the first `PlaybackInfo` probe (open point in CLAUDE.md); before that the `.nfo`/stub carry only what TMDB and the release name gave at add time | missing | none |
| qBittorrent-compatible API for arr submissions | Radarr/Sonarr talk to CatBox as if it were a torrent client | Mycelium mirrors titles directly into Radarr/Sonarr over their REST API as monitored, search-off entries, and separately writes a tiny stub `.mkv` per title into a folder the arrs mount as root, so they show the title as owned | different by design | `arr_sync.py` `mirror_add`, `_add_movie`, `_add_series`; `arr_stubs.py` `write_title` |
| Symlink into a virtual WebDAV tree | Yes, for Jellyfin, Emby and (via FUSE) Plex | `.strm` files carrying a proxy URL (`/stream/<token>`), native to Jellyfin/Emby/Kodi; a separate optional WebDAV server exists for Plex/Emby but is a different mechanism, not symlink-based | different by design | `strm_generator.py` `create_lazy_movie_strm`, `create_lazy_episode_strm`; `catbox.py` `register`, `proxy_url`; `webdav.py` |
| Removal from the debrid account after playback | Removed right after playback ends | Removed by an idle-timeout sweep (`CATBOX_IDLE_MINUTES`, default 1440 minutes / 24 hours), not tied to a playback-stop event | different by design | `catbox.py` `release_idle` |
| Direct-play requests redirected to a signed CDN URL | Yes, bytes bypass the app | Same for MKV/other non-MP4: `/stream/<token>` is a 302 to `/spore-stream/<token>`, which live-checks and 302s again to the TorBox CDN | same | `catbox.py` `materialize`; `spore-stream/stream.go` |
| Bytes proxied instead of redirected for transcode-shaped requests | Jellyfin and Plex fall back to proxying for transcode, remux and HLS | MP4 is always proxied through a moov-first cache, because TorBox serves MP4 with `moov` at the end (mdat-before-moov), not because of a transcode decision | different by design | `mp4_faststart.py` `build_and_cache`, `serve_bytes` |
| Add new torrents cached-only by default | `add_only_if_cached` | `_materialize_locked` only ever adds a release TorBox's cache-check already confirmed (`cached=True`) | same | `catbox.py` `_materialize_locked` (the `torbox.add_magnet(..., cached=True)` call) |
| Optional toggle for uncached fetches | Yes, kept apart from the play queue | No such toggle in the catbox path | missing | none |
| Self-hosted Torznab indexer endpoint | `/torznab`, for Prowlarr | Mycelium consumes Torznab feeds (Comet, MediaFusion) but exposes none of its own | missing | none |
| Background availability checking | Flags items no longer available | Hourly `reconcile_torbox_ids()` compares stored TorBox ids against each account's live list, clears or repoints stale ones | same | `catbox.py` `reconcile_torbox_ids` |
| Multi-arr support (Lidarr, Readarr, Prowlarr) | All five arr tools accepted | Radarr and Sonarr only; Mycelium's whole pipeline (TMDB metadata, scrapers, `.strm` layout) is movies and series only | missing | none |
| Plex integration without `.strm` | FUSE-backed virtual files | Spore: stub `.mkv` + a Plex Transcoder wrapper script + the `spore-stream` proxy; code exists, not deployed on the current VPS | different by design | `spore/plex_transcoder_wrapper.sh`, `spore_server.py`, `strm_generator.py` `make_stub_mkv` |
| Multiple debrid accounts as a hedge | Not described; one account per tenant (or a one-way RD-to-TorBox migration) | TorBox account pool (several API keys as peers, 0.29.0) plus an optional RealDebrid fallback per item | different by design (Mycelium goes further) | `torbox_pool.py` `choose_for_add`, `accounts`; `catbox.py` `_adopt_or_choose`, `_rd_get_url` |
| Per-tenant catalog of release state | SQLite catalog per tenant | SQLite (`requests.db`), single-tenant, same idea | same | `db.py` (`virtual_items` table) |

Counts: same 4, different by design 7, missing 4.

## 4. Missing behaviours rated

**Metadata probe answering before first play (missing).** This is the one
gap a real user notices without digging: a freshly added title shows up in
Jellyfin with placeholder or absent codec, language and subtitle
information until someone actually plays it once, which is exactly the
"janky" complaint already logged as an open point. For four to six users
browsing a library together this matters more than it would for a single
viewer, because someone else's first play is what fixes the listing for
everyone. Mycelium already has the groundwork: a 2026-09-08 spike found
that `POST /Items/{id}/PlaybackInfo` with a user id makes Jellyfin probe
and store real stream info without playing anything. Wiring that into the
add or preload path (call PlaybackInfo once the torrent is warm, or run
ffprobe against the fresh CDN URL and write the result into the `.nfo`)
is a genuinely useful, medium-sized change: a day or two once the priming
call is written, touching `catbox.py` (the preload/materialize path),
`strm_generator.py` (`_write_nfo`), and a small new cache of per-release
probe results so a second episode of the same release does not re-probe.

**qBittorrent-compatible API for arr tools (different by design).**
Mycelium's mirror-plus-stub approach already gets Radarr and Sonarr to
show a title as owned, with search off, without a download client at all.
Building a real qBittorrent shim would mean emulating torrent states,
categories and a client Radarr/Sonarr can actually grab through, which is
a much bigger surface (likely one to two weeks) for a benefit this
install does not need: Mycelium's own Discover/Requests UI is already the
add path, and Seerr/Maintainerr only need the arrs to know a title exists,
which the current mirror already gives them. Not worth it at this scale.

**Removal after playback vs idle release, and staying inside TorBox's
thirty days (different by design).** CatBox's aggressive per-play removal
makes sense for a shared hosting service running many tenants against
TorBox's terms at once. A private VPS with a handful of known users has a
much smaller compliance risk, and Mycelium's default 24-hour idle window
is already comfortably inside the 30-day limit while also letting a user
who stops and resumes an episode within the same day skip a full
re-materialize. Switching to true "remove right after playback ends"
would need a playback-stopped signal Mycelium does not currently consume
(Jellyfin sends this in its webhook plugin, but Mycelium's webhook only
reads Radarr/Sonarr/Jellyfin delete events today), handling for
simultaneous viewers of the same token, and would make quick re-plays
slower. Effort: a few days across `catbox.py` (a new removal path keyed
on a playback-stop event, separate from `release_idle`) and the webhook
handler. Low priority; the idle timer already does the job it needs to.

**Optional uncached-fetch toggle (missing).** Mycelium's whole release
pipeline is built around cache-first search; letting the catbox path add
an uncached release on request would spend TorBox's 60-per-hour uncached
budget on a guess that might not even finish downloading soon, which cuts
against the reason CATBOX_MODE exists. Exposing the already-supported
`torbox.add_magnet(cached=False)` behind a setting is a few hours of
work, but there is no real user need behind it for this deployment.

**Self-hosted Torznab indexer endpoint (missing).** Would let an external
tool such as Prowlarr search what Mycelium already has materialized.
Building and maintaining a small Torznab server (feed shape, categories,
a caps XML) is a few days' work, but a four-to-six-user Jellyfin install
already has Mycelium's own UI as the single front door; nothing else in
the stack currently wants to search through it. Low priority.

**Multi-arr support for Lidarr, Readarr, Prowlarr (missing).** Out of
scope, not a gap. Mycelium's metadata (TMDB), scraping and `.strm` layout
are all video-specific; adding music or book support would be a second
product built alongside this one, likely weeks of work, not a comparison
gap worth closing.

**Multi-debrid (flagged as a candidate, turns out inverted).** ElfHosted's
own documentation describes one TorBox account per tenant, or a one-way
migration from RealDebrid to TorBox, never both accounts working
together. Mycelium already has a TorBox account pool (0.29.0) and an
optional RealDebrid fallback used inside the same `materialize()` call.
There is nothing to build here; Mycelium is ahead of what CatBox's own
docs claim on this specific axis.

## 5. Where Mycelium's docs and code disagree

**The redirect chain.** `catbox.py`'s own module docstring says playback
"fetches a fresh CDN URL, and 307-redirects the client" straight to it.
The README's Catbox sequence diagram shows the same thing: a direct
307 from Mycelium to the TorBox CDN. Neither matches the code: `app.py`'s
`stream_redirect` route (`GET /stream/<token>`) issues a 302, not a 307,
and it redirects to `/spore-stream/<token>`, not to the CDN. The
`spore-stream` Go front then either proxies the bytes itself (MP4, via
the moov-first cache) or 302s a second time to a live-checked CDN URL
(MKV and other non-MP4). `egress_estimate.py`'s own docstring and
CLAUDE.md both describe this correctly (a 302 through the Go front). This
looks like doc drift, not an intended contradiction: the two-hop
`spore-stream` architecture was added after `catbox.py`'s docstring and
the README diagram were written, and neither was updated to mention it.
Harmless (nothing depends on the docstring), but worth a one-line fix
whenever that file is next touched.

**"Fetches a fresh CDN URL on every play."** The README's Catbox-vs-Fixed
FAQ entry says exactly that. In the code, a resolved CDN URL is cached
in-memory per token for up to 2.5 hours (`_URL_CACHE_TTL_SEC`) precisely
to avoid re-fetching on every play within that window, since TorBox's own
download links stay open about 3 hours. The FAQ answer is a readable
simplification, not wrong in effect (a URL never goes stale for the
reader), and looks like an intended simplification for a short FAQ
answer rather than a bug.

## 6. Recommendation

1. Prime Jellyfin's probe (via `PlaybackInfo`) or a stored ffprobe result once a release is warm, so codecs, languages and subtitles show before the first play; this is the one gap users will actually notice.
2. Persist that probe result per release (not per token) so a season pack or an upgrade does not re-probe every episode.
3. Fix the stale redirect description in `catbox.py`'s module docstring and the README's Catbox sequence diagram to match the real `/stream` to 302 `/spore-stream` chain.
4. Leave removal timing as the idle sweep; it already sits well inside TorBox's 30-day limit for this deployment's size, and an event-based removal would add real complexity for a smaller UX win here than it gives a multi-tenant host.
5. Skip the qBittorrent-compatible API, the self-hosted Torznab endpoint and Lidarr/Readarr/Prowlarr support unless a specific user need shows up; each is real effort for a benefit this deployment does not currently need.
6. No action needed on multi-debrid: Mycelium's TorBox pool and RealDebrid fallback already exceed what CatBox's own documentation describes.
