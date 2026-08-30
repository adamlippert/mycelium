# Changelog

All notable changes to Mycelium are documented in this file.

## [0.7.6] - 2026-08-30

### Fixed

- **The NFO title repair never repaired anything.** `repair_tvshow_titles()` guarded with `if not title_el`, but an ElementTree Element's truth value is its *child count*, not whether the find succeeded. `<title>Season 01</title>` has no child elements, so the guard was true for every file and the loop skipped all of them; the function returned `{"fixed": 0}` regardless of what the library contained. Python emits a `DeprecationWarning` about precisely this. `is None` is the correct check. This means the repair has never worked in any version, which is also why the underlying "Season 01" bug survived long enough to be worked around twice.
- **The repair now covers movies as well as series.** The write bug could not reach them - a movie's NFO sits in the movie's own folder, so `_write_nfo` derived its title from the right directory, and a test pins that - but a repair that inspects only half the library cannot report the other half is clean. A movie is rewritten as a `<movie>` document keeping its `<year>`, never as a `<tvshow>`, which would break Jellyfin matching. The Maintenance button is relabelled "Fix library titles" accordingly.

## [0.7.5] - 2026-08-30

### Fixed

- **The retry queue never drained.** Three separate paths let it grow without limit. `processor.process()` re-queued on a mutex miss by calling `db.enqueue_retry` directly instead of going through `retry_queue`, which skipped `schedule()`'s give-up check and passed the attempt count unchanged rather than `+1` - so a title that kept colliding re-queued every 60 seconds indefinitely with its progress toward being abandoned frozen at zero. `run_due()` bails when the TorBox createtorrent budget is nearly spent, leaving rows due but unprocessed, and a row that is never processed never increments its attempt either, so under sustained budget pressure the queue only grew. And `retry_queue` had no `UNIQUE` on `imdb_id` and appeared in no prune target, so a single title could hold many rows and nothing ever removed them. Observed on a live instance as 8 rows for 2 titles, 7 of them the same title - more than `schedule()` alone can produce, which is the signature of the collision path specifically.
- A mutex miss now goes through `requeue_after_collision()`, capped at `MAX_COLLISION_REQUEUES` and deliberately not raising `attempt`, because a scheduling collision is not a failed attempt. The count is held in memory rather than on the row: the row is deleted the moment the retry fires, so a column would reset every cycle and never reach the cap, and the locks it guards are in-process too, so a restart legitimately clears both.
- `enqueue_retry()` is now an upsert against a unique `imdb_id`, taking `MAX(attempt)` so a collision re-queue cannot reset a title's progress. The migration collapses existing duplicates first, keeping the furthest-along attempt, since the unique index cannot be created while duplicates exist and a failed migration means the container does not boot.
- Rows older than a week are pruned twice daily.

### Added

- **A "Clear retry queue" button** in Maintenance. The dashboard already displayed the pending retries but offered no way to act on them.

## [0.7.4] - 2026-08-30

### Fixed

- **Mycelium imported the entire TorBox account unprompted.** `strm_generator.run_once()` in non-catbox mode walked the whole TorBox mylist and wrote a `.strm` for every torrent in it. That is what the "Import TorBox library" button is for, but it also ran on a timer every hour (`STRM_GENERATOR_INTERVAL_HOURS` defaults to 1) and again 30 seconds after every boot, so an account holding content from before Mycelium was installed, or added elsewhere, grew a library nobody asked for. Worse, `process_torrent()` recorded nothing: no request row, and in fixed mode no `virtual_items` row either, so the result played in Jellyfin but appeared in neither the Requests nor the Library tab and could not be removed. `run_once()` and `run_and_refresh()` now take `import_unknown`, and the two unattended call sites pass `False`; deliberate triggers (the button, the TorBox push webhook, post-add, cleanup, recovery) are unchanged. This does not affect fixed-mode URL freshness: `_write_strm()` returns early when the path exists, so the hourly run never refreshed an expiring CDN URL - importing was its only effect. `process_torrent()` also now records a request row for what it materialises when the caller knows the imdb_id, filling a gap without disturbing a request the processor already owns.
- **Every series was named "Season 01" in Jellyfin.** `_write_nfo()` derived the title from `strm_path.parent.name`. For a movie that is the movie's own folder and correct; for an episode it is the SEASON folder, and `tvshow.nfo` is written from an episode path, so every series got `<title>Season 01</title>` and Jellyfin displayed exactly that. The title now comes from the folder the NFO itself sits in. This had been worked around twice without being fixed - `repair_tvshow_titles()` rewrites the bad files afterwards, and `generate_missing_nfos()` refuses to write a "Season XX" string - but neither ran at write time, so every newly added series reproduced it. Existing files are untouched; the new button below repairs them.
- **The retired filter settings were still editable in the admin UI.** 0.7.0 replaced the twelve booleans with the rule model and nothing reads the old keys, but `SETTING_GROUPS` kept listing `QUALITY_PREFERENCE`, `ALLOW_4K`, `EXCLUDE_REMUX`, `EXCLUDE_BLURAY`, `EXCLUDE_CAM`, `PREFER_WEBDL`, `PREFER_HEVC`, `STRICT_NO_CAM`, `AUDIO_LANGUAGE_PREFERENCE` and `EXCLUDE_LANGUAGES`. Toggling one saved a value no code path consults, which reads as a filter being in force when it is not. Both affected groups are renamed to what they now hold: "Quality & filtering" becomes "Size & seeders", "Languages & subtitles" becomes "Subtitles". A test ties the settings page to `migrate_filters.RETIRED` so this cannot drift again.

