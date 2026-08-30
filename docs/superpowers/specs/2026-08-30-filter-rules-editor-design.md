# C2: Filter rules editor

**Date:** 2026-08-30
**Status:** draft, awaiting review
**Scope:** C2 of two. C1 (the engine) is complete on `feat/inclusive-filter-model`.
**Depends on:** `docs/superpowers/specs/2026-08-29-inclusive-filter-model-design.md`

## Problem

C1 replaced twelve booleans with 35 settings. The admin UI renders each one as a
row with a comma-separated text box:

```
RESOLUTION_PREFERRED   [1080p,2160p,720p                    ]
RESOLUTION_EXCLUDED    [                                    ]
RESOLUTION_REQUIRED    [                                    ]
RESOLUTION_INCLUDED    [                                    ]
RESOLUTION_STRICT      [x]
```

Thirty-five of those. The model is more expressive than the booleans it replaced
and the interface is worse: the user types values from a vocabulary the page
never shows, and `settings.set()` rejects a typo only after saving.

C1 was built to be robust. C2 is what makes it usable.

## What C2 is not

A "why was this release not picked" view. C1 produces a `Verdict` for every
rejected candidate and nothing displays it. Surfacing that needs a decision C1
deliberately deferred: persist verdicts, or re-run the ranker on demand. Re-running
means re-scraping, which is slow and rate limited against TorBox; persisting means
a new table and a retention policy. That is a subsystem, not a panel. It is
recorded here as possible future work and is out of scope.

## Layout

One panel per category. Four state rows per panel, each holding chips.

```
RESOLUTION                                       5 values   strict [ ]
  Preferred   [1080p x] [2160p x] [720p x]        + add v      up/down
  Excluded    (none)                              + add v
  Required    (none)                              + add v
  Included    (none)                              + add v   ! overrides everything

SOURCE                                          21 values   strict [ ]
  Preferred   [webdl x] [webrip x] [web x]        + add v      up/down
  Excluded    [remux x] [cam x] [ts x] [tc x]     + add v
              [scr x] [r5 x] [ppvrip x] [workprint x]
  Required    (none)                              + add v
  Included    (none)                              + add v   ! overrides everything

> AUDIO TAG              no rules set            10 values
> AUDIO CHANNELS         no rules set             4 values
> LANGUAGE               no rules set            35 values
```

### Why chips rather than a grid

Categories differ in size by a factor of seven: `resolution` has 5 values,
`source` 21, `language` 35. A layout with one row per value is comfortable for
the first and unusable for the last, and `language` is among the most likely to
be configured. Chips show only what the user has assigned, so an unused category
costs one line regardless of how large its vocabulary is.

### Collapse and overflow

A category with no rules in any state collapses to a summary line. After
migration from Mycelium's defaults, three of seven categories start empty, and
padding them out to twelve "(none)" rows would bury the four that carry rules.

Chips are capped at a COUNT, not a row count, and the remainder collapses behind
a "+N more" control that expands in place.

The distinction matters. Knowing how many chips fit on two rows requires
`getBoundingClientRect` in a live browser, and this project has no browser to
verify such a measurement against. A count behaves identically in a test, which
a measurement never would, so the cap is a constant: `CHIP_VISIBLE_LIMIT = 10`.

Ten is chosen so the shipped default is never truncated. `SOURCE_EXCLUDED` holds
eight values after a default migration, and a cap that hid part of the
out-of-the-box configuration would make every user click to see settings they
never chose. The control exists for the genuinely long case, such as excluding
sixteen of the twenty-one source values, where it shows ten and offers "+6 more".

Expansion is per state row, held in memory rather than on the container, so a
redraw cannot lose it. Expanding changes nothing about the rules, so it does not
write the hidden inputs or mark the form dirty.

### Reordering

The `up/down` control appears on the `Preferred` row and nowhere else. Order is
load-bearing there: `1080p` before `2160p` is a different preference, and the
sort key reads the list positionally. Order is meaningless for the other three
states, which are membership tests, so offering reorder there would imply a
semantics that does not exist.

