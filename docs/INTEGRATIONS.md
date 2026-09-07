# Integrations

How Mycelium talks to the rest of a media stack.

## Radarr and Sonarr

Mycelium can mirror its library into Radarr and Sonarr. Turn it on with
`ARR_SYNC_ENABLED=true` (Settings > Radarr / Sonarr). Every title Mycelium
adds is created in the arr as a monitored entry with **search off**, and
removed again on "Remove from library". A reconcile job runs every
`ARR_SYNC_INTERVAL_MINUTES` (60) and does two things: it adds anything the
arrs are missing, and it purges titles that were deleted elsewhere while
Mycelium was not told. It only ever removes arr entries it put there itself,
as part of purging that title.

That second part is what makes the delete webhooks (below) optional. A
title Mycelium once put in the arr that has since vanished from the arr's
listing, and that the arr confirms it no longer holds when asked directly,
was deleted there and is purged on the next reconcile. A title whose `.strm`
files are all gone from disk was deleted in Jellyfin (Jellyfin removes the
file with the item); the separate on-disk check (`DISK_SYNC_ENABLED`, hourly,
needs only Catbox mode) purges those, with or without any arr. So a missed
webhook, or none configured at all, still converges within the hour. The
webhooks make it instant. Titles touched in the last ten minutes are left
alone.

Guards keep a broken arr or a lost mount from wiping the library: the
reconcile refuses to purge anything when an arr lists nothing while
mirrored titles exist, when more than half of the mirrored titles vanish at
once, when more than half the titles with files lose them at once, or when
the media tree holds no `.strm` at all. Each refusal is a warning in the
log containing "refusing to purge", and the refused titles are put back in
the arr instead, the way the reconcile always worked. Set
`ARR_SYNC_PURGE_ENABLED=false` to keep that add-only behaviour permanently.
Two Mycelium instances sharing one arr will purge each other's titles
through this path; give each its own arr.

Every purge made this way is logged and shows in the admin activity feed
with the reason (deleted in Radarr, deleted in Sonarr, or files gone).

What this gives you:

- Seerr sees the title in the arr and stops treating it as unknown.
- Maintainerr can manage the title through the arr. When it deletes there,
  the arr's delete webhook tells Mycelium to purge (see Delete webhooks).
- Calendar widgets (Jellyfin Enhanced, Homarr) list the title.

What to expect:

- The arrs **never import `.strm` files**. Without the stub tree below,
  every mirrored title shows as **Missing**; that is cosmetic. Do not "fix"
  it by giving the arr a download client.
- Give the arrs **no download client**. Radarr logs a "no download client is
  available" health warning; ignore it.
- Root folder: blank means the arr's first root folder. Settings > Radarr /
  Sonarr has a Load button that fills a dropdown from the arr, and
  a Test button per arr; both use the URL and key as typed. In `.env`, set
  `RADARR_ROOT_FOLDER` / `SONARR_ROOT_FOLDER` to a path. Pick the quality
  profile the same way (`RADARR_QUALITY_PROFILE`, `SONARR_QUALITY_PROFILE`);
  blank uses the first profile, which is what older releases always did.
- Mycelium sends `imdb:` lookups; for a movie it also falls back to a `tmdb:`
  lookup when one is known, and for a series Sonarr cannot find that way it
  resolves the TVDB id through TMDB and retries.

### Stub files (so titles show as owned)

Turn on `ARR_STUBS_ENABLED` and Mycelium writes a tiny fake `.mkv` per title
into a folder tree the arrs scan as their root folder. Radarr and Sonarr
then show the title with a file and the quality Mycelium found, Maintainerr's
"delete files" has something to delete, and calendar widgets show the title
as owned. The stubs are a few kilobytes: a valid MKV header with a runtime
and no video, the same trick Mycelium Spore uses for Plex.

Needs `CATBOX_MODE=true`; the stubs are built from Mycelium's virtual
items.