### Added

- **A "Fix series titles" button** in Maintenance. `repair_tvshow_titles()` and its endpoint already existed but nothing linked to them, so the only way to repair a library full of shows named "Season 01" was to call the URL by hand. A second test walks every literal `/ui/` URL the admin page fetches and asserts `app.py` defines it, so a renamed route fails the suite rather than leaving a button that breaks only when clicked.

## [0.7.3] - 2026-08-30

### Fixed

- **"Remove from library" left the title on screen.** The purge deleted the `.strm` files and their per-episode `.nfo`, and nothing else - but `nfo_generator` also writes the episode still (`<episode>-thumb.jpg`), `poster.jpg`/`fanart.jpg` in both the season folder and the series root, and `tvshow.nfo` in the series root. All of it survived, with two consequences: the folders were never empty so the `rmdir` sweep quietly left the whole tree in place, and Jellyfin, scanning a series folder that still held a valid `tvshow.nfo` and artwork, kept the show in the library. From the outside the button looked like it had done nothing, even though every `.strm` was already gone. The purge now clears those sidecars and removes the folders, deleting only filenames this project writes and skipping any folder that still holds a `.strm`, so a sibling title's files - and anything you put there yourself - keep both their artwork and their directory.
- **A purge could delete the files and never tell Jellyfin.** `jellyfin.refresh_library()` debounces for 60 seconds so that bulk `.strm` generation does not hammer the server, but that also swallowed the refresh for a purge landing shortly after an unrelated one - observed live, 50 seconds after a scheduled refresh. A purge now forces the scan, and both skip paths log at info rather than debug, since the entire effect of a skip is something visibly not happening.
- **`spore-nfs` and `spore-smb` no longer log every refresh.** Each printed `tree refreshed: N files, M dirs` roughly every ten seconds, from two processes, indefinitely - around seventeen thousand identical lines a day. With the compose default of `max-size 10m` / `max-file 5` that rotates real diagnostic history out of the log, and it actively obstructed diagnosing the bug above. Both now log only when the count changes, which also turns the log into a usable record of when the library actually moved.

**Note:** the folder fix applies to future removals. A title purged by an earlier version has already left its artwork behind; those folders contain no `.strm` and can be deleted directly.

## [0.7.2] - 2026-08-30

### Added

- **`PUID` / `PGID` support.** Mycelium writes the `.strm` files that Jellyfin and Plex read and delete. Deleting a file needs write permission on its parent *directory*, so all three have to agree on a user id - and running as root meant Mycelium owned everything it created and Jellyfin could not remove any of it from its web UI. That id is a property of the deployment rather than of the image, so it arrives at runtime through the same two variables Jellyfin and Plex already use, instead of a `USER` line in the Dockerfile. The new entrypoint corrects ownership of the data directories and then drops to `PUID:PGID`. `PUID=0` is the default and execs straight through, so nothing changes for anyone who does not set it.
- The recursive ownership pass is guarded by a marker named `.ownership-<uid>-<gid>`: it runs once, re-runs when the ids change rather than leaving half the tree owned by the old id, and is skipped on every normal restart, where a walk over a large library would otherwise cost minutes on each boot. A chown that fails deliberately does not write the marker, so a broken permission state retries on the next start instead of booting into a database it cannot write. `FORCE_CHOWN=1` repeats the pass on demand.
- Setting `user:` in Compose achieves the same end result, but leaves the operator to fix existing ownership by hand and to remember the setting on every deployment - and a platform that regenerates its Compose file can drop it with no visible symptom beyond new files quietly reverting to root. `PUID`/`PGID` is ordinary configuration, which is the thing such platforms carry correctly.

### Fixed

- **`spore-smb` keeps its port under a non-zero `PUID`.** Port 445 is below 1024 and so normally requires root to bind, which would have silently cost the SMB share to anyone adopting `PUID`. The binary now carries `cap_net_bind_service`, which works at any user id on any host without asking operators to set sysctls or capabilities per deployment. Applied after the `COPY` because capabilities live in the file's extended attributes. Verified not to disturb the default path: the binary still loads normally under the secure-execution mode that file capabilities enable.
- **A dead `spore-nfs` or `spore-smb` is no longer silent.** Both were backgrounded while only gunicorn was `exec`'d, so either could fail at startup or die days later with nothing logged and nothing restarted - the share simply was not there, with no error to search for. Their exits are now reported.

## [0.7.1] - 2026-08-30

### Fixed

- **Deleting a request now actually deletes it.** Delete removed only the `requests` row, leaving behind three things it had created, each of which then poisoned the next request for the same title: the `webhook_events` dedup key (which lives 24h, so re-requesting the title was answered `duplicate` and silently never processed), the `.strm` files and `virtual_items` rows, and the `retry_queue` row (so a deleted request reappeared at the next backoff interval). `db.delete_request()` now clears the dedup keys and queued retries with the row.
- **A re-requested series is no longer marked failed while its episodes sit in the library.** `strm_generator.create_lazy_episode_strm()` returns `False` both when the episode is already registered and when the write genuinely failed, and `processor._lazy_register_season()` treated both as failure. So every season of a re-requested series returned `False`, the request was marked `failed`, and a retry was queued that could never accomplish anything - while Jellyfin and Plex had the whole show. The movie path had been fixed for this already (`_lazy_register_movie`: "strm already exists - still a success"); the series path never was. The new `_already_registered()` asks the database whether the episode has a `virtual_item`, which is the only way to tell "already there" from "write failed" - a disk error is still reported as a failure rather than as a healthy library.

### Added

