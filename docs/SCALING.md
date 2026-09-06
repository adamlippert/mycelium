# Scaling notes

Measured answers to "will this hold up", so the next person asking does not
have to re-derive them. Numbers here were benchmarked on the real schema and
the real SQLite settings (WAL, `synchronous=NORMAL`, one connection per
thread), against a seeded 50,000-item library.

---

## Would Postgres help?

**No, and not by a small margin.** The database is roughly three orders of
magnitude away from being the constraint.

Measured throughput:

| Operation | Rate |
|---|---|
| `record_egress`, single thread | 75,000 writes/sec |
| Hot-path writes interleaved, 8 threads contending | 14,500 writes/sec |
| `reserve_createtorrent_slot` (`BEGIN IMMEDIATE`, serialises by design) | 11,600 writes/sec |
| `get_virtual_item`, indexed lookup | 122,000 reads/sec |

Against that, a busy install writes on the order of tens of rows per second
at most. Browsing is reads, and the stats overview is cached for 60 seconds.

The two things that actually bind, neither of which a database change
touches:

1. **TorBox allows 60 uncached `createtorrent` calls per hour, per API key.**
   That is about 1,440 distinct new plays per day across every user you have.
   It is enforced server-side and synchronised across their servers, so extra
   IPs buy nothing; only extra accounts would.
2. **The app is pinned to one gunicorn worker.** Catbox's single-flight
   locks, the scan-burst detector and Flask-Limiter's `memory://` counters
   all live in process memory. Moving to Postgres without also moving that
   state to shared storage would multiply the rate-limit guards into N
   independent counters, which is the exact failure mode the TorBox quota
   tracker was moved into SQLite to avoid. See the comment at the Dockerfile
   `CMD`.

Postgres becomes a real conversation only after that in-process state is
addressed, and that is an architectural change rather than a driver swap.

---

## What an `egress_log` row is, and why the count is smaller than it looks

One row is **one HTTP Range request whose bytes Mycelium proxied**. Not one
playback. A player fetches a film in ranges, buffering as it goes and asking
again on every seek, so a single viewing can be many requests.

The volume therefore depends entirely on **how often the proxy is in the
byte path at all**, and for most libraries the answer is: rarely.

`spore-stream` reports egress from exactly two places, the end of
`serveCold` and the end of `serveWarm`. The redirect path does not report,
because it never carries bytes:

| Container | Path | Rows |
|---|---|---|
| MKV and other non-MP4 | 302 redirect straight to the TorBox CDN | **none** |
| MP4 | proxied, warm from the `.fsh` cache or cold while it builds | one per Range request |

There is one wrinkle that does not change the conclusion: the **first** play
of any title, MKV included, cold-proxies briefly while the `.fsh` cache is
built in the background. Once that lands as a sentinel (`ftyp_size == 0`),
every later play of that title redirects. So an MKV produces a handful of
rows once, ever, rather than rows per playback.

**On an MKV-dominant library, which is what TorBox mostly carries for quality
releases, steady-state viewing produces almost no rows at all.** A library
census during this work found ten MKV sentinels and zero proxied MP4s.

### The consequence for the Overview tile

The tile is labelled **"Proxied egress this month"** rather than total
egress, and the sub-line says MKV plays are not counted. That is honest, but
on an MKV library it means the figure reads near zero while real TorBox
bandwidth is far higher. Do not read it as "we are nowhere near the plan
floor". Closing that gap means recording the item's size on the redirect
branch as an estimate; it is an open item.

---

## If MP4s ever become common here

This is the case worth watching, because it is the one where the row count
stops being negligible. It would arrive through a change in what gets
selected, not through more viewers: a filter or sort-order change that
favours smaller web releases, a scraper whose results skew to MP4 (YTS and
similar), or Plex usage via Spore, which proxies far more than Jellyfin does.

### The trigger

Watch the row count, not the viewer count:

```bash
docker exec mycelium python3 -c "
import db
with db._connect() as c:
    print('egress rows :', c.execute('SELECT COUNT(*) n FROM egress_log').fetchone()['n'])
    print('last 24h    :', c.execute(\"SELECT COUNT(*) n FROM egress_log WHERE created_at > datetime('now','-1 day')\").fetchone()['n'])
"
```

Measured cost of `egress_this_month()`, which sums every row since the start
of the calendar month and sits behind the Overview's 60 second cache:

| Rows in the window | Query time | Database size |
|---|---|---|
| 1.7M | 62 ms | 0.14 GB |
| 12M | 454 ms | 1.0 GB |

**Harden when the daily row count reaches roughly a million**, which is where
the month-to-date sum starts costing hundreds of milliseconds and the
database starts gaining a gigabyte a week. Retention is currently
`prune_old(14)` every six hours, so the table settles at fourteen days of
rows.

### The fix, when it is needed

A **daily rollup table**: one row per day holding that day's byte total,
written by the existing prune job or a small scheduled task, with
`egress_this_month()` summing thirty rows instead of tens of millions. That
turns the query into a sub-millisecond lookup at any volume.

It is a schema change, not a database change. Postgres would run the same
expensive query over the same rows.

---

## Where the real limits are, in order

1. **TorBox's 60 uncached adds per hour.** Caps distinct new plays per day
   across all users, regardless of library size or hardware.
2. **TorBox's monthly bandwidth floors**, 5 TB free through 30 TB Pro, with a
   three-warning then permanent-ban policy. This is the account-ending one,
   and the Overview tile only sees the proxied fraction of it.
3. **The single-worker pin**, which caps concurrency long before SQLite does.
4. **Jellyfin's own library scaling**, which becomes the wall well before
   Mycelium's storage does at very large libraries.
5. **SQLite**, a distant fifth on these measurements.
