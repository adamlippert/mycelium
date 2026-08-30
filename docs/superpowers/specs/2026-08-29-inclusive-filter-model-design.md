# C1: Inclusive filter model (engine)

**Date:** 2026-08-29
**Status:** draft, awaiting review
**Scope:** C1 of two. C2 (rules-editor UI) is recorded at the end and is not
covered here. C1 ships fully functional, edited as plain comma-separated text rows.
**Supersedes:** the abandoned exclusive-model work (`feat/ranking-and-limits`,
`feat/source-type-filter-states`, both retired).

## Problem

Filtering today is twelve booleans and lists feeding a sequential chain in
`streams.rank_streams`. Four defects, each verified against the code.

### 1. The chain is order-dependent

Every filter self-disables against the pool **as it stands at that moment**:

```python
filtered = [s for s in candidates if not _BLURAY_RE.search(...)]
if filtered:
    candidates = filtered          # pool shrinks here
else:
    log.warning("Only BluRay candidates available; allowing them")
```

Because each filter both reads and rewrites `candidates`, the result depends on
the order the filters happen to be written in. Excluding BluRay before REMUX can
give a different surviving set than the reverse. Nothing documents the order and
nothing tests it.

### 2. The source-type regexes overlap silently

```
release                              REMUX  BLURAY
Dune.2160p.UHD.BluRay.REMUX.HEVC      True    True
Movie.1080p.BDRip.x264               False    True
Movie.1080p.BDRemux.x264              True   False
```

`_BLURAY_RE` matches `bluray|blu-ray|bdrip|brrip` and `_REMUX_RE` matches
`remux|bdremux`. A `BluRay.REMUX` release matches both, so `EXCLUDE_BLURAY`
silently drops remuxes the user never asked to drop. The overlap is partial, not
total: `BDRemux` escapes the BluRay filter because that token is absent from the
alternation. Nothing in the UI hints at any of this.

### 3. `QUALITY_PREFERENCE` is not about quality

`_QUALITY_PATTERNS` holds `2160p / 1080p / 720p / 480p`. `Stream.quality` holds a
**resolution**, and `QUALITY_PREFERENCE` (default `1080p,2160p,720p`) is a
resolution preference. Source type (remux, WEB-DL, cam) is expressed separately
as booleans. The name has been wrong long enough that it appears in the UI, the
README and `.env.example`. This is a migration hazard: `QUALITY_PREFERENCE` maps
to the `RESOLUTION_*` rows, not the `SOURCE_*` ones.

### 4. The model can only subtract

Every control is a negation (`EXCLUDE_*`) or a soft nudge (`PREFER_*`). There is
no way to say "only these". Adding one more attribute means adding two more
booleans, and the settings page is already twelve opaque switches.

## The model

Four states per category, matching AIOStreams.

| State | Effect |
|---|---|
| `included` | Escape hatch. Checked first, across all categories. A match keeps the stream regardless of every other rule, and short-circuits. |
| `required` | If the list is non-empty and the stream does not match, mark for drop. |
| `excluded` | If the stream matches, mark for drop. |
| `preferred` | Never filters. Supplies sort ranking only. Ordered. |

`preferred` deliberately has no rescue power. This is the decision that sank the
previous plan: if `preferred` rescued, migrating `PREFER_WEBDL=true` would grant
WEB-DL releases an override they never had, and a WEB-DL remux would start
surviving `EXCLUDE_REMUX`. Keeping `included` separate costs a fourth state to
explain and buys an exactly behaviour-preserving migration.

`included` is powerful and easy to misuse: `included: atmos` will rescue a CAM
release that happens to carry Atmos. The UI (C2) must say so plainly.

### Evaluation, and why it is order-independent

```
1. any category has an `included` match          -> KEEP, short-circuit
2. per category: `required` non-empty, no match  -> mark drop
3. per category: `excluded` match                -> mark drop
4. if every candidate is marked                  -> relax all non-strict
                                                    categories, log which
```

Each category computes its verdict **against the full pool**, independently.
The drops are then applied together. No category ever sees a pool another
category has already shrunk, which removes defect 1 by construction rather than
by convention.

Step 4 is where soft-by-default lives. Every category self-disables rather than
return nothing, matching the existing house rule in `rank_streams`. A category
with its `*_STRICT` toggle on is exempt: it holds even if that empties the pool,
which is how `STRICT_NO_CAM` behaves today and the only hard filter that exists.

### Unknown is a value, not an absence

**Absence of data is not evidence of absence.** A release that does not say
"English" is not a release without English audio; untagged English is the
default in release naming.

This is not a new invention. `rank_streams` already applies it twice:

