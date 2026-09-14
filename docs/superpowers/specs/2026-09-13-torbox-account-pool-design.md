# TorBox account pool: several API keys as equal peers

Date: 2026-09-13. Status: approved in conversation, awaiting file review.
Replaces the "provider substitution" item of the Field Report batch B with
what the user actually wants: more than one TorBox account, used as equal
peers, to lift the add budget, spread playback across accounts, and keep
playing when one key is rate-limited or broken. Absorbs the batch B
"debrid-aware metrics" item as a side effect.

## Goal

An admin adds a second (third, ...) TorBox API key in Settings. From then
on new torrents are added to the least loaded healthy account, every play
of a title comes from the account that holds its torrent, and a broken or
disabled account hands its titles over on their next play. A single-key
install behaves exactly as today after the upgrade, with no action needed.

## Decisions taken

| Question | Decision |
|---|---|
| What the extra keys lift | All three: the sixty uncached adds per hour per key, evening playback throughput, and resilience when a key fails |
| Account roles | Equal peers. Any enabled account may hold any torrent; there is no primary |
| Copies | One home per torrent. A torrent is added to exactly one account; every play of that title uses that account. Throughput spreads across titles, not within one |
| Where the choice happens | At the first play (or the first add in fixed mode). A play never rebalances |
| Configuration | A table of accounts with label, key and enabled flag, edited on a Settings section; the existing `TORBOX_API_KEY` becomes account 1 ("main") |
| Client shape | The existing module keeps its functions; account-bound ones take an `account_id`; per-account state is keyed by id. A new `torbox_pool` module owns the accounts and the choice |
| Cache checks | Account-free. TorBox's cache is global, any key answers |

## 1. Data

### `torbox_accounts`

```
id          INTEGER PRIMARY KEY AUTOINCREMENT
label       TEXT NOT NULL UNIQUE
api_key     TEXT NOT NULL
enabled     INTEGER NOT NULL DEFAULT 1
created_at  TEXT NOT NULL
```

Migration on first start: when the table is empty and a `TORBOX_API_KEY`
is configured (env or settings), insert it as id 1, label `main`. Account
1 stays bound to the `TORBOX_API_KEY` setting: saving that setting
updates row 1's key, and row 1's key is what `settings.get("TORBOX_API_KEY")`
returns, so the wizard, the Settings test button and every existing
single-key path keep working. Extra accounts live only in the table.

### `virtual_items.torbox_account INTEGER`

The id of the account holding the item's torrent; null when `torbox_id`
is null. Migration sets it to 1 for every row whose `torbox_id` is not
null. `torbox_id` and `torbox_account` are written and cleared together:
`db.set_virtual_torbox(token, torbox_id, account_id)` replaces
`update_virtual_torbox_id` for writes; `update_virtual_item_upgrade` clears
both.

### `createtorrent_log.account INTEGER`

Which key an add went through, so each account's hourly budget is counted
on its own. Migration adds the column with default 1.

## 2. `torbox_pool.py`

```
accounts(enabled_only=True) -> list[Account]      Account = (id, label, api_key, enabled)
account(account_id) -> Account | None             disabled accounts are still returned
choose_for_add() -> Account                       see below
mark_429(account_id)                              called by the client on a 429
mark_auth_failure(account_id)                     called on 401 or 403
health(account_id) -> {rate_limited_until, auth_failed_at, budget_left, torrents}
invalidate()                                      after Settings changes
```

Accounts are read from the table and cached for sixty seconds; Settings
changes call `invalidate()`. In-memory health per account: last 429 time,
last auth failure time. Both are process state, forgotten on restart, as
the single `_last_429_at` is today.

`choose_for_add()`:

1. Candidates: enabled accounts, minus those with a 429 in the last ten
   minutes, minus those with an auth failure in the last ten minutes,
   minus those with fewer than two uncached adds left in the hour
   (`createtorrent_usage(account_id)`).
2. Pick the candidate holding the fewest items with a non-null
   `torbox_account` equal to it (`db.count_items_by_account()`), ties by
   most budget left, then lowest id.
3. No candidate: return the enabled account whose 429 is oldest (or, if
   none has one, the lowest id). A burst then degrades to today's
   behaviour, a 429 and a cooldown, rather than a hard failure.