Setup, once:

1. Create a host folder, for example `/opt/mycelium/arr-stubs`, owned by the
   same `PUID:PGID` as Mycelium.
2. Mount it into three containers: Mycelium at `ARR_STUB_PATH` (default
   `/arr-stubs`), Radarr and Sonarr anywhere, for example `/mycelium`.
3. In Radarr add `/mycelium/movies` as a root folder, in Sonarr
   `/mycelium/series`, then pick them in Settings > Radarr / Sonarr with the
   Load buttons.
4. Set `ARR_STUBS_ENABLED=true`. The hourly reconcile fills the tree for
   every title already in the library; new titles get their stub as they are
   added.

What to expect:

- Names are truthful: `Heat (1995) - WEBDL-1080p.mkv` is what Mycelium
  found. Titles below your profile cutoff appear under Cutoff Unmet, which is
  harmless with search off and no download client; the stub is rewritten
  when Mycelium upgrades the title.
- Mycelium writes into the folder the arr chose, so your folder naming
  format is respected, and marks each folder with a `.mycelium` file. It
  only ever deletes folders carrying that marker.
- Deleting the file in Radarr (or Maintainerr with "delete files") removes
  the title from Mycelium, like deleting the movie. Deleting a single
  episode file in Sonarr does nothing; delete the series.
- The health card shows "Arr stubs: not mounted" when the folder is missing
  inside the Mycelium container.

## Delete webhooks

Mycelium owns the `.strm` library, so a deletion made anywhere else has to
reach it, or the title's database rows, monitoring and 24-hour duplicate
guard outlive the files and the next request for it is silently swallowed.
Two hourly jobs catch these on their own: the Radarr/Sonarr reconcile (see
above) notices a title the arr no longer holds, and the on-disk check
(`DISK_SYNC_ENABLED`, needs only Catbox mode, no arrs) notices a title whose
`.strm` files are gone, which is what a Jellyfin delete looks like. The
webhooks below make it immediate.

Point these at `POST https://<mycelium>/webhook/arr`. It uses the same
secret as the Seerr webhook: send it as the `X-Webhook-Secret` header
(preferred) or as `?secret=` in the URL.

**Radarr** Settings > Connect > Webhook: URL as above, method POST, tick
**On Movie Delete**. Add the secret under Headers. Tick **On Movie File
Delete** as well if you use the stub files (see above): a manual file
delete in Radarr, or Maintainerr with "delete files", then removes the
title from Mycelium. Radarr's own upgrade and missing-from-disk file events
are ignored.

**Sonarr** Settings > Connect > Webhook: same, tick **On Series Delete**.

**Jellyfin** (Webhook plugin): add a Generic destination with the URL above,
tick **Item Deleted**, item types Movies and Series, and use this template:

```
{"eventType":"ItemDeleted","itemType":"{{ItemType}}","name":"{{Name}}","imdb":"{{Provider_imdb}}","tmdb":"{{Provider_tmdb}}","tvdb":"{{Provider_tvdb}}"}
```

Add a request header `X-Webhook-Secret` with your secret.

What happens: a `MovieDelete`, `SeriesDelete` or `ItemDeleted` for a title
Mycelium owns runs the same purge as "Remove from library" (files, `.nfo`,
artwork, Spore stubs, database rows, monitoring, dedup keys, then a Jellyfin
refresh). Deletions of titles Mycelium does not own are answered `ignored`
and nothing happens, which is also what stops the arr echoing our own
removal back into a loop. `Test` events return `ignored` too, so the arr's
"Test" button succeeds.

Deleting a single **episode** in Jellyfin removes that `.strm` file (Jellyfin
has the rights to do so) but is not a title deletion, so it is ignored here;
the repair job may regenerate the file. Delete the series instead.

## Jellyfin: targeted refresh

