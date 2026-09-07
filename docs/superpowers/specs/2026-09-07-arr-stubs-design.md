# Arr stub tree (Level B) design

Status: approved in conversation on 2026-09-07. Implements the "Level B"
follow-up to the arr integration shipped in 0.14.0 to 0.14.4.

## Problem

Radarr and Sonarr never import `.strm` files, so every title Mycelium
mirrors into them (0.14.0) shows as **Missing**. That is cosmetic for Seerr,
but it means the arrs never hold a file for the title, so Maintainerr's
"delete files" path has nothing to delete, calendar widgets show the title
as not owned, and the "Missing" and "Cutoff Unmet" lists are noise.

## Idea

Mycelium writes a small fake video file (a stub) per `.strm` into a second
folder tree that the arrs scan as their root folder. The stub is the same
EBML/MKV header Spore already builds for Plex (`strm_generator.make_stub_mkv`):
tracks, a Segment Duration from the TMDB runtime, no media data, a few KB.
MediaInfo reports a runtime, so the arrs' sample detection (runtime first,
size only as a fallback) accepts it, and the arrs parse the quality from the
file name.

## Where the tree lives

A dedicated host folder, bind-mounted into Mycelium, Radarr and Sonarr and
owned by `PUID:PGID` (option 2 of the three discussed; the media-subfolder
option was rejected because Mycelium's cleanup jobs walk `MEDIA_PATH` and
prune folders without `.strm` files, and the data-volume option because it
would hand the arrs write access to the SQLite database directory).

Mycelium's side: `ARR_STUB_PATH` (default `/arr-stubs`) with `movies/` and
`series/` under it, plus a `.ignore` file at the root so a Jellyfin library
accidentally pointed there skips it.

The arrs' side: the existing `RADARR_ROOT_FOLDER` and `SONARR_ROOT_FOLDER`
settings (the dropdowns added in 0.14.3) must point at the arr's mount of
`<ARR_STUB_PATH>/movies` and `<ARR_STUB_PATH>/series`. When stubs are on,
both are required and Settings says so.

Path translation mirrors `JELLYFIN_MEDIA_PATH`: an arr reports a title at
`<RADARR_ROOT_FOLDER>/Heat (1995)`; Mycelium replaces the root prefix with
`<ARR_STUB_PATH>/movies` and writes there. Because Mycelium writes into the
folder the arr chose, the arr's folder-naming format is respected whatever
it is.

## Settings

| Key | Type | Default | Meaning |
|---|---|---|---|
| `ARR_STUBS_ENABLED` | bool | `false` | Write stubs. Requires `ARR_SYNC_ENABLED`. |
| `ARR_STUB_PATH` | str | `/arr-stubs` | Mycelium's mount of the shared folder. |

Registered in `settings.py` (`_BOOL_KEYS`, `HOT_RELOAD`, the `arr_import`
group), `config.py`, `.env.example`.

## What gets written

- One stub per `.strm`, at the `.strm`'s path relative to `MEDIA_PATH`,
  under the arr-chosen title folder. The relative layout is the one Spore
  already mirrors (`movies/<Title (Year)>/<file>`, `series/<Show>/Season NN/<file>`).
- File name: the `.strm` stem plus a quality tag the arrs parse, for example
  `Heat (1995) - WEBDL-1080p.mkv` and `Show - S01E01 - WEBDL-1080p.mkv`.
  Naming is **truthful**: the tag is what Mycelium actually found. Titles
  below the profile cutoff appear under "Cutoff Unmet"; with search off and
  no download client that list is cosmetic, and the stub is regenerated on
  upgrade. (The alternative, naming every stub at the cutoff, was rejected
  as a lie that also needs the profile's cutoff from the arr.)
- Quality tag derivation: resolution from the request row (`quality`),
  source from the release name carried in the item's magnet `dn=` through
  `release_tags`, mapped onto the arr vocabulary: `remux` to `Remux`,
  `bluray`/`bdrip`/`brrip` to `Bluray`, `webdl`/`web` to `WEBDL`, `webrip`
  to `WEBRip`, `hdtv`/`satrip`/`tvrip` to `HDTV`, `dvdrip`/`dvd` to `DVD`.
  Unknown source: resolution only (`1080p`), which the arrs still parse.
- No `.minfo` sidecar; that belongs to Spore. Spore's tree and this one are
  independent; only `make_stub_mkv()` is shared.

## When

- **Add**: `arr_sync` adds the title to the arr (or finds it present) and
  gets the arr's `path` back. It then writes the stub(s) into that folder
  and posts `RescanMovie` / `RescanSeries` to `/api/v3/command`. Without the
  command the arr only notices on its 12-hourly refresh.
- **Upgrade and consolidation**: where Task 3 of the Level A plan added
  `jellyfin.note_change`, the old stub is removed, a new one written with
  the new tag, and a rescan requested.
- **Purge**: the title's stub folder is deleted **before** `mirror_remove`,
  so the arr's delete (still `deleteFiles=false`) has nothing to clean and
  no `MovieFileDelete` fires back.
- **Reconcile** (six-hourly): for every successful title, ensure the arr
  entry and the stub both exist. Turning the feature on populates the whole
  library on the first run; a lost host folder regenerates itself.
- Everything is best-effort and never raises into the pipeline.

## Delete events from the arrs

`/webhook/arr` already accepts `MovieFileDelete` and `EpisodeFileDelete`
and ignores them. With stubs they mean:

| Event | `deleteReason` | Action |
|---|---|---|
| `MovieFileDelete` | `manual` | purge, like `MovieDelete` (a person, or Maintainerr with "delete files") |
| `MovieFileDelete` | `upgrade`, `missingFromDisk`, other | ignore (no download client; missing-from-disk is our own rewrite) |
| `EpisodeFileDelete` | any | ignore, logged; delete the series instead |

Loop check: purge removes the stub folder first and then the arr entry
with `deleteFiles=false`, so the arr sends only `MovieDelete`, which the
unknown-title guard already ignores.

## Failure handling

- The writer refuses to run when `ARR_STUB_PATH` is missing or not
  writable, and the health card reports "stub folder not mounted" rather
  than silently doing nothing.
- A failed rescan command is logged and left to the next reconcile.
- A stub that cannot be written does not fail the add; the arr entry still
  exists, as in Level A.

## Testing

- Pure: quality tag mapping, file naming, path translation.
- Writer against `tmp_path`: creates the folder, writes an MKV that starts
  with the EBML magic, writes `.ignore` at the root, refuses an unwritable
  root.
- Hooks by source text: add, upgrade/consolidation, purge order (stub
  removal before `mirror_remove`), reconcile backfill.
- Webhook mapping for the file-delete reasons.
- Reconcile backfill against the fake arr transport in `tests/test_arr_sync.py`.
- No arr in the local test stack: the first live check is on the VPS,
  adding one title and watching it turn from Missing to a file with the
  expected quality in Radarr.

## Out of scope

- The setup wizard's Radarr/Sonarr step (unchanged).
- Serving the stubs over Spore's SMB/NFS shares instead of a bind mount.
- Any change to Spore's own tree.
