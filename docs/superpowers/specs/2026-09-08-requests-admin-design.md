# Requests admin: approvals, history and quotas

Date: 2026-09-08. Status: approved in conversation, awaiting file review.
Plan 2 of the Library admin work; section 4 of
`2026-09-07-library-admin-design.md` in full. Builds on the Library tab
kit shipped in 0.19.0 (rail, hash state, table, paging, title drawer).

## Goal

Replace the admin Requests tab (a pending-approvals list, a request list
that moved to Library in 0.19.0, and the auto-approve rules) with a tab
that answers "what did people ask for, who, and what happened to it":
every user request with its history, approve and deny with an inline
reason, reopen, per-user monthly quotas that are shown and enforced, and
the auto-approve rules where they belong.

## Decisions taken

| Question | Decision |
|---|---|
| Which requests | Only requests made by SPA users (`user_requests`). Automatic sources (Seerr, Trakt, MDBList, Suggestarr, rules) stay visible in the Library tab as requester "auto" |
| Quotas | Shown per user on this tab and enforced at request creation. The cap is edited on the Users tab only |
| Admin approve over quota | Always works; an admin decision is explicit. The row shows an amber hint |
| Auto-approve users at the cap | Their new requests are created as pending with a note, not approved |
| Actions | Approve, Deny (inline reason), Reopen a denied request. No bulk bar; no delete of request rows (history is kept) |
| Drawer | Row click opens the same title drawer as Library. The drawer gains "Forget request (keep files)" next to Purge, closing the 0.19 leftover |

## 1. Data and endpoints

### `GET /ui/api/admin/requests` (admin)

Params: `view` (`pending, approved, denied, all`), `user` (user id), `type`
(`movie, series`), `added` (`24h, 7d, 30d`), `q` (title or imdb id
substring, LIKE-escaped), `sort` (`created, reviewed, user, title`),
`order`, `page`, `per_page` (default 50, max 200). Unknown values are
ignored. Returns `{rows, total, page, per_page}`.

Row fields: `id, imdb_id, tmdb_id, title, media_type, seasons, status,
note, created_at, reviewed_at, user_id, username, reviewer` (username or
null), `library_status` (`requests.status` for the imdb id, or null when
the title is not in the library).

Implementation: new `requests_admin.py` with `list_requests(filters) ->
(rows, total)` and `view_counts() -> {view: count}`, the same shape as
`library_admin`: one SELECT over `user_requests` joined to `users` twice
(requester, reviewer) and left-joined to `requests` for the library
status, wrapped so views and filters reference the computed columns, plus
a COUNT with the same WHERE. Views: `pending`, `approved`, `denied` by
status, `all` unfiltered. Default sort newest requested first; the
`pending` view sorts oldest first so the longest wait is on top. New index
`user_requests(status, created_at DESC)`.

`GET /ui/api/admin/requests/views` returns the four counts.

### `GET /ui/api/admin/quotas` (admin)

One row per enabled user with role other than admin: `user_id, username,
used, limit, remaining, unlimited, resets_at, auto_approve, paused`
(`paused` is true when `auto_approve` is set and `used >= limit` with a
non-zero limit). Built from `quota.get_quota` per user, ordered by
username.

### Enforcement

In the request-creation route (the SPA's request endpoint that calls
`db.create_user_request`): for a non-admin user with a non-zero cap and
`used >= limit`, return `409 {"error": "quota reached", "used", "limit",
"resets_at"}` and create nothing. For an auto-approve user at the cap the
request is still recorded, as `pending`, with the note
"auto-approve paused: monthly quota reached", and nothing is kicked off.
Admins are never limited. The check lives in `quota.allows(user) ->
(ok: bool, info: dict)` so the route stays thin and the rule has one unit
test.

### Actions

Existing: `POST /ui/api/user-requests/<id>/approve`,
`POST /ui/api/user-requests/<id>/deny` (JSON `{note}`), unchanged.

New: `POST /ui/api/user-requests/<id>/reopen` (admin): a `denied` request
returns to `pending` with `reviewed_by`, `reviewed_at` and `note` cleared;
any other status returns `{ok: false, message}`. Implemented as
`db.reopen_user_request(req_id) -> bool`.