- **A second "Remove from library" button** beside Delete, in both the classic admin Requests tab and the SPA (admin-only there). Delete keeps its existing meaning: forget the request record, keep the files. Remove from library additionally deletes the `.strm` files, their `.nfo`, the Spore stubs, the `virtual_items` rows and the monitoring rows that would regenerate them, then prunes the emptied folders and refreshes Jellyfin. Folder pruning uses `rmdir` only and never walks above `MEDIA_PATH`, so a directory still holding another title is left exactly as it was.

## [0.7.0] - 2026-08-30

### Changed

- **Release filtering replaced with a four-state rule model.** The twelve boolean filters (`ALLOW_4K`, `EXCLUDE_REMUX`, `EXCLUDE_BLURAY`, `EXCLUDE_CAM`, `STRICT_NO_CAM`, `EXCLUDE_DV_P5`, `PREFER_WEBDL`, `PREFER_HEVC`, `QUALITY_PREFERENCE`, `AUDIO_LANGUAGE_PREFERENCE`, `EXCLUDE_LANGUAGES`, plus the coupling in `EXCLUDE_UNDERSIZED_RELEASES`) are retired in favor of 37 new settings across seven categories - `RESOLUTION`, `SOURCE`, `ENCODE`, `VISUAL_TAG`, `AUDIO_TAG`, `AUDIO_CHANNELS`, `LANGUAGE` - each with its own `_PREFERRED`, `_EXCLUDED`, `_REQUIRED`, `_INCLUDED` and `_STRICT` setting, plus `SORT_ORDER` and the internal `FILTER_RULES_MIGRATED` marker. `preferred` is tie-break only and never rescues a candidate another rule dropped; `included` overrides every other rule in every category, including a `_REQUIRED`/`_EXCLUDED` rule on an unrelated category, so it is the one setting a user can seriously surprise themselves with.
- **Evaluation is order-independent.** Every category now votes against the full candidate pool independently, and the drops are unioned afterwards, instead of the old sequential chain where each filter reshaped the pool before the next one ran. Soft relaxation (falling back rather than emptying the pool) is assessed globally across all non-strict categories together, not per category, so two categories that each drop a different half of the pool are caught even though neither one alone would have emptied it.
- **Every drop now carries a reason.** `filter_rules.evaluate()` returns a `Verdict` per candidate (kept/dropped, which rule, which value, whether that rule self-relaxed), replacing the old silent list-shrinking. `streams.rank_streams_explained()` exposes this; `rank_streams()` keeps its old signature for existing call sites.
- **`EXCLUDE_LANGUAGES` loses its undocumented rescue.** The retired filter never dropped a candidate that also matched `AUDIO_LANGUAGE_PREFERENCE` or `multi`, even if it also matched an excluded language - so a release tagged both "ru" and "en" survived `EXCLUDE_LANGUAGES=ru`. `LANGUAGE_EXCLUDED` has no such exception: it drops on a match, full stop. This is an intentional behaviour change; use `LANGUAGE_INCLUDED` if you want a deliberate rescue instead.
- **Dolby Vision detection now recognises a trailing `.DV` marker.** The retired regex was `\b(dovi|dolby[\s.]?vision|\.dv\.)\b`, which required a bare `dv` to have dots on both sides and so missed a release name ending `...x264.DV`. The new detector's pattern is `\b(dovi|dolby[\s.]?vision|dv)\b`, which catches it. With `EXCLUDE_DV_P5` on (the default) this now drops some releases as `dv_only` that previously passed. That is intended, not a regression: the setting exists to keep Dolby Vision profile 5 (no HDR10 fallback layer) off clients that render it washed out, and the old pattern was simply missing cases it should have caught.
- Fixed the `bluray`/`remux` overlap: the retired `EXCLUDE_BLURAY` regex matched `BluRay.REMUX` releases too, so setting it could silently drop remuxes that `EXCLUDE_REMUX` was never asked to touch. `release_tags.detect_sources()` is mutually exclusive (most-specific pattern wins), so a BluRay remux is tagged `remux`, never both.
- `STRICT_NO_CAM` is decoupled from the undersized-release size check it used to also govern, unrelated to cam rips. The size check now has its own `EXCLUDE_UNDERSIZED_STRICT` toggle; `STRICT_NO_CAM` migrates to `SOURCE_STRICT`.
- `SORT_ORDER` is now configurable (ten criteria: `season_pack`, `resolution`, `cached`, `language`, `source`, `encode`, `visual_tag`, `audio_tag`, `seeders`, `size`), replacing a hardcoded seven-term tuple. The default reproduces the old order exactly.
- **Naming fix:** `QUALITY_PREFERENCE` held a resolution (1080p/2160p/720p) despite its name. The new `RESOLUTION_PREFERRED` (and the rest of the `RESOLUTION_*` family) name it correctly - if you hand-write a `.env`, `QUALITY_PREFERENCE=1080p,2160p` becomes `RESOLUTION_PREFERRED=1080p,2160p`, not a `QUALITY_*` key.
- The retired settings are translated into the new rule rows automatically, once, at startup, guarded by `FILTER_RULES_MIGRATED` - a later startup never re-reads them and clobbers an edit made since in the admin UI. A retired key still present in `.env` after migration is reported (not silently ignored) via a startup warning naming the key and its replacement.
- **The settings page renders the rule editor as seven category panels with per-value chips,** replacing 35 comma-separated text boxes and dropdown-selected lists. Each category's vocabulary is offered as a dropdown picker, so an invalid value cannot be typed. A value stored from `.env` that is not in the vocabulary is now surfaced in the UI struck through with an explanation; previously it warned once at container startup and was then invisible while matching nothing. `preferred` is the only state offering reorder controls, because order only changes behaviour in that state; `included` carries a permanent warning that it overrides every other rule in every category. The editor writes the same settings as before - `setting_<KEY>` hidden inputs on save - so `.env` values and the API remain unaffected.