Reordering uses buttons rather than drag and drop. The admin UI is served in an
iframe and is read on phones; drag targets are unreliable on touch, and buttons
are keyboard accessible for free.

### The Included warning

`Included` carries a persistent warning marker. It is the one control that can
surprise a user badly: it short-circuits every other rule in every category, so
marking `atmos` as included keeps a cam rip that happens to carry Atmos. That
behaviour was verified against the live engine during C1. The warning sits next
to the control because a user reaching for `Included` is not reading the docs.

## Data flow

**No new endpoint.** Each state keeps a hidden input named exactly as today:

```html
<input type="hidden" name="setting_RESOLUTION_PREFERRED" value="1080p,2160p,720p">
```

Chips are a view over those inputs and rewrite them on every change. The existing
`/ui/settings` handler loops over `setting_*` keys and calls `settings.set()`
unchanged.

Two properties follow, and both are the reason for this choice:

- C2 cannot break saving for the other fourteen setting groups, because it does
  not touch the save path.
- If the script fails to load, the page falls back to the current text boxes
  rather than presenting a dead interface.

The vocabulary for each key already arrives from the backend. `all_for_ui()`
emits `options` for every rule key, `hot_reload: true` for all 35, and the
existing renderer already special-cases a group by id (`arr_import`), so
`filter_rules` follows an established path rather than inventing one.

## Invalid values are surfaced, not hidden

A stored value absent from `options` renders as a struck-through chip that can be
removed but not re-added, with the reason on hover.

This makes a case C1 deliberately left quiet finally visible. A value arriving
from `.env` bypasses `settings.set()` validation: it warns once at startup and is
then kept and used, where it silently matches nothing. Someone who never reads
container logs has no way to discover it today.

## Language values

The picker displays `German (de)` and stores `de`. The engine and `.env` both
need the code; a dropdown of 35 bare codes is a puzzle rather than a picker.
Names come from a static code-to-name map in the JS, with the code shown as a
fallback for any code lacking a name.

## Files

| File | Responsibility |
|---|---|
| `static/admin/filter_rules.js` (new) | All C2 logic. Pure state functions with no DOM dependency, plus thin DOM wiring. |
| `tests/js/filter_rules.test.js` (new) | `node --test`, no dependencies. Covers the pure functions. |
| `templates/ui.html` | Roughly ten lines: a container, a script tag, and the branch that skips the generic table for `filter_rules`. |

`templates/ui.html` is already 2205 lines with every script inline and no test
coverage. Adding 250 lines of interactive logic there would be untestable by
construction, which is why the logic goes to its own file.

## Testing, and its limits

`node --test` covers the pure functions: order preserved through add and reorder,
duplicates rejected, serialization round-trips through the comma format, an
invalid value marked rather than dropped, and a value removed from one state
becoming available again in that category's `+ add` list.

Python covers what the backend must supply: `options` present and correct for all
35 keys, and the `filter_rules` group present with its 35 members.

**Nothing tests the DOM or a real browser.** No such harness exists in this repo
and C2 does not add one. Rendering bugs will not be caught by tests. This is
stated rather than implied, because a claim of coverage that does not exist is
worse than an honest gap.

## Risks

**The hidden-input contract is invisible.** If a later change alters how
`/ui/settings` parses form keys, C2 breaks silently and the failure looks like
"my filter settings do not save". The Python test asserting the group and its key
names is the guard; it must name the `setting_` prefix explicitly.

**Chip state and hidden inputs can drift.** They are two representations of one
value. The serialization tests are the defence, and the DOM wiring that keeps
them in sync is the untested part. Keeping that wiring to a single function that
rewrites all four inputs from one state object, rather than mutating them
individually, keeps the untested surface small.

**A category with a large vocabulary and many assignments is still tall.**
Excluding most of `source` produces eight or more chips even with the two-row
cap. Acceptable, and it degrades gracefully rather than breaking.