```python
if s.seeders == 0 or s.seeders >= min_seeders     # unknown seeders pass
if s.size_gb == 0.0 or s.size_gb <= max_size_gb   # unknown size passes
```

C1 generalises it. Every category gains an `unknown` sentinel, assigned when no
value is detectable. Rules:

- `required` does **not** drop an `unknown` stream. "Did not say" is not "does
  not match".
- `unknown` can be named explicitly in `excluded` by a user who wants only
  positively-tagged releases.
- `unknown` sorts below any `preferred` match and above a positively
  non-preferred value. This is exactly the existing `_lang_score` ordering and
  is already pinned by tests.

This is mandatory, not optional, and language proves why: `zilean.LANGUAGES_AVAILABLE`
is `False` because Zilean's payload carries no language data at all. No shared
parser can fix that. Without this rule, a `required` language would drop every
Zilean result permanently.

### Categories

| Category | Values |
|---|---|
| `resolution` | 2160p, 1080p, 720p, 480p, unknown |
| `source` | remux, bluray, bdrip, brrip, webdl, webrip, web, hdrip, dvdrip, dvd, hdtv, satrip, tvrip, r5, ppvrip, ts, tc, scr, cam, unknown |
| `encode` | hevc, avc, av1, xvid, divx, unknown |
| `visual_tag` | hdr10, hdr10plus, dv, dv_only, hlg, 10bit, sdr, imax, unknown |
| `audio_tag` | atmos, truehd, dts_hd, dts, ddp, dd, aac, flac, opus, unknown |
| `audio_channels` | 2.0, 5.1, 7.1, unknown |
| `language` | the 34 codes in `streams.LANGUAGE_CODES`, plus unknown |

`source` splits what is today one overlapping pair into distinct, non-overlapping
values, fixing defect 2. `bluray` no longer implies `bdrip`, and `bdremux`
resolves to `remux`.

`dv_only` is synthetic: Dolby Vision with no HDR10 base layer, which is what
`EXCLUDE_DV_P5` means today. No plain tag expresses it, so it stays computed.

### Storage: four plain lists per category

**Decided.** Each category gets four ordinary comma-separated list settings plus
one strict toggle:

```
RESOLUTION_PREFERRED = "2160p,1080p"
RESOLUTION_EXCLUDED  = "480p"
RESOLUTION_REQUIRED  = ""
RESOLUTION_INCLUDED  = ""
RESOLUTION_STRICT    = false
```

Thirty-five settings. Every list is an ordinary `_LIST_KEYS` entry, so:

- parsing is unchanged, and order inside `preferred` survives the comma split;
- per-value validation reuses the `_LANGUAGE_LIST_KEYS` pattern shipped in 0.6.6;
- the settings page renders each one with **no new UI code**, because
  `settings.py` infers the widget from registry membership
  (`"list" if key in _LIST_KEYS`).

The rejected alternative was one packed row per category
(`RESOLUTION_RULES = "2160p=preferred,480p=excluded"`, fourteen settings). It
was rejected because `key=value` exists nowhere in this codebase, so it needs a
new parser, a new validator including precedence for a value named twice with
conflicting states, and a new UI widget kind. That last point is decisive: a
packed row belongs to no registry, falls through to `"str"`, and renders as an
unvalidated free-text box unless C1 also builds UI, which is the work C1 exists
to defer.

The accepted cost is a long settings page until C2 lands, roughly 35 added lines
in `.env.example`, and 28 bookkeeping entries in `_LIST_KEYS`. None of those can
select the wrong release. A buggy parser can.

### Sorting

An ordered criteria list, each entry naming a category whose `preferred` list
supplies the ranking:

```
SORT_ORDER = season_pack,resolution,cached,language,quality,encode,
             visual_tag,audio_tag,seeders,size
```

Built natively in C1. The retired `feat/ranking-and-limits` branch had a version
of this, but it is being rebuilt rather than cherry-picked so no part of the
rejected approach is resurrected.

## Explainability: every rejection carries its reason

**Decided.** The engine must never discard a candidate silently.

Today `rank_streams` rebinds `candidates` on every filter pass, so a rejected
release is unreferenced and its reason exists only as an unstructured
`log.warning` that names no release. Four candidates in, one out, and nothing
records which of three different rules removed each of the other three.

### Required shape

The engine walks the pool **once** and attaches a verdict to every candidate,
then derives survivors from the verdicts. It does not rebind the list.

```python
@dataclass(frozen=True)
class Verdict:
    kept: bool
    rule: str | None      # "SOURCE_EXCLUDED", "MIN_SEEDERS", ...
    value: str | None     # the matched value, e.g. "remux"
    relaxed: bool         # this rule self-disabled to avoid an empty pool
```