### Fixed

- **The OIDC toggle in the admin UI now takes effect.** `oidc.is_enabled()` read `config.OIDC_ENABLED`, a snapshot taken from `.env` at startup, so switching OIDC on or off in Settings saved the value and changed nothing; only editing `.env` and restarting worked. It now reads the live settings overlay, falling back to `.env`. `OIDC_ENABLED` is also registered as a boolean setting: without that, storing `false` wrote the string `"false"`, which is truthy, so switching OIDC off would have left it on. A half-working toggle is worse than one that plainly does nothing, so both halves are needed.

## [0.6.6] - 2026-08-29

### Fixed

- Debridio results were being systematically outranked on a criterion they could not win. Debridio ships language information as flag emoji in the stream title, but `debridio.py` never populated `Stream.languages`, so every Debridio result arrived with an empty language set. Language is the third term of the ranking tuple - above WEB-DL, HEVC, seeders and size - and an empty set scores worst-but-one, so for anyone who had set `AUDIO_LANGUAGE_PREFERENCE` (it ships empty by default, so a default install saw no effect from this bug at all) a Debridio release lost to any Torrentio release whose name happened to spell out "ENGLISH", regardless of which was the better file. Debridio is queried first, so this quietly suppressed the scraper that was supposed to lead. Detection now lives in one place, `streams.detect_languages()`, reads flag emoji as well as name tokens, and is used by all three scrapers.
- **This can move a release down as well as up.** A release flagged only French and German previously scored as "unknown"; now it correctly scores below a release in a preferred language, and below an untagged one. That is the intended behaviour - we know more than we did - but a picked release changing after upgrade is expected rather than a fault.
- The detectable language vocabulary grows from four codes (`nl`, `en`, `multi`, `ru`) to 34, so `AUDIO_LANGUAGE_PREFERENCE` and `EXCLUDE_LANGUAGES` can now name languages that were previously undetectable. Both settings are validated when saved: an unknown code such as `english` is rejected with the valid codes listed, where before it was accepted silently and simply never matched. Values arriving from `.env` bypass that check and warn at startup instead.
- Zilean carries no language data of any kind. That is now explicit (`zilean.LANGUAGES_AVAILABLE`) rather than an accident of an empty field, and an empty language set is documented as meaning "the release did not say", never "this release has no audio" - untagged English is the default in release naming, so anything treating absence as a positive fact would discard most of the catalogue.

## [0.6.5] - 2026-08-29

### Added

- **Debridio** joins Zilean and Torrentio as a third scraper, and is queried first when enabled. It is a paid Stremio-protocol addon, so unlike the other two it needs credentials: `DEBRIDIO_API_KEY` must be your *Debridio account* key, not a debrid provider key - Debridio is a search addon that proxies through a provider, and the provider key it proxies with is your existing `TORBOX_API_KEY`, which Mycelium reuses automatically. Both are required; with either missing the scraper reports itself unconfigured and stays out of rotation entirely rather than failing per request. Its stream objects carry no `infoHash` field, so the hash is recovered from `behaviorHints.bingeGroup` with the play-URL path as a fallback - verified consistent across 702 of 702 streams, 88 of which matched Torrentio's hashes for the same title verbatim. The addon's config segment is base64 JSON holding **both** API keys, which makes the request URL itself a secret: every log line, health payload and exception message that could carry it passes through `debridio.redact()` first.
- The Debridio config is deliberately permissive - every resolution, no excluded qualities, no size cap - rather than mirroring Mycelium's own filter settings down into it. The two filter models are not the same kind: Mycelium's filters are soft and self-disabling (`EXCLUDE_REMUX` drops remuxes only while something else survives, then logs "only remux candidates available; allowing them" and takes them anyway), while Debridio's are hard. Pushing ours down would delete streams upstream that `rank_streams` would have chosen to allow, and the fallback that exists precisely for the thin-pickings case would never fire. Filtering stays in one place, at ranking time, with the full pool visible.
- A **`source_unique_win`** metric alongside the existing `source_win`. Win rate on its own overstates whichever scraper sits first in the priority order: the three scrapers overlap heavily, so a source can win nearly every race while contributing almost nothing that the others would not have found a moment later. `source_unique_win` counts only the wins where no other scraper returned that hash at all, which is the number that actually answers "is this source worth querying". The merge records the overlap in `also_seen_in` as it dedupes, so both metrics come from the same pass.

### Fixed

