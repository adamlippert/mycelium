# Library admin: a title-centric management view

Date: 2026-09-07. Status: approved in conversation, awaiting file review.
Builds on the Settings field kit (0.17.0) and its style.

## Goal

Replace the admin Requests tab, which is three unrelated panels (pending
approvals, a flat request list with search and two delete buttons, the
auto-approve rules), with two tabs that answer the operator's real
questions in one place: what happened to this title and what do I do about
it (Library), and what did people ask for and who (Requests). The data
already exists across seven tables and five screens; today an admin bounces
between the admin, Maintenance, Blacklist, the user-facing Requests page and
the Wanted page to answer one question.

Scope of this spec: the Library tab (plan 1) in full, and the Requests tab
(plan 2) in outline. Picking a different release for a title (candidate
list and swap) is a third plan and is out of scope here.

## Decisions taken

| Question | Decision |
|---|---|
| What the view optimises for | All four jobs the operator named: failure triage and retry, fixing a bad or unplayable file, who requested what, keeping series complete; plus queue management |
| Navigation | Two tabs: Library (titles, drawer, queue) and Requests (approvals, history, quotas, auto-approve rules) |
| Data side | One aggregated read model in a new backend module, two endpoints, SQL joins; no client-side composition, no summary table |
| Style | The Settings kit: left rail, cards with a small uppercase title and one-line description, `Select`/`MultiSelect`/`Button`, inline action results, sticky action bar |

## 1. Data and endpoints

### `GET /ui/api/library`

Query params: `q` (title, imdb id or hash substring), `status` (comma list
of `success, wanted, upcoming, failed, pending`), `type` (`movie` or
`series`), `problem` (`failed, wanted, unplayable, missing_episodes,
in_retry_queue, no_requester, not_mirrored`), `requester` (user id, or
`auto`), `added` (`24h, 7d, 30d`), `sort` (`title, status, requester,
updated, created`), `order` (`asc, desc`), `page` (1-based), `per_page`
(default 50, max 200). Returns `{"rows": [...], "total": int, "page": int,
"per_page": int}`.

Row fields: `id, imdb_id, tmdb_id, title, media_type, status, error,
quality, source, info_hash, seasons, created_at, updated_at, requester`
(username of the most recent `user_requests` row for the imdb id, or `auto`
when none), `requested_at, playability` (`{status, last_fail_reason}` or
null), `missing_episodes` (count of `wanted_episodes` rows with status
`wanted`), `retry` (`{attempt, next_retry_at}` or null), `arr_mirrored`
(bool from `requests.arr_mirrored_at`), `in_torbox` (bool: any virtual item
with a `torbox_id`).

Implementation: `library_admin.list_titles(filters) -> (rows, total)` in a
new `library_admin.py`, one SELECT with correlated subselects over
`requests`, `user_requests`, `users`, `wanted_episodes`, `playability_state`,
`retry_queue`, `virtual_items`, and one COUNT with the same WHERE. Two new
indexes: `user_requests(imdb_id, created_at DESC)` and
`wanted_episodes(imdb_id, status)`.

Views are named filter sets resolved server-side so the rail counts come
from the same code:

| View | Predicate |
|---|---|
| `all` | none |
| `attention` | status `failed`, or playability status not ok and not unknown, or retry attempt >= 3 |
| `wanted` | status `wanted` or `upcoming`; default sort oldest updated first |
| `queue` | status `pending`, or a retry-queue row, or a wanted-list row; default sort by next retry ascending |
| `incomplete` | series with `missing_episodes > 0` |
| `unmirrored` | status `success` and not `arr_mirrored`; only offered when the mirror is on |

`GET /ui/api/library/views` returns `{view: count}` for the rail.

### `GET /ui/api/library/<imdb_id>`

