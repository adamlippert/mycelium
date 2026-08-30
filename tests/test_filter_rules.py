import os, sys
os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
import release_tags as rt
import settings as _s

STATES = ("PREFERRED", "EXCLUDED", "REQUIRED", "INCLUDED")
PREFIXES = ("RESOLUTION", "SOURCE", "ENCODE", "VISUAL_TAG",
            "AUDIO_TAG", "AUDIO_CHANNELS", "LANGUAGE")


def test_all_thirty_five_settings_are_registered():
    for prefix in PREFIXES:
        for state in STATES:
            key = f"{prefix}_{state}"
            assert key in _s._LIST_KEYS, f"{key} missing from _LIST_KEYS"
        assert f"{prefix}_STRICT" in _s._BOOL_KEYS, f"{prefix}_STRICT missing"
    total = len(PREFIXES) * len(STATES) + len(PREFIXES)
    assert total == 35


def test_every_registered_key_appears_in_a_settings_group():
    grouped = {k for g in _s.SETTING_GROUPS for k in g["keys"]}
    for prefix in PREFIXES:
        for state in STATES:
            assert f"{prefix}_{state}" in grouped, f"{prefix}_{state} not in any group"
        assert f"{prefix}_STRICT" in grouped


def test_no_quality_prefixed_rule_key_exists():
    """QUALITY_PREFERENCE already exists and means resolution. A QUALITY_PREFERRED
    two characters away from it, meaning source type, is a trap."""
    for state in STATES:
        assert f"QUALITY_{state}" not in _s._LIST_KEYS


def test_setting_an_unknown_value_is_rejected(monkeypatch):
    stored = {}
    monkeypatch.setattr(_s.db, "set_setting", lambda k, v: stored.__setitem__(k, v))
    with pytest.raises(ValueError) as exc:
        _s.set("RESOLUTION_EXCLUDED", ["1081p"])
    assert "1081p" in str(exc.value)
    assert stored == {}


def test_setting_a_known_value_is_accepted(monkeypatch):
    stored = {}
    monkeypatch.setattr(_s.db, "set_setting", lambda k, v: stored.__setitem__(k, v))
    _s.set("RESOLUTION_EXCLUDED", ["480p"])
    assert stored["RESOLUTION_EXCLUDED"] == "480p"


def test_unknown_is_a_settable_value_in_every_category():
    """Excluding 'unknown' is how a user asks for positively-tagged releases only."""
    for category in rt.CATEGORIES:
        assert rt.UNKNOWN in rt.values_for(category), category


def test_language_vocabulary_is_never_reachable_as_an_empty_value():
    """A half-populated mapping would let validation silently accept any
    language string. values_for is the single accessor precisely so there is
    no alternative path that returns an unresolved empty vocabulary."""
    assert not hasattr(rt, "VALUES_BY_CATEGORY"), (
        "a public all-categories mapping invites .get()/.items() access that "
        "bypasses lazy resolution")
    assert len(rt.values_for("language")) > 30
    assert rt.UNKNOWN in rt.values_for("language")


import filter_rules as fr


def _rules(**kw):
    """Every category empty unless named. Mirrors an untouched install."""
    base = {c: {"preferred": [], "excluded": [], "required": [], "included": [],
                "strict": False}
            for c in rt.CATEGORIES}
    for category, states in kw.items():
        base[category].update(states)
    return base


def _tag(name, languages=()):
    return rt.detect_all(name, languages)


def test_every_candidate_gets_a_verdict_including_survivors():
    tagged = [_tag("Movie.1080p.WEB-DL.x264"), _tag("Movie.1080p.HDCAM.x264")]
    verdicts = fr.evaluate(tagged, _rules(source={"excluded": ["cam"]}))
    assert len(verdicts) == 2
    assert verdicts[0].kept is True
    assert verdicts[1].kept is False


def test_a_drop_names_the_rule_and_the_value():
    tagged = [_tag("Movie.1080p.WEB-DL.x264"), _tag("Movie.1080p.HDCAM.x264")]
    verdicts = fr.evaluate(tagged, _rules(source={"excluded": ["cam"]}))
    assert verdicts[1].rule == "SOURCE_EXCLUDED"
    assert verdicts[1].value == "cam"


def test_evaluation_is_order_independent(monkeypatch):
    """Each category sees the full pool, so no category can shrink the pool
    another category then evaluates against."""
    tagged = [
        _tag("Movie.2160p.BluRay.REMUX.x265"),
        _tag("Movie.1080p.WEB-DL.x264"),
        _tag("Movie.720p.HDCAM.x264"),
    ]
    rules = _rules(source={"excluded": ["remux", "cam"]},
                   resolution={"excluded": ["720p"]})
    forward = fr.evaluate(tagged, rules)

    # evaluate() iterates rt.CATEGORIES, so the evaluation order lives THERE,
    # not in the rules dict. Reversing the dict would change nothing and the
    # test would pass against a sequential implementation too.
    monkeypatch.setattr(fr.rt, "CATEGORIES", tuple(reversed(rt.CATEGORIES)))
    backward = fr.evaluate(tagged, rules)

    assert [v.kept for v in forward] == [v.kept for v in backward]
    assert [v.kept for v in forward] == [False, True, False]


