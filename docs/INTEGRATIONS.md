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

## Delete webhooks

Mycelium owns the `.strm` library, so a deletion made anywhere else has to
reach it, or the title's database rows, monitoring and 24-hour duplicate
guard outlive the files and the next request for it is silently swallowed.

Point these at `POST https://<mycelium>/webhook/arr`. It uses the same
secret as the Seerr webhook: send it as the `X-Webhook-Secret` header
(preferred) or as `?secret=` in the URL.

**Radarr** Settings > Connect > Webhook: URL as above, method POST, tick
**On Movie Delete**. Add the secret under Headers. Leave the file-delete
events unticked; Mycelium ignores them in this version anyway.

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