- Candidate discovery is now a single `scrapers.fetch_candidates()` orchestrator instead of nine hand-rolled call sites that had drifted into three different orchestration patterns - some queried Zilean and Torrentio sequentially, some concurrently, some checked health first and some did not, and the dedup rules differed. All three scrapers are now queried concurrently and merged in *priority* order rather than completion order, so which source keeps a duplicated hash is deterministic instead of a race. The shared stream model, parsing helpers and ranking moved out of `torrentio.py` into `streams.py`; they were never Torrentio-specific, they just lived there.
- A transient scraper outage could delete the library. Because the orchestrator catches every scraper exception and returns an empty list, cleanup's repair pass read a total upstream outage as "this title no longer exists anywhere" and unlinked the `.strm`, its `.nfo` and the database row, then marked the title unfixable for 24 hours. Ten minutes of Torrentio 502s with the other two scrapers off was enough to take out every already-broken title in one run. Callers that destroy something on an empty result now opt into `ScrapersUnavailable`, which separates "searched and found nothing" from "could not search at all"; the same confusion was putting web playback into a six-hour backoff that outlived the outage by hours.
- A lapsed Debridio subscription reported itself healthy. Both health probes treated any status below 500 as up, but Debridio is the only scraper that authenticates: 401/403 for an expired subscription and 404 for a garbled config token all sailed through, so the admin Health card showed ok and every search kept paying a pointless round trip instead of falling through to the other scrapers.
- With `LOG_LEVEL=DEBUG`, urllib3 logged each request's full path - for Debridio, the base64 config segment holding both API keys - into the log buffer and the admin Logs tab. It logs below every redaction call site, so nothing in Mycelium's own code could have caught it; the urllib3 logger is now pinned at WARNING regardless of log level.
- The web player never saw Debridio: it still queried Zilean and Torrentio directly, because it deliberately does not want the house ranking (it orders by browser compatibility instead). It now shares the orchestrator's fetch, merge and dedup and applies its own scoring to the result.
- The dashboard's Quality card split unrecognised qualities across two labels, because the shared parser called them `""` and Torrentio's called them `"unknown"`.
- The outage guard above almost never fired. It counted a scraper as failed only when its adapter raised, but Debridio and Zilean both document "never raises, returns `[]` on failure" - only Torrentio propagates. With all three active, at most one could ever count as failed, so `failed == len(active)` could never be true and a real all-scrapers-down outage still read as "searched, found nothing". Debridio and Zilean now take a `raise_on_error` flag that `scrapers.py` sets so their failures are counted too, and the guard itself is now "something failed AND nothing was found" - evaluated after the merge, so a partial failure that still turned up candidates proceeds normally instead of blocking a legitimate repair. The flag defaults to `False` everywhere else, so both adapters' documented never-raises contract is unchanged for other callers.
- Catbox's per-title search cache stored the outage sentinel for 6 hours instead of not caching it. `_search_cached_release` only shortened the TTL for a truthy result, so the sentinel fell through to the same 6-hour "nothing cached" backoff as a real miss - the token's own retry cooldown was the intended 30s, but the title itself would not be re-searched again until long after any real outage had ended. The sentinel is no longer written to the cache at all; the next request re-searches.

## [0.6.4] - 2026-08-29

### Fixed

- Catch-up requests were recorded under their raw IMDB id (`tt2017109` instead of the actual title), which then propagated into the library folder name on disk. Seerr's `Media` entity has no title column - it carries only `mediaType`, `tmdbId`, `tvdbId`, `imdbId` and `status` - so `media.get("title")` in `catchup._build_request` was always `None` and the raw id fallback fired every time. Titles now resolve through `tmdb.display_title()`, the same fallback `webhook_parser` uses for a payload with no subject. This was always broken but only surfaced at scale in 0.6.3: while the webhook was rejecting requests for want of an IMDB id, approved requests piled up unprocessed in Seerr, and the first restart after that fix let catch-up replay the whole backlog at once. **Existing rows and folders can be repaired with the "Fix IMDB titles" button in Admin > Maintenance**, which renames on disk and updates the database and strm paths.

### Internal

- `test_strm_generator` swapped mocks into `sys.modules` and then imported `strm_generator`, which is silently order-dependent: if any earlier test module had already imported `strm_generator` for real, the swap bound nothing and every test relying on a mocked `settings`/`db` ran against the real module instead - failing on an unrelated assertion with no indication why. Dependencies are now patched as module attributes in an autouse fixture, so the file passes regardless of import order, and the mocks are function-scoped so direct assignments no longer leak between tests.

## [0.6.3] - 2026-08-28

### Fixed

- Seerr/Jellyseerr requests were intermittently rejected with `400 No IMDB id found in webhook payload or Seerr API`, most often for TV and anime. Three things combined to make this the common case rather than an edge case: Seerr's shipped default webhook template emits only `media_type`/`tmdbId`/`tvdbId`/`status` and has no `{{media_imdbid}}`, so no id ever arrives in the payload; Seerr creates its own `Media` row without an `imdbId`, and only ever backfills one for movies its Jellyfin scanner has already found on disk (never for TV); and the TMDB fallback that should have covered both was called from *inside* the Seerr API branch, so any failure of that round-trip - unreachable, 404, 401, or a payload with no `request_id` - skipped it entirely, despite the `tmdbId` sitting in the payload the whole time. The fallback is now hoisted out of that branch and runs off whichever `tmdbId` is available, choosing TMDB's movie or tv `external_ids` endpoint from the payload's own `media_type`. Requires `TMDB_API_KEY` to be a v4 Read Access Token (the long `ey...` string) - the API is called with bearer auth, so a v3 key returns 401 on every call and resolution silently fails.
- The webhook handler no longer contacts Seerr at all when `SEERR_URL` is unset - it previously made a guaranteed-to-fail request and logged a misleading `Seerr API lookup failed` warning on every single request.
- A webhook template rendering an unsubstituted `{{media_tmdbid}}` raised `ValueError` out of `int()`, which is not a `WebhookError` and so escaped as an HTTP 500 with a traceback instead of a clean 400.
- The "no IMDB id" error now names the subject, the `tmdb_id` it tried, and whether `TMDB_API_KEY` is set at all, instead of reporting the same opaque string for four unrelated causes.

## [0.6.2] - 2026-07-11

### Added

