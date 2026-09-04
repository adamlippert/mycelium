"""Per-resolution size caps, and which end of the size range wins a tie.

Ported from the feat/ranking-and-limits branch, which was written before the
four-state filter model replaced the old boolean settings and so never
merged. The two features it carried that never reached main:

  MAX_SIZE_GB_BY_RESOLUTION  a cap per resolution, so a library can take
                             large 4K files while keeping 1080p modest,
                             which one global MAX_SIZE_GB cannot express
  PREFER_SMALLER_FILES       the sort direction for the size term, whose
                             previous behaviour (smallest first) is the
                             default here
"""
import os
import sys

import pytest

os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import streams


def _stream(**kw):
    base = dict(name="n", title="t", info_hash="a" * 40, quality="1080p",
                seeders=10, size_gb=5.0, is_season_pack=False)
    base.update(kw)
    return streams.Stream(**base)


@pytest.fixture()
def settings(monkeypatch):
    """Resolve settings from a dict, so a test states only what it changes.

    streams.py imports settings inside each function, so patch the settings
    module itself rather than an attribute on streams."""
    import settings as settings_mod
    values = {}
    monkeypatch.setattr(settings_mod, "get", lambda k, d=None: values.get(k, d))
    return values


# -- parsing ------------------------------------------------------------------

def test_parses_a_comma_list_into_a_mapping():
    assert streams.parse_size_limits("2160p=60,1080p=15") == {"2160p": 60.0, "1080p": 15.0}


def test_accepts_a_list_as_well_as_a_string():
    """settings stores this as a list; .env supplies a string."""
    assert streams.parse_size_limits(["2160p=60", "720p=8"]) == {"2160p": 60.0, "720p": 8.0}


def test_malformed_entries_are_skipped_not_raised():
    """A bad setting must narrow nothing, not break ranking for every
    request that touches it."""
    assert streams.parse_size_limits("2160p=sixty,1080p=15") == {"1080p": 15.0}


def test_a_resolution_mycelium_never_produces_is_dropped():
    """Stream.quality says 2160p, never 4k, so a 4k= entry would silently
    cap nothing while looking configured."""
    assert streams.parse_size_limits("4k=60,1080p=15") == {"1080p": 15.0}


def test_empty_and_none_parse_to_nothing():
    assert streams.parse_size_limits("") == {}
    assert streams.parse_size_limits(None) == {}


# -- the caps in use ----------------------------------------------------------

def test_a_per_resolution_cap_applies_to_that_resolution_only(settings):
    settings["MAX_SIZE_GB_BY_RESOLUTION"] = ["1080p=10"]
    big_1080 = _stream(quality="1080p", size_gb=40.0)
    big_4k = _stream(quality="2160p", size_gb=40.0)
    small_1080 = _stream(quality="1080p", size_gb=5.0)

    kept = streams._apply_non_category_filters([big_1080, big_4k, small_1080], {})

    assert big_1080 not in kept, "the 1080p cap did not apply"
    assert big_4k in kept, "the 1080p cap wrongly applied to 2160p"
    assert small_1080 in kept


def test_an_unnamed_resolution_falls_back_to_the_global_cap(settings):
    settings["MAX_SIZE_GB"] = 20
    settings["MAX_SIZE_GB_BY_RESOLUTION"] = ["2160p=60"]
    big_4k = _stream(quality="2160p", size_gb=50.0)     # under its own cap
    big_1080 = _stream(quality="1080p", size_gb=50.0)   # over the global one

    kept = streams._apply_non_category_filters([big_4k, big_1080], {})

    assert big_4k in kept
    assert big_1080 not in kept


def test_a_per_resolution_cap_overrides_a_stricter_global_one(settings):
    settings["MAX_SIZE_GB"] = 10
    settings["MAX_SIZE_GB_BY_RESOLUTION"] = ["2160p=60"]
    big_4k = _stream(quality="2160p", size_gb=50.0)

    assert big_4k in streams._apply_non_category_filters([big_4k], {})


def test_an_unknown_size_always_survives(settings):
    """Consistent with every other numeric filter here: a scraper that did
    not report a size must not be discarded for it."""
    settings["MAX_SIZE_GB_BY_RESOLUTION"] = ["1080p=1"]
    no_size = _stream(quality="1080p", size_gb=0.0)

    assert no_size in streams._apply_non_category_filters([no_size], {})


def test_caps_relax_rather_than_return_nothing(settings):
    """Same soft behaviour as the rest of the filters: an empty result is
    worse than an oversized one."""
    settings["MAX_SIZE_GB_BY_RESOLUTION"] = ["1080p=1"]
    only = _stream(quality="1080p", size_gb=40.0)

    assert streams._apply_non_category_filters([only], {}) == [only]


# -- the tie-break direction --------------------------------------------------

# _sort_candidates reads a "preferred" list per rule category even when
# SORT_ORDER names none of them, so supply the empty shape it expects.
_NO_RULES = {c: {"preferred": []} for c in
             ("resolution", "language", "source", "encode", "visual_tag", "audio_tag")}


def _sorted_sizes(settings, sizes):
    settings["SORT_ORDER"] = ["size"]
    given = [_stream(size_gb=n) for n in sizes]
    return [s.size_gb for s in streams._sort_candidates(given, _NO_RULES, False, {})]


def test_smallest_wins_by_default(settings):
    assert _sorted_sizes(settings, [30.0, 5.0, 12.0]) == [5.0, 12.0, 30.0]


def test_prefer_smaller_false_flips_the_direction(settings):
    settings["PREFER_SMALLER_FILES"] = False
    assert _sorted_sizes(settings, [30.0, 5.0, 12.0]) == [30.0, 12.0, 5.0]


def test_the_default_matches_the_behaviour_before_this_setting_existed(settings):
    """main sorted ascending with no way to change it; that has to remain
    what an install with nothing configured gets."""
    assert _sorted_sizes(settings, [9.0, 2.0]) == [2.0, 9.0]