The drawer payload: `request` (the row), `items` (virtual items: token,
info_hash, provider, strm_path, torbox_id, last_played, play_count),
`playability`, `episodes` (series only: seasons with present, wanted and
missing counts; episodes per season loaded by
`GET /ui/api/library/<imdb_id>/season/<n>`), `monitored` (the
`monitored_series` row), `retry`, `user_requests` (each with username,
status, reviewed_by username, note, dates), `seerr_request_id`,
`override` (the show override), `hashes` (hashes this title has used, with
`blacklisted` bool and last error), `activity` (log entries, newest first,
`limit` and `before` params for Load more), `arr` (`mirrored_at`, and the
arr ids when the listing has them).

### Activity log gains `imdb_id`

Migration: `ALTER TABLE activity_log ADD COLUMN imdb_id TEXT` plus an index
on it. `db.log_activity(event, title, message, success, imdb_id=None)`.
Callers that know the id pass it: processor success and failure, purge,
the arr and disk reconcile purges, upgrader, pack consolidation, retry. The
drawer query matches by `imdb_id`, falling back to `title` equality for
rows written before the column existed.

### Action routes (admin-only, JSON `{ok, message}`)

Existing and reused: `POST /ui/api/requests/<id>/retry`,
`POST /ui/api/requests/<id>/purge`,
`POST /ui/api/virtual-items/<token>/re-resolve`.

New, all thin wrappers over existing helpers:

| Route | Does |
|---|---|
| `POST /ui/api/library/<imdb_id>/mirror` | `arr_sync.mirror_add` for the title |
| `POST /ui/api/library/<imdb_id>/unmirror` | `arr_sync.mirror_remove` |
| `POST /ui/api/library/<imdb_id>/drop-retry` | `db.remove_retry` for the title's row |
| `POST /ui/api/library/<imdb_id>/retry-now` | runs the retry-queue entry now (same path as `retry_queue.run_due` for one row) |
| `POST /ui/api/library/<imdb_id>/recheck-series` | the series sync for this title only |
| `POST /ui/api/library/<imdb_id>/episodes/<s>/<e>/retry` | one episode through the processor |
| `POST /ui/api/library/hash/<hash>/blacklist` and `/unblacklist` | the blacklist helpers |
| `POST /ui/api/library/<imdb_id>/playability/reset` | clears the playability record |
| `POST /ui/api/library/<imdb_id>/override` (JSON body) and `DELETE` | `db.upsert_show_override` / delete |

Bulk actions are the frontend calling the per-title route once per
selected row; no bulk endpoint.

## 2. The Library tab

Layout mirrors Settings: a left rail and a main column.

**Rail.** Saved views with counts at the top (All, Needs attention, Wanted,
Queue, Incomplete series, Unmirrored when the mirror is on). Below, the
filters: search (`type="search"`), type `Select`, status `MultiSelect`
chips, requester `Select` (users plus "auto"), added `Select` (24 hours, 7
days, 30 days, any). Filters combine with the view. The whole state
(view, filters, sort, page) lives in the URL hash after `#library?`, so a
view is linkable and survives reload.

**Table.** Columns: title (type icon, year), status pill with the error as
a muted second line, quality and source as a mono tag, requester, badges
(playability red or amber, missing-episode count, retry attempt, arr
check, TorBox cloud), updated. Sortable headers: title, status, requester,
updated, created. Fifty rows a page, server-side, with a page-size select.
Row click opens the drawer; a checkbox per row and a header select-all
drive the action bar.

**Action bar.** Sticky at the bottom when rows are selected: "N selected",
Retry, Re-resolve, Mirror to arr, Remove from library; for the Queue view
also Run now and Drop from queue. Each runs the per-title route
sequentially, shows "k of N", and lists failures inline. Remove keeps the
existing confirmation wording, extended with the count.

**Empty and loading states** say what the view means and what would put a
title in it.

## 3. The title drawer