The choice is logged at info level with the label and the reason
("fewest torrents", "fallback: every account limited").

## 3. `torbox.py`

Every function that talks to an account takes `account_id: int` as its
first argument and builds the header from `torbox_pool.account(account_id)`:
`add_magnet`, `list_torrents`, `find_by_hash`, `find_by_id`,
`delete_torrent`, `wait_until_ready`, `get_user_info`, `get_usage_summary`,
`title_exists`, `invalidate_mylist_cache`, `createtorrent_usage`,
`last_429_at`. `check_cached` and `check_cached_files` take no account and
use the lowest enabled id's key (any key answers a cache check).

Per-account state replaces the module globals: the mylist cache and its
locks, the last 429 time, and the createtorrent slot reservation are
dicts keyed by account id. `add_magnet` records the account on the
`createtorrent_log` row and calls `torbox_pool.mark_429` on a 429 and
`mark_auth_failure` on 401 or 403. A `_headers()` call without an account
no longer exists; a guard test greps the module for `Bearer` outside the
account-aware builder.

Three places outside the client build a TorBox header or `requestdl` call
themselves and move into it: `strm_generator._get_stream_url` (becomes
`torbox.request_download_link(account_id, torrent_id, file_id)`),
`health.py` line 106 (the TorBox ping, which now pings every enabled
account), and the web player plugin's `requestdl` (uses the same client
function with the account chosen for its add).

## 4. The play path (`catbox.materialize`)

- **Item already homed** (`torbox_id` and `torbox_account` set): every
  call uses that account. Unchanged flow otherwise.
- **First play / no home:** before adding, look the hash up in every
  enabled account's list (`find_by_hash(account_id, hash)` per account,
  cached lists). A hit adopts that account as home with no add. Otherwise
  `choose_for_add()` picks the home, the add goes there, and
  `set_virtual_torbox(token, torbox_id, account_id)` stores both.
- **Re-homing:** when the home account is disabled, or any call to it
  answers 401 or 403, or `find_by_id` says the torrent is gone, the play
  clears id and account and re-enters the first-play path. A 429 from the
  home does not re-home: the torrent is still there, the play backs off
  as today.
- **Fixed mode and the other adders** (`processor` in non-catbox mode,
  `monitor._search_and_add_season`, `catchup`, `retry_queue`,
  `upgrader`, the web player): call `choose_for_add()` once, then pass
  that account to every call of the operation, including the download
  link. They store nothing.

## 5. Jobs

- **Idle release** (`catbox.release_idle`): deletes each idle item's
  torrent through the item's home account; clears id and account.
- **Hourly id check** (`catbox.reconcile_torbox_ids`): fetches each
  enabled account's list once, checks each item against its home's list.
  A missing id whose hash appears in another enabled account's list is
  re-homed there; otherwise cleared. An account whose list is empty or
  fails is skipped for that run (its items are left alone), reported per
  account in the result.
- **Swap, upgrade, purge:** clear id and account together (they already
  clear the id).
- **Quota warning:** runs per account, labelled.

## 6. Admin surfaces