After an add, an upgrade or a purge, Mycelium now tells Jellyfin exactly
which files changed (`POST /Library/Media/Updated`) instead of asking for a
full library scan. A large library is no longer rescanned on every request.

Expect about a minute, not seconds: Jellyfin waits for its library monitor
delay (60 seconds by default) after the last reported change before it
refreshes, so a title shows up, or disappears, roughly a minute after
Mycelium reports it. A title that never appears means the path does not
match, see `JELLYFIN_MEDIA_PATH` below. The full scan is still used by the
cleanup job, which renames and merges folders, and as a fallback whenever
the targeted call fails.

If Jellyfin mounts the media at a different path than Mycelium does, set
`JELLYFIN_MEDIA_PATH` to Jellyfin's path (Settings > Connections). Blank
means both containers use the same path, which is what the compose in this
repo does.

**Autopulse** is redundant for a Mycelium library once this is in place; you
can keep it for other sources.

While you are in Jellyfin's library settings for the Mycelium library: turn
**off** Trickplay, chapter image extraction and intro detection for that
library. Each of those opens every file, which for a `.strm` means pulling
the whole title through the TorBox CDN and resetting its retention clock.

## Seerr: outcome reporting

With `SEERR_REPORT_STATUS=true` (the default) Mycelium reports back to Seerr
for every request that came in through the Seerr webhook:

| Mycelium outcome | Seerr |
|---|---|
| Added | media marked **Available** at once, no need to wait for Seerr's Jellyfin scan |
| No suitable stream (terminal) | request **Declined**; the person can re-request |
| Released but nothing acceptable yet | left as **Processing**, Mycelium keeps searching |
| Still nothing after `SEERR_DECLINE_WANTED_AFTER_DAYS` (default 30) | request **Declined** once; Mycelium keeps searching anyway |
| Removed from library | Seerr's media record is removed at once (what its own "clear media data" button does), so the title can be requested again straight away. Seerr's request history for that title goes with it |

Mycelium finds the title in Seerr by its TMDB id, so this works for titles
requested before Mycelium stored Seerr request ids, for series, and for
titles added from Mycelium's own Discover page that also exist in Seerr.
(Seerr 3.4.1 accepts a "deleted" media status and then ignores it, which is
why removal deletes the record instead.)

"Removed from library" means the Remove from library button, the arr and
Jellyfin delete webhooks, and anything else that runs the purge. The Delete
button only forgets Mycelium's request record and leaves the files, so the
title really is still in Jellyfin and Seerr is not told.

The Seerr API key must belong to a user with **Manage Requests** (an admin
key does). Titles added from Mycelium's own Discover, Trakt or MDBList have
no Seerr request and are not reported.

## Auto-requesters and the TorBox add budget

TorBox allows 60 uncached adds per hour per API key, and Mycelium spends
one for every title it adds while `CATBOX_PRELOAD` is on (the default):
the torrent is added to TorBox at request time so the first play is
instant. Every tool that files requests draws on that same budget:
Suggestarr, Trakt and MDBList watchlist sync, the auto-approve genre and
actor rules, and Seerr's own users.

The Overview health card shows **TorBox adds this hour** and turns amber
from 45. When it does, or when the log shows `createtorrent` rate limits:

- Keep each auto-requester's per-run cap at or under 10:
  `TRAKT_AUTO_REQUEST_CAP`, `MDBLIST_AUTO_REQUEST_CAP`,
  `AUTO_APPROVE_DAILY_LIMIT`, and Suggestarr's own "max results" setting.
  A Suggestarr run that files 40 recommendations at once uses two thirds of
  the hour on its own.
- Or turn `CATBOX_PRELOAD` off and set `CATBOX_LAZY_ADD` on. Titles are then
  added to TorBox on first play instead of at request time, so requests are
  free and only actual viewing spends the budget. The first play of a title
  waits for TorBox instead of starting instantly.
- Requests that hit the limit are not lost: they wait in the retry queue
  and are processed when the hour rolls over.