A right-side panel over the table, about 560px, closed by Escape or the x.
Header: title, year, type, status pill; primary actions as `Button`s:
Retry, Re-resolve, Mirror to arr, Purge, Blacklist current hash. Below,
cards in the Settings style, hidden when empty:

| Card | Contents and actions |
|---|---|
| Status | status, last error, changed at; retry row (attempt, next retry) with Retry now and Drop from queue; pending rows say the processor has it |
| Release | quality, source, hash, provider, TorBox state and id, each `.strm` path, last played, play count; Copy on hash and path |
| Playability | status, last ok provider and time, last failure, consecutive failures; Re-resolve, Reset |
| Episodes (series) | seasons with present, wanted, missing counts; expand loads episodes with air date, attempts, last attempt; per-episode Retry; Recheck series |
| Requests | every user request: user, status, reviewed by, note, dates; Seerr request id |
| Preferences | the show override: quality preference, allow 4K, prefer HEVC, notes; Save, Clear |
| Arr mirror | mirrored since, arr ids; Mirror now, Remove from arr |
| Hashes | hashes used, blacklisted flag and last error; Blacklist, Unblacklist |
| Activity | log entries for this title, twenty at a time, Load more |

Every action shows its `{ok, message}` inline like a Settings Test button,
then the drawer and the table page refetch.

## 4. The Requests tab (plan 2, outline)

Same rail and table kit. Views: Pending, Approved, Denied, All; filters
user, type, date. Columns: title with type, user, requested, status pill,
reviewed by and when, note. Approve and Deny on pending rows; Deny opens an
inline reason field (no browser prompt). Row click opens the same title
drawer. Below the table: a Quotas card (per-user monthly count against
quota) and the Auto-approve rules editor moved here unchanged with Run
now. History is kept: every user request row is listed, not only pending.

## 5. Navigation and what leaves

Tab strip: Overview, Library, Requests, Users, Filter rules, Scrapers,
Logs, Releases, Maintenance, Blacklist, Settings. Maintenance keeps its
library-wide jobs; its per-token playability panel is removed once the
drawer's Playability card ships (the plan keeps the panel until then). The
Blacklist tab gains a title column. The Overview's retry-queue count links
to the Queue view. The old admin `Requests.tsx` is replaced. The
user-facing Requests page (failed panel, retry for end users) is untouched.

## 6. Testing

Backend (pytest, existing conventions): `list_titles` against a seeded
database for every filter, view predicate, sort and the paging math;
requester resolution; the detail payload with each card's data present and
absent; the activity-log migration and that callers pass the id; each
action route on source text plus its helper; the blacklist and override
helpers. Mutation checks on the view predicates.

Frontend (vitest): rail views with counts switch the query; filters
serialise to and restore from the hash; table badges from a fixture; the
selection drives the action bar and bulk posts once per title with a
running count; the drawer opens from a row, hides empty cards, each card's
action posts and refetches; Escape closes the drawer; the Requests tab's
inline deny reason (plan 2).

## 7. Delivery

Plan 1 (Library), nine tasks: (1) activity-log column and callers; (2)
`library_admin.list_titles`, views and the two list endpoints; (3) the
detail query and endpoints; (4) the action routes; (5) rail, filters,
table, paging, hash state; (6) drawer shell with Status, Release and
Playability cards; (7) Episodes, Requests, Preferences, Arr, Hashes,
Activity cards; (8) action bar and Queue view; (9) tab strip, Maintenance
and Blacklist adjustments, docs. Subagent-driven with an opus final
review; released as 0.19.0.

Plan 2 (Requests): views, inline deny, quotas card, rules move; 0.20.0.
Release swap: a third plan.

## Risks

The list query joins six tables; at 5,000 titles SQLite answers in
milliseconds, and the two indexes cover the hot subselects. The Episodes
card loads per season on expand, so a long series stays cheap. Removing
the Maintenance playability panel is deferred until the drawer covers it.
The only data-model change is one nullable column, so rollback is a
redeploy.
