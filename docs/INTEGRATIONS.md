# Integrations

How Mycelium talks to the rest of a media stack.

## Radarr and Sonarr

Mycelium can mirror its library into Radarr and Sonarr. Turn it on with
`ARR_SYNC_ENABLED=true` (Settings > Radarr / Sonarr). Every title Mycelium
adds is created in the arr as a monitored entry with **search off**, and
removed again on "Remove from library". A reconcile job runs every six hours
and adds anything the arrs are missing; it never deletes from the arrs.

What this gives you:

- Seerr sees the title in the arr and stops treating it as unknown.
- Maintainerr can manage the title through the arr. When it deletes there,
  the arr's delete webhook tells Mycelium to purge (see Delete webhooks).
- Calendar widgets (Jellyfin Enhanced, Homarr) list the title.

What to expect:

- The arrs **never import `.strm` files**, so every mirrored title shows as
  **Missing** in Radarr/Sonarr. That is cosmetic. Do not "fix" it by giving
  the arr a download client.
- Give the arrs **no download client**. Radarr logs a "no download client is
  available" health warning; ignore it.
- Root folder: blank means the arr's first root folder. Set
  `RADARR_ROOT_FOLDER` / `SONARR_ROOT_FOLDER` to pick another. The quality
  profile is the arr's first one; it does not matter, nothing is searched.
- Mycelium sends `imdb:` lookups; for a series Sonarr cannot find that way it
  resolves the TVDB id through TMDB and retries.