Removed: `GET /ui/api/requests/all` and `api.requestsAll`, orphaned since
0.19.0.

## 2. The Requests tab

Layout mirrors Library: rail plus main column; the whole state (view,
filters, sort, page, open) lives in the hash after `#requests?`.

**Rail.** Views with counts: Pending, Approved, Denied, All. Filters:
search, user `Select` (every user by username), type `Select`, added
`Select`, and Clear filters when any is set.

**Table.** Columns: title (type icon, imdb id under it); user; requested;
status pill; library (the title's library status pill, or muted "not in
library"); reviewed (reviewer and date, muted); note (truncated, full text
in the title attribute). Sortable headers: title, user, requested,
reviewed. Fifty rows a page, server side, with the page-size select and
the same paging strip as Library.

**Row actions** in the last column:

| Status | Actions |
|---|---|
| pending | Approve; Deny, which swaps the cell for an inline text field with Confirm and Cancel (note optional) |
| denied | Reopen; Approve |
| approved | none |

Approve on a user whose quota is reached shows an amber "over quota" hint
beside the button and still works. Every action shows its result inline
(`{ok, message}` style, as in the Library drawer) and refetches the table
and the rail counts.

**Drawer.** Clicking the title opens `TitleDrawer` for that imdb id
(`#requests?open=<imdb>`); a title not in the library shows the drawer's
404 message. `TitleDrawer` gains a secondary "Forget request (keep files)"
button next to Purge, calling the existing
`POST /ui/api/requests/<id>/delete` with its own confirmation; it prunes
the selection like Purge does.

**Below the table, two cards** in the Settings card style:

- Quotas: one line per user with used, cap, remaining and the reset date;
  unlimited users read "unlimited"; a user at or over the cap gets the
  count in red and "auto-approve paused" when it applies. A link "Edit
  quotas in Users" to `#users`.
- Auto-approve: the genre rules and favourite-actor editor moved over
  unchanged, with Run now.

**Empty states** say what the view means: "No requests waiting for
review", "No approved requests yet", "Nothing denied", "No one has
requested anything yet".

## 3. What changes elsewhere

- `frontend/src/pages/admin/Requests.tsx` is replaced; its pending panel
  becomes the Pending view and its auto-approve panel moves under the
  table.
- The user-facing Requests page shows the quota message from a 409 under
  the request control instead of a generic error; its quota card is
  unchanged.
- `AdminLayout` already derives the tab from the hash up to `?`.
- README admin row and CHANGELOG updated.

## 4. Testing

Backend: `list_requests` against a seeded set (three users, every status,
movie and series, one user over quota) for each view, filter, sort and the
paging math; `view_counts` matches; the quotas endpoint rows including
`paused` and `resets_at`; `quota.allows` unit tests (unlimited, under,
at cap, admin, auto-approve at cap); the creation route's 409 and the
pending downgrade on source text; `reopen_user_request` clears the
reviewer and note and refuses a non-denied row; the reopen route on source
text; source-text checks that the removed route is gone.

Frontend: rail views switch the query and update the hash; filters
restore from the hash; inline deny posts the note and Cancel restores the
row; Reopen and Approve appear only on the right statuses; the over-quota
hint renders; the Quotas card marks a user at the cap and shows the pause;
the auto-approve editor still saves and runs; the drawer opens from a row;
the drawer's Forget button confirms, posts and prunes; the user page shows
the quota message on 409.

## 5. Delivery

One plan, six tasks: (1) `requests_admin.py`, the index, the list and
views endpoints; (2) `quota.allows`, enforcement in the creation route,
the quotas endpoint, the reopen helper and route, removal of the orphaned
route; (3) frontend types, hash state, rail, table and paging; (4) row
actions with inline deny, drawer wiring, the Forget button; (5) Quotas
card, auto-approve move, the user-page quota message; (6) tab replacement,
docs, changelog. Subagent-driven with an opus whole-branch review;
released as 0.20.0 on request.

## Risks

Enforcement is the only behaviour change users can feel: a user with a
cap set today who is already over it will be refused from the first
deploy. The Users tab shows every cap, so an operator can check before
upgrading; the default cap is 0 (unlimited), so an install that never set
one is unaffected. Rollback is a redeploy.
