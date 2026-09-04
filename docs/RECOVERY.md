# Recovery

What to do when Mycelium comes up with the wrong data, or none.

Written after a real incident on 2 September 2026, where a deployment came
back with an empty database. Nothing was corrupt and nothing was lost: the
container was pointed at a fresh volume. That is why the first section is
diagnosis and not restoration. Restoring a backup onto the wrong volume
makes a recoverable situation worse.

---

## Stop before you touch anything

**If the library looks empty, stop the container first.**

```bash
docker stop mycelium
```

With an empty database and the media mount still attached, two scheduled
jobs will actively destroy the thing you are trying to recover:

- **`strm_repair`** walks every `.strm` file, finds no matching row in the
  database, treats each one as an orphaned token, and deletes it.
- **Reprocessing** then re-adds those titles to TorBox, against a limit of
  60 uncached adds per hour. A library of any size will exhaust that and
  start failing.

The database being empty is recoverable. The `.strm` tree being deleted
because the database was empty is a much longer afternoon.

---

## Diagnose: is the data gone, or is the container looking in the wrong place?

Two independent stores reading as empty at the same moment is the signature
of a mount problem, not data loss. Storage does not usually fail in pairs.

**1. What is actually mounted into the container?**

```bash
docker inspect mycelium --format \
  '{{range .Mounts}}{{.Type}}  {{if .Name}}{{.Name}}{{else}}{{.Source}}{{end}} -> {{.Destination}}{{println}}{{end}}'
```

Expect a named volume at `/data` and your media at `/media`. A `bind` mount
where you expected a volume, or a path that does not match your compose
file, is the answer.

**2. What does the container see?**

```bash
docker exec mycelium sh -c 'ls -la /data; echo "--- backups:"; ls -la /data/backups; echo "--- media:"; ls /media | head'
```

**3. Do the real volumes still exist on the host, with data in them?**

This is the important one. A volume holding `requests.db` and a `backups/`
directory means nothing was lost and this is a remount, not a restore.

```bash
for v in $(docker volume ls -q | grep -i myc); do
  echo "=== volume: $v"
  docker run --rm -v "$v":/v alpine sh -c 'du -sh /v; ls -la /v | head -20'
done
```

**4. Is the media still on the host?**

```bash
du -sh /jellyfin/media 2>/dev/null; ls /jellyfin/media 2>/dev/null | head
```

### Reading the result

| What you see | What it means | What to do |
|---|---|---|
| A volume holds `requests.db` and `backups/` | Nothing was lost. The container is attached to the wrong volume. | Fix the volume in Coolify or the compose file and redeploy. **Do not restore.** |
| Volumes exist but are empty, media is present | The database is genuinely gone. | Restore from a backup, below. |
| Volume and media both empty | The mount is wrong, or the host lost both. | Do not restore yet. Find the host paths first. |

---

## Restore from a backup

Mycelium copies the SQLite database to `/data/backups/requests_<timestamp>.db`
every `BACKUP_INTERVAL_HOURS` (24 by default) and keeps the **14 most
recent**.

### What a backup covers

The database only: requests, virtual items, monitored series, settings,
users, the playability state. That is the irreplaceable part.

It does **not** include, and does not need to:

- **`.strm` files** -- regenerated from the database by the repair job
- **`.nfo` files, posters, artwork** -- regenerated
- **The `.fsh` moov cache** -- rebuilt on the next play of each title
- **The native Zilean index** (`/data/zilean_native.db`) -- re-syncs from
  upstream, though a full rebuild is a large download

So a restored database plus a repair pass gets you back. Nothing else has
to be recovered by hand.

### From the admin UI

**Admin -> Maintenance -> Backup restore.** Enter the filename (for example
`requests_20260902_030000.db`) and press Restore.

The current database is copied to `requests.pre-restore.<timestamp>.db` in
`/data` before it is replaced, so a restore is itself undoable. The UI now
reports failure explicitly; a red error means nothing was changed.

**Then restart the container.** This is not optional:

```bash
docker restart mycelium
```

Mycelium keeps one SQLite connection per thread for the lifetime of the
process. Those handles still point at the file that was replaced, so until
you restart, the running app is reading the old database.

### By hand

Use this when the UI is unreachable, which is likely if the database is the
problem.

```bash
# See what is available
docker exec mycelium ls -la /data/backups

# Stop first: copying over a database that a running process holds open
# risks a torn file.
docker stop mycelium

# Keep the current database, whatever state it is in
docker run --rm -v mycelium-data:/data alpine \
  sh -c 'cp /data/requests.db /data/requests.manual-pre-restore.db 2>/dev/null || true'

# Restore
docker run --rm -v mycelium-data:/data alpine \
  sh -c 'cp /data/backups/requests_20260902_030000.db /data/requests.db'

docker start mycelium
```

Substitute your own volume name from step 3 of the diagnosis.

---

## Verify

```bash
# Does the app agree it has a library again?
curl -s https://your-host/ui/api/stats | python3 -m json.tool | head -20

# Row counts straight from the database
docker exec mycelium python3 -c "
import db
print('requests      :', len(db.get_recent(100000)))
print('virtual items :', db.count_virtual_items())
print('users         :', db.user_count())"
```

Signs it worked:

- Item counts match roughly what you expect
- The **empty-library alert stops firing**. Mycelium warns when the database
  holds no items while `.strm` files still exist on disk, which is exactly
  the state this document is about. Silence means the two agree again.
- Playback works on a title that existed before the incident

If `.strm` files were deleted before you stopped the container, run
**Admin -> Maintenance -> Repair broken strm files** to regenerate them from the restored
database.

---

## After the fact

- **Check the backups are actually running.** `ls -la /data/backups` should
  show a file per day, up to fourteen. An empty directory means backups have
  been failing silently and the next incident has no floor under it.
- **The `.pre-restore` copy is your undo.** Keep it until you are satisfied,
  then delete it; nothing prunes it for you.
- **If this was a mount problem, fix it in Coolify**, not in a file on the
  host. Coolify regenerates its compose from stored configuration, so an
  edit on disk can be silently reverted on the next deploy.