- **Settings, section "TorBox accounts"** (custom component): rows with
  label, masked key, enabled toggle, Test (the existing TorBox tester
  against that key), Remove. Add row: label and key. Removing an account
  that still homes items is refused with the count ("disable it; its
  titles move on their next play"). Account 1 cannot be removed, only its
  key edited through the existing setting. Endpoints, admin only:
  `GET /ui/api/torbox-accounts`, `POST /ui/api/torbox-accounts`
  (`{label, api_key}`), `POST /ui/api/torbox-accounts/<id>`
  (`{label?, enabled?, api_key?}`), `DELETE /ui/api/torbox-accounts/<id>`,
  `POST /ui/api/torbox-accounts/<id>/test`.
- **Overview, TorBox card:** one column per enabled account (label):
  uncached adds against sixty, cached count, torrents held, last 429 as a
  relative time. The status strip's "TorBox adds" cell shows the total and
  turns amber when any single account is at forty-five or more; its reason
  line names that account. `/ui/api/overview` gains
  `torbox.accounts: [{id, label, adds: {uncached, cached, limit, resets_in_sec}, torrents, last_429_at}]`.
- **Library drawer:** the release card shows the home account's label next
  to the TorBox id.
- **Health rows:** "TorBox" becomes one row per account ("TorBox main",
  "TorBox second"), each pinging with its own key; an auth failure on one
  account is red for that row only.
- **Metrics:** `torbox_torrent_count`, `torbox_total_bytes`,
  `catbox_active_in_torbox` and `service_up{service="torbox"}` gain an
  `account` label. A new gauge `torbox_createtorrent_used{account}` exports
  each account's uncached adds in the current hour.
- **Logs:** every add, adoption and re-home line names the account label.

## 7. Behaviour and edge cases

- A single-key install after the upgrade: one account, every choice picks
  it, every surface shows one column or row. Nothing else changes.
- A key edited in Settings for account 1 keeps its id; items stay homed.
  A key replaced with a different account's key is the admin's problem,
  as it is today: the ids stop matching and the hourly check clears them.
- Disabling an account does not delete its torrents; they stay on TorBox
  until its items re-home and the idle release deletes them through the
  old account when it is enabled again, or never if it stays disabled.
  The Settings row says so.
- Two plays of the same unhomed title at once: the token lock serialises
  them as today, so the second sees the home the first stored.
- Every account limited: `choose_for_add()` still returns one; the add
  gets a 429 and today's cooldown applies. The log names it as a
  fallback so the admin sees the pool is exhausted.
- The migration is idempotent: an existing `torbox_accounts` row 1 is
  left alone; items with an account keep it.

## 8. Testing

Backend (own `_isolated_db` fixtures, no network, `requests` faked):

- `torbox_pool`: selection by fewest torrents, tie-breaks, exclusion for
  429, auth failure and low budget, the all-excluded fallback, the
  sixty-second cache and `invalidate()`.
- `torbox`: the header carries the given account's key; per-account
  mylist caches and 429 marks do not bleed; `createtorrent_log` rows carry
  the account; `createtorrent_usage(account_id)` counts only that
  account; the guard that no header is built without an account.
- Play path: adoption from another account's list without an add; first
  add stores id and account together; re-home on 403, on a disabled
  account and on a gone torrent; no re-home on 429; the fixed-mode adders
  pass one account through an operation.
- Jobs: idle release deletes through the home; the id check per account,
  re-homing by hash, an unreachable account skipped and reported.
- Migration: an existing database gets account 1 from the current key,
  every homed item marked, `createtorrent_log.account` defaulted; running
  it twice changes nothing.
- Endpoints: add, edit, disable, test, refuse removal while homed, account
  1 not removable; admin only (source text).
- Metrics: the account label on the four gauges and the new gauge.

Frontend (`vitest`): the accounts section (list, add, toggle, test result,
refused removal message), the Overview TorBox card with two accounts and
the amber rule on one account at forty-five, the drawer label.

Mutation checks on every new branch, as usual.

## 9. Delivery

Subagent-driven, in this order, each task reviewed:

1. Data and pool: table, migration, `torbox_pool`, `db` helpers.
2. Client: account-aware `torbox.py`, the three moved header sites, the
   guard test.
3. Play path and adders: `catbox.materialize`, fixed-mode adders, swap and
   upgrade clearing the account.
4. Jobs: idle release, id check, quota warning.
5. Endpoints and Settings section.
6. Overview, health rows, drawer label, metrics.
7. Docs: README, INTEGRATIONS, SCALING (a note on per-account budgets),
   changelog.

One opus whole-branch review, one fix wave, released as 0.29.0 on request.
Roughly two days.

## Risks

- The client signature change touches sixteen modules and their tests;
  the guard test and the type of `account_id` (an int, never optional on
  account-bound functions) keep a forgotten call site from passing
  silently.
- TorBox may count some limits per user rather than per key. If two keys
  belong to one TorBox user, the budget split is fiction; the Settings
  help text says keys must belong to separate accounts.
- The "fewest torrents" proxy for load ignores what is actually streaming.
  It is cheap and monotone; a later refinement can weigh recent plays per
  account from `egress_log` once the account is recorded there. Not in
  scope now.