`relaxed` is not optional bookkeeping. A category that switched itself off to
avoid returning nothing is exactly the event a user needs to see, and today it
is a log line they will never read.

### Public surface

The internal engine always computes verdicts. Two entry points expose them:

- `rank_streams(...) -> list[Stream]` keeps today's signature, so the two
  existing call sites (`torrentio.py:110`, `scrapers.py:150`) are untouched.
- `rank_streams_explained(...) -> tuple[list[Stream], list[Verdict]]` returns
  both. `rank_streams` becomes a thin wrapper that discards the verdicts.

Structured logging: one line per drop at DEBUG, one summary line at INFO
(`kept 1 of 4; SOURCE_EXCLUDED dropped 2, MIN_SEEDERS dropped 1`).

### Deliberately deferred

Persisting verdicts for later display is C2's decision, between re-running the
ranker and storing the last decision per item. That is a storage question and can
be added without touching the loop. Producing the verdicts cannot be, which is
why it is here and not there.

## Source capability map

**Included on my recommendation, not an explicit instruction. Strike it if you
disagree.**

`zilean.LANGUAGES_AVAILABLE = False` is today the only statement of what a
scraper can and cannot supply, and it is a one-off. Zilean sends no language
data at all, and probably no audio tags or channels either, so a `REQUIRED` rule
in those categories would silently discard every Zilean result forever. That is
the same class of defect as the Debridio language bug, which went unnoticed
through several releases.

Each scraper module declares which categories it can populate:

```python
CAPABILITIES: frozenset[str] = frozenset({"resolution", "source", "encode"})
```

`rank_streams` logs a warning when a `REQUIRED` rule names a category that a
contributing source cannot populate. C2 later uses the same map to annotate or
grey out those rules.

The map is populated as tag parsing is written, not guessed up front. Only the
Zilean language entry is known today.

## Migration

Defaults below are the shipped values, verified in `config.py`.

| Current setting | Default | Becomes |
|---|---|---|
| `QUALITY_PREFERENCE` | `1080p,2160p,720p` | `RESOLUTION_PREFERRED`, order kept. **Name trap: this is resolution.** |
| `ALLOW_4K` | `true` | when false, `2160p` joins `RESOLUTION_EXCLUDED` |
| `EXCLUDE_REMUX` | `true` | `SOURCE_EXCLUDED` gains `remux` |
| `EXCLUDE_BLURAY` | `false` | `SOURCE_EXCLUDED` gains `bluray,bdrip,brrip` (remux no longer swept up) |
| `EXCLUDE_CAM` | `true` | `SOURCE_EXCLUDED` gains `cam,ts,tc,scr,r5,ppvrip` |
| `STRICT_NO_CAM` | `false` | `SOURCE_STRICT` |
| `EXCLUDE_DV_P5` | `true` | `VISUAL_TAG_EXCLUDED` gains `dv_only` |
| `PREFER_WEBDL` | `true` | `SOURCE_PREFERRED` gains `webdl` |
| `PREFER_HEVC` | `true` | `ENCODE_PREFERRED` gains `hevc` |
| `AUDIO_LANGUAGE_PREFERENCE` | *(empty)* | `LANGUAGE_PREFERRED`, order kept |
| `EXCLUDE_LANGUAGES` | *(empty)* | `LANGUAGE_EXCLUDED`. **Behaviour change, see below.** |
| `MIN_SEEDERS` | `3` | unchanged, not a category |
| `MAX_SIZE_GB` | `0` | unchanged, not a category |
| `EXCLUDE_UNDERSIZED_RELEASES` | `true` | unchanged, not a category |

Because `preferred` never rescues, `PREFER_WEBDL` and `PREFER_HEVC` migrate with
identical behaviour.

### The one behaviour change

`EXCLUDE_LANGUAGES` has an undocumented rescue today: a release in an excluded
language survives if it **also** carries a preferred one.

```python
any(lang in s.languages for lang in exclude_langs)
and not any(lang in s.languages for lang in pref_langs)
```

Under the new model `excluded` means excluded, and `preferred` cannot rescue.
A release tagged `ru,en` with `ru=excluded` will be dropped where today it
survives.

Migrating those preferred languages to `included` would preserve it exactly, but
`included` short-circuits **all** categories, so it would also start rescuing
English-tagged CAM releases. That is worse. The recommendation is to accept the
narrower behaviour and document it.

Blast radius is nil for default installs: both language settings ship empty, so
this rescue only ever fires for users who configured both.

## What C1 does not do