- **spore-nfs** and **spore-smb**: read-only NFSv3 and SMB2/3 servers exposing the virtual library as real files, backed by the existing `/spore-stream/<token>` endpoint (no new materialization logic). Server-side tricks to block Direct Play on Shield/Android TV (stub channel count, forced PGS subtitle burn-in) stopped working reliably - Android's local-network fast path bypasses the profile negotiation Linux/desktop clients respect, turning the fake stub into a black screen instead of a transcode. With real size/bytes served, Direct Play becomes correct instead of catastrophic, on every client. Both protocols share a 3-window read-ahead LRU, background prefetch, resolved-CDN-URL caching, self-healing on a dead cached URL, and a token-bucket rate limiter with retry/backoff against TorBox/CDN 429s. spore-nfs later merged into the main image (one container instead of two).

### Fixed

- MKV/non-MP4 playback via `/stream` (Jellyfin's path, and any other client not building a moov-first cache) could be redirected straight to a CDN URL that had gone dead earlier than its 23h in-memory cache TTL, with no validation - Jellyfin/ffmpeg would follow the dead link into a TorBox error page and fail with `FFmpegException: FFmpeg exited with code 8` / `ffprobe failed`. Now HEAD-checked before redirecting, with an automatic re-resolve on a dead link.
- `play_count`/`last_played` were written to SQLite on every single byte-range request during playback, not just on play start - under concurrent playback these writes serialized against each other for no benefit. Debounced to once per token per 60s; the CDN liveness check above is similarly cached for 120s so repeated seeks in one session don't each pay a fresh CDN round trip.
- Stale `JELLYFIN_API_KEY` on deploy could leave `refresh_library()`, `merge_duplicate_versions()`, `refresh_missing_images()` and continue-watching sync silently failing with 401 - not a code fix, but worth a mention since it was masking as playback flakiness.

## [0.6.1] - 2026-07-05

A security- and correctness-focused release from a full multi-pass code review. No new features.

### Security

- OIDC and trusted-proxy logins no longer implicitly become admin - `auth.py` now resolves or creates a real per-user role (`user` by default; only the very first user ever provisioned this way becomes admin, and only during initial, incomplete setup)
- `AUTH_SESSION_SECRET` is no longer used to sign sessions when left at the well-known default value - a random secret is generated and persisted instead, same pattern as the existing `WEBHOOK_SECRET_AUTO`
- Added `is_admin()` checks to roughly 30 previously-unprotected `/ui/*` and `/ui/api/*` routes: settings save/reset, backup restore, DB vacuum/prune, cleanup/repair/migrate triggers, Zilean sync/import, wanted-recheck, NFO/strm regeneration, and several legacy `/api/*` aliases that had slipped through
- `/admin` itself now redirects non-admin users to login instead of only checking that setup is complete
- Web Player `/stream/<token>/*` playback routes now require an authenticated session with the Web Player feature enabled - previously reachable by anyone who obtained a token
- `TRUSTED_PROXY_NETWORKS` default narrowed from broad private-IP ranges to loopback only
- Webhook secret and internal token comparisons now use constant-time comparison throughout
- The Spore TCP server (port 8089, unauthenticated protocol) now binds to loopback by default instead of all interfaces

### Fixed

- A transient scraper/cache-check error on a single episode could mark an entire multi-season request "failed", discarding seasons that had already been added successfully
- The retry queue could silently drop a failed retry and abort the rest of that cycle's batch instead of continuing
- Cleanup/repair and canonical-name migration could leave orphaned database rows behind after deleting or merging `.strm` files, permanently blocking recreation of that title
- Folder rename/merge database updates could corrupt a sibling folder's paths when one folder name was a literal prefix of another (e.g. "Alien (1979)" vs. "Alien (1979) Directors Cut")
- Duplicate-folder merges could silently delete a file that was never actually copied over first
- Plex's fast-start MP4 cache could corrupt sample offsets for CDN files with a second data block after the `moov` atom (dual-mdat layout)
- HTTP suffix byte-ranges (`bytes=-N`) were parsed as the first N bytes instead of the last N
- CSRF protection was effectively disabled on roughly 27 internal API routes because the exemption predated the frontend actually sending the CSRF token
- Several background jobs (series monitor, retry queue) could abort an entire batch when a single item raised an unexpected error instead of continuing with the rest
- Assorted smaller fixes: SQLite `LIKE` wildcard characters in folder names could cause wrong-path matches during renames; a webplayer seek race could start two concurrent FFmpeg processes for the same session; two `/api/*` routes referenced an unimported module and would have raised on use

## [0.6.0] - 2026-07-04

### Credits

Several of the bugfixes in this release were discovered and/or confirmed through the work of [Ventrex](https://github.com/Ventrex/mycelium) in his fork ("VenFlix") and the accompanying [GitHub Discussions](https://github.com/corveck79/mycelium/discussions). Thanks for digging into these issues and sharing the fixes/ideas with the community.

Thanks also to [Damosso](https://github.com/Damosso) for the Seerr webhook secret tip in [#41](https://github.com/corveck79/mycelium/issues/41), which shaped a docs fix earlier in this cycle.

### Added

- **Trakt**: auto-request new watchlist items for download (not just watchlist sync), capped daily, built into the existing Trakt plugin
- **MDBList integration**: connect your own API key, pick lists to sync, capped auto-request
- **Auto-approve**: per-genre rules with year ranges, follow favorite actors (auto-requests their filmography, excludes talk shows/soaps), shared daily budget
- **Discover genre tabs**: admin-configurable browse rows per genre + year range
- **Language filter**: per-user include/exclude of content by original language in Discover
- **Clickable cast**: cast in the detail modal opens an actor page with bio + filmography + Follow button
- **TorBox library scan**: reads existing TorBox cache and creates `.strm` files for anything missing (e.g. after a DB reset)
- **Notification settings** in the React Settings page (Discord/Telegram)
- **Real topbar search bar** instead of just a link to the search page
- **React Admin dashboard finally routed**: `/admin` now shows a tab between the new dashboard (user management, Radarr/Sonarr import, Auto-approve, genre tabs, maintenance) and the existing Jinja page - this page already existed but was never wired to a route

### Fixed

- Settings-UI overrides were silently ignored in several places (Zilean, TMDB, RealDebrid, TorBox, OpenSubtitles, catbox) due to frozen `config.py` imports instead of `settings.get()`
- Mislabeled cams/trailers (e.g. "2160p" that's actually a cam) are now rejected based on physically plausible file size vs. TMDB runtime
- Unreleased titles could pull in fake/cam releases - now blocked via TMDB release date
- Multi-season series only got season 1 into the library
- Duplicate episode tokens/strms when title sanitizing landed differently
- `db.insert_request()` could update the wrong row on retry (SQLite `lastrowid` quirk), leaving requests permanently stuck on "rate_limited"
- TorBox timeouts were treated as success, writing a `.strm` before the torrent was actually ready
- Series could end up split across multiple folders due to varying release names
- Jellyfin library refresh had no debounce, could fire excessively during bulk operations
- Raw IMDb IDs (`tt1234567`) instead of titles shown in notifications/UI for requests without a title in the payload
- Toggle switches in the admin user panel rendered incorrectly (knob always on the right regardless of state)
- Clickable cast was invisible due to a z-index conflict between the detail and actor modals
- Removed a duplicate, colliding Trakt integration (a new build on top of an already-existing plugin) - including a database schema conflict that broke the existing plugin
- Web Player: `/ui/api/web-player/status/<job_id>` silently dropped `token`/`stream_type` from its JSON response, so the frontend always fell into the HLS.js branch (pointed at a raw MP4 redirect instead of a playlist) instead of direct-playing eligible files, causing an infinite retry/timeout loop

## [0.5.2] - 2026-06-12

### Added

- **Web Player VA-API**: hardware-accelerated HEVC transcoding via VA-API (`renderD128`); reduces CPU usage significantly on supported hardware
- **Web Player HEVC-always**: HEVC is always transcoded to HLS regardless of codec; direct serve only for H264 to avoid browser incompatibility
- Docker Compose: `videodriver` GID 937 added for VA-API `renderD128` access
- **Spore wrapper EAE detection**: also detects EAE need from output encoder args (e.g. Shield TV requesting `eac3_eae` output via eARC); skips injecting native decoder hint when output is `copy` to prevent EAE init failures on HTTP input

### Fixed

**Web Player**
- Black screen / corrupt green output on 10-bit HEVC with VA-API (Apollo Lake J3455)
- `scale_vaapi` failure on 10-bit HEVC sources
- Stale segments causing black screen after seek or restart
- Missing `/direct`, `/convert-hls`, `/hls-status` routes
- HLS buffer increased to prevent stalls on slow CDN
- Temp directory leak when HLS conversion crashes before session registration
- `ffmpeg.log` file handle not closed on `Popen` failure
- `shutil.rmtree` called before ffmpeg process exits (race condition)

**Security**
- Session fixation: `session.clear()` now called before writing new session keys on login
- `/torbox-webhook` and `/ui/api/repair-strms` now require authentication
- `/setup/save` now validates against a known-key allowlist (previously accepted arbitrary keys)
- `/health` no longer leaks internal exception details in the response body

**Data integrity**
- `cleanup.py`: new strm written via `process_torrent` before the old one is deleted
- `upgrader.py`: season-pack strms written before per-episode strms are removed
- `mp4_faststart.py`: `.fsh` cache written atomically via temp-file + rename; ftyp box fetched at actual size instead of hardcoded 64 bytes

**Logic**
- `torbox.py`: `metaDL_done` state never matched because `download_state` is lowercased before comparison — fixed to `metadl_done`
- `torbox.py`: createtorrent quota now recorded after HTTP success, not before (prevented quota inflation on network errors)
- `torrentio.py`: season-pack regex `s0?N` → `s0*N(?!\d)` to correctly match zero-padded season codes
- `catbox.py`: `release_idle()` no longer aborts on first network error — each torrent deletion is now wrapped in try/except
- `monitor.py`: aired episodes without a strm are now marked `wanted` in the DB (were silently left without status)
- `retry_queue.py`: startup crash on undefined `_CREATETORRENT_LIMIT` constant (should be `_CREATETORRENT_LIMIT_HOUR`)
- `db.py`: `_migrate()` ALTER TABLE loop now catches per-column errors instead of aborting remaining migrations

**Fresh install**
- Fixed crash `sqlite3.OperationalError: no such table: settings` on first boot when the DB is empty ([#34](https://github.com/corveck79/mycelium/issues/34))

---

## [0.5.1-dev] - 2026-05-29

### Added

- **Library poster grid**: movies tab now shows a paginated poster grid (24/page) with the same look as Discover and Watchlist
- **Library search and filters**: search box and All / Available / Wanted filter tabs in the movies view
- **Open in Jellyfin preference**: per-user toggle in Settings > Preferences; clicking a library poster opens the item directly in Jellyfin web instead of the detail modal
- **Jellyfin batch lookup**: Jellyfin item IDs are pre-fetched in one call so poster clicks are synchronous (no popup-blocker issues)
- **Lazy poster loading**: posters missing from the local cache are fetched on first render without blocking the page

### Fixed

- GitHub Actions arm64 build crash: removed dead `spore-builder` Dockerfile stage that compiled a C LD_PRELOAD library using `stat64`/`__xstat64` which do not exist on aarch64
- Jellyfin click mode not working after toggle: Settings now uses an optimistic session-cache update so Library reacts instantly without a page reload
- Detail modal not opening for older items that lack a stored `tmdb_id` (now resolved via `/ui/api/tmdb/find`)

---

## [0.5.0-dev] - 2026-05-28

### Added

- **Mycelium Spore** (experimental Plex integration): stream via stub MKV library + transcoder wrapper, no rclone or local storage required
- **Spore fast-start cache**: moov-first MP4 cache (`.fsh` files) built on first play so subsequent plays are instant
- **Spore track persistence**: audio/subtitle tracks and duration saved to DB after first ffprobe; stubs are regenerated with real tracks on container restart
- **Spore CDN preload**: fast-start cache and ffprobe run automatically when a CDN URL is first resolved, so first play is instant even before user interaction

### Fixed

- TorBox outage no longer causes a 6-hour retry delay for affected items
- HDR10+ no longer treated as a valid HDR10 fallback in the Dolby Vision P5 filter
- Bulk rename for items stored with raw IMDB codes as title (Admin > Maintenance > Fix IMDB titles)
- HEVC compatibility fix in the webplayer plugin for browser playback

---

## [0.4.2] - 2026-05-25

### Added

- `WEBHOOK_SECRET` auto-generation with copy button in admin Settings
- Metrics endpoint secured with optional Bearer token
- Rate limiting on authentication endpoints

### Fixed

- Setup wizard now closes after first run (re-open via Settings)
- WebDAV auth hardening and security headers

---

## [0.4.1] - 2026-05-25

### Added

- Docker Hub CI/CD pipeline on release tags (multi-arch images)
- Splash screen as login background

---

## [0.4.0] - 2026-05-25

### Added

- `LITE_MODE` for webhook-only deployments without heavy background schedulers
- Settings tab in admin dashboard (hot-reload quality filters and runtime config)

### Changed

- Setup wizard UI improved

---

## [0.3.0-beta] - 2026-05-24

### Added

- **Web Player plugin**: in-browser HLS player with subtitle picker
- **Trakt plugin**: watchlist sync and ratings integration
- **Plugin slot system**: plugins can inject components into the frontend (episode player, settings cards)
- Web Player: HDR detection and SDR-only release selection for browser compatibility
- Web Player: multi-audio HLS master playlist with separate audio streams

---

## [0.2.0-beta] - 2026-05-22

### Added

- **Multi-user authentication** with roles (admin/user) and pending approval flow
- **OIDC/SSO support** for single sign-on
- Users tab in admin with pending approval management
- Redesigned React SPA: Library status indicators, region picker

### Fixed

- Open redirect vulnerability on login
- `/setup` accessible without authentication

---

## [0.1.0-beta.1] - 2026-05-22

First public beta. Mycelium has been running in production for several
users; this release formalizes versioning and adds CI/CD.

### Added

- **React SPA** with Discover, Library, Watchlist, Search, Requests, and Wanted pages
- **Setup wizard** walks through TorBox, Jellyfin, TMDB, quality preferences, and Catbox config on first launch
- **Catbox mode** (lazy materialization): torrents added to TorBox on-demand at playback, removed after idle
- **Multi-user auth** with password and OIDC support, role-based access (admin/user)
- **Auto-upgrade**: background job upgrades existing releases when better quality becomes available
- **Season pack consolidation**: replaces individual episode files when a full season pack is found
- **Zilean + Torrentio combined search**: both sources queried and deduplicated for maximum coverage
- **Checkcached batching**: hashes sent in groups of 100 to avoid 414 URI Too Long errors
- **Language filtering**: exclude unwanted audio languages, prefer specific languages
- **Dolby Vision Profile 5 filter**: blocks DV releases without HDR10 fallback layer
- **Separate EXCLUDE_BLURAY option**: BluRay encodes allowed by default, remux filtered separately
- **Blacklist system**: failed info_hashes tracked and excluded from future attempts
- **Playability state tracking**: per-item failure reasons (TB_429, NO_RELEASE, TIMEOUT, etc.)
- **Discord and Telegram notifications** on success/failure
- **OpenSubtitles integration** for automatic subtitle downloads
- **WebDAV server** (optional) for Plex/Emby compatibility
- **RealDebrid support** as fallback debrid provider
- **Radarr/Sonarr bulk import** for migrating existing libraries
- **Community install guide** by Ventrex (EN/NL, Proxmox/NAS)
- **Admin dashboard** with Overview, Requests, Blacklist, Maintenance, Settings, and Logs tabs
- **Pagination** on admin tables (25/50/100/250 rows)
- **CI/CD**: GitHub Actions builds multi-arch Docker images on tag push to GHCR

### Fixed

- Startup crash when duplicate imdb_id rows exist in requests table
- Monitor loop continuing after checkcached 429 (now backs off 60s in catbox mode)
- Upgrader crash from renamed rate limit constant
- Source field showing first word of torrent name instead of torrentio/zilean
- REMUX filter blocking all BluRay encodes (now only blocks actual remux)

### Changed

- Admin page embeds seamlessly in SPA (no double topbar when accessed via sidebar)
- Admin colors matched to SPA palette
- Repair tab renamed to Maintenance with grouped action cards
- Quality preferences and filters are hot-reloadable via Settings (no restart needed)