def test_required_does_not_drop_unknown():
    """Absence of data is not evidence of absence. Zilean supplies no language
    at all, so a required-language rule must not delete every Zilean result."""
    tagged = [_tag("Movie.1080p.WEB-DL.x264", ()),          # language unknown
              _tag("Movie.1080p.WEB-DL.FRENCH.x264", ("fr",))]
    verdicts = fr.evaluate(tagged, _rules(language={"required": ["en"]}))
    assert verdicts[0].kept is True, "unknown must survive a required rule"
    assert verdicts[1].kept is False, "a positively non-matching value is dropped"


def test_unknown_can_be_excluded_explicitly():
    """A second, known-language candidate keeps the pool from going fully
    empty. A single-candidate pool would hit the global soft-by-default
    relaxation (every candidate dropped -> relax), which is a different
    behaviour under test elsewhere; this test is specifically about the
    exclusion itself taking effect, so it needs a survivor alongside it."""
    tagged = [_tag("Movie.1080p.WEB-DL.x264", ()),
              _tag("Movie.1080p.WEB-DL.FRENCH.x264", ("fr",))]
    verdicts = fr.evaluate(tagged, _rules(language={"excluded": [rt.UNKNOWN]}))
    assert verdicts[0].kept is False
    assert verdicts[0].rule == "LANGUAGE_EXCLUDED"
    assert verdicts[1].kept is True


def test_included_rescues_across_categories_and_short_circuits():
    tagged = [_tag("Movie.1080p.HDCAM.Atmos.x264")]
    rules = _rules(source={"excluded": ["cam"]}, audio_tag={"included": ["atmos"]})
    verdicts = fr.evaluate(tagged, rules)
    assert verdicts[0].kept is True
    assert verdicts[0].rule == "AUDIO_TAG_INCLUDED"


def test_preferred_never_filters():
    tagged = [_tag("Movie.1080p.WEBRip.x264")]
    verdicts = fr.evaluate(tagged, _rules(source={"preferred": ["webdl"]}))
    assert verdicts[0].kept is True


def test_a_rule_that_would_empty_the_pool_relaxes_and_says_so():
    tagged = [_tag("Movie.1080p.HDCAM.x264"), _tag("Movie.720p.HDCAM.x264")]
    verdicts = fr.evaluate(tagged, _rules(source={"excluded": ["cam"]}))
    assert all(v.kept for v in verdicts), "soft by default"
    assert all(v.relaxed for v in verdicts), "relaxation must be recorded"


def test_strict_holds_even_when_it_empties_the_pool():
    tagged = [_tag("Movie.1080p.HDCAM.x264")]
    rules = _rules(source={"excluded": ["cam"], "strict": True})
    verdicts = fr.evaluate(tagged, rules)
    assert verdicts[0].kept is False
    assert verdicts[0].relaxed is False


def test_two_categories_that_each_drop_part_of_the_pool_still_relax(monkeypatch):
    """Soft-by-default has to be assessed globally. A per-category emptiness
    check misses the case where two categories drop disjoint subsets that
    together cover everything: neither category sees an empty pool on its own,
    so neither relaxes, and the caller gets nothing."""
    tagged = [
        _tag("Movie.1080p.HDCAM.x264"),
        _tag("Movie.1080p.HDCAM.x264"),
        _tag("Movie.720p.WEB-DL.x264"),
    ]
    rules = _rules(source={"excluded": ["cam"]},
                   resolution={"excluded": ["720p"]})
    verdicts = fr.evaluate(tagged, rules)
    assert all(v.kept for v in verdicts), (
        "the pool emptied across two categories without either relaxing: "
        f"{[(v.kept, v.rule) for v in verdicts]}")
    assert all(v.relaxed for v in verdicts)


def test_relaxed_is_not_set_on_survivors_of_an_unrelaxed_run(monkeypatch):
    """relaxed marks a candidate a relaxed rule voted against, not every
    survivor of any run in which some relaxation happened."""
    tagged = [_tag("Movie.1080p.WEB-DL.x264"), _tag("Movie.1080p.HDCAM.x264")]
    verdicts = fr.evaluate(tagged, _rules(source={"excluded": ["cam"]}))
    assert verdicts[0].kept is True and verdicts[0].relaxed is False
    assert verdicts[1].kept is False