Deliberately out of scope, from the AIOStreams relevance pass: stream-type
filtering (torrents only, via TorBox), subtitle filtering (separate pipeline),
release-group / keyword / regex filters, the deduplicator matrix (already
deduped on `info_hash`), per-addon result limits, age and bitrate (neither is
parsed), and variants / config-expression inheritance (multi-tenant features
with no analogue here).

## Risks

**Tag parsing is the bulk of the work.** Audio tags, channels, and most visual
tags are parsed nowhere today. That is roughly 30 new patterns, and pattern bugs
will look like ranking bugs. Every pattern needs a test with a real release name.

**Silent scope loss.** Any category where a scraper cannot supply data behaves
like language-on-Zilean. The `unknown` rule covers it, but each new category
needs an explicit answer to "which sources can actually populate this?"

**Migration is one-way.** Once the new rows exist, the old booleans stop being
read. A migration that misreads a setting is a silent behaviour change in the
user's download picks, which is exactly the class of bug that is hardest to
notice. The migration needs its own test per row of the table above.

## Setting names, in full

Seven categories, each with four state lists plus one strict toggle. Thirty-five
settings.

```
RESOLUTION_PREFERRED      SOURCE_PREFERRED        ENCODE_PREFERRED
RESOLUTION_EXCLUDED       SOURCE_EXCLUDED         ENCODE_EXCLUDED
RESOLUTION_REQUIRED       SOURCE_REQUIRED         ENCODE_REQUIRED
RESOLUTION_INCLUDED       SOURCE_INCLUDED         ENCODE_INCLUDED
RESOLUTION_STRICT         SOURCE_STRICT           ENCODE_STRICT

VISUAL_TAG_PREFERRED      AUDIO_TAG_PREFERRED     AUDIO_CHANNELS_PREFERRED
VISUAL_TAG_EXCLUDED       AUDIO_TAG_EXCLUDED      AUDIO_CHANNELS_EXCLUDED
VISUAL_TAG_REQUIRED       AUDIO_TAG_REQUIRED      AUDIO_CHANNELS_REQUIRED
VISUAL_TAG_INCLUDED       AUDIO_TAG_INCLUDED      AUDIO_CHANNELS_INCLUDED
VISUAL_TAG_STRICT         AUDIO_TAG_STRICT        AUDIO_CHANNELS_STRICT

LANGUAGE_PREFERRED   LANGUAGE_EXCLUDED   LANGUAGE_REQUIRED
LANGUAGE_INCLUDED    LANGUAGE_STRICT
```

Eleven settings are retired by the migration: `QUALITY_PREFERENCE`, `ALLOW_4K`,
`EXCLUDE_REMUX`, `EXCLUDE_BLURAY`, `EXCLUDE_CAM`, `STRICT_NO_CAM`,
`EXCLUDE_DV_P5`, `PREFER_WEBDL`, `PREFER_HEVC`, `AUDIO_LANGUAGE_PREFERENCE`,
`EXCLUDE_LANGUAGES`. Three are untouched because they are not categories:
`MIN_SEEDERS`, `MAX_SIZE_GB`, `EXCLUDE_UNDERSIZED_RELEASES`.

### Why the source category is not called `quality`

`QUALITY_PREFERENCE` already exists and holds a **resolution**. A new
`QUALITY_PREFERRED` would sit two characters away from it while meaning
something entirely different, which is a defect waiting to be filed. The
category is named `SOURCE_*`, and the migration deletes the misnomer.

`LANGUAGE_*` is likewise distinct from the retired `AUDIO_LANGUAGE_PREFERENCE`.

### Stale values left in .env

A retired key sitting in a user's `.env` becomes silently inert after upgrade.
Startup must log a warning naming each retired key it still finds, and what
replaced it. Without this, a user who set `QUALITY_PREFERENCE` in `.env` sees
their preference stop working with no message anywhere.

## C2, recorded

A per-category editor replacing the text boxes. Each category renders every
possible value as a row with a single control offering five choices: **No rule**,
Preferred, Excluded, Required, Included. That is the dropdown that makes the
thirty-five text fields disappear from view: the user picks from a fixed list
and can no longer type a value that does not exist.

Two requirements a plain dropdown does **not** satisfy, and which C2 must
handle:

- **Order matters for Preferred.** `1080p` before `2160p` is a different
  preference from the reverse. State alone does not capture it, so preferred
  values need drag-to-reorder or an explicit priority number.
- **Included needs a visible warning.** It overrides every other rule across
  every category, so marking `atmos` as Included will keep a cam rip that
  happens to carry Atmos. The control must say so at the point of choosing.

C1 is robust, C2 is what makes it intuitive. C2 must not begin before C1's data
model is settled.
