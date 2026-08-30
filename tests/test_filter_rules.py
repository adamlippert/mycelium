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


def test_every_rule_key_is_hot_reloadable():
    """filter_rules.load_rules() reads every one of the 35 rule keys live on
    every rank_streams call, so none of them should ever tell the admin UI a
    restart is needed. Asserted against _RULE_LIST_KEYS/_RULE_STRICT_KEYS
    directly (not the PREFIXES/STATES literals above) so the two lists cannot
    drift apart again."""
    for key in _s._RULE_LIST_KEYS:
        assert key in _s.HOT_RELOAD, f"{key} missing from HOT_RELOAD"
    for key in _s._RULE_STRICT_KEYS:
        assert key in _s.HOT_RELOAD, f"{key} missing from HOT_RELOAD"


def test_all_for_ui_exposes_the_vocabulary_for_rule_and_sort_keys():
    """options was null for every rule key even though set() validates each
    one against a fixed vocabulary - the UI offered free text where a typo
    would raise. Rule keys, the language lists and SORT_ORDER should all now
    carry their valid values."""
    groups = {item["key"]: item for g in _s.all_for_ui() for item in g["items"]}
    assert groups["SOURCE_EXCLUDED"]["options"] == list(rt.values_for("source"))
    assert groups["SORT_ORDER"]["options"] == list(_s._streams.SORT_CRITERIA)
    # Was AUDIO_LANGUAGE_PREFERENCE, which is retired and no longer offered in
    # the UI at all. LANGUAGE_PREFERRED replaced it. Its vocabulary is the
    # detector's, which is every language code PLUS "unknown" - a first-class
    # value in the rule model, since a release that named no language is not a
    # release with no audio.
    assert groups["LANGUAGE_PREFERRED"]["options"] == list(rt.values_for("language"))
    assert set(_s._streams.LANGUAGE_CODES) <= set(groups["LANGUAGE_PREFERRED"]["options"])
    assert "unknown" in groups["LANGUAGE_PREFERRED"]["options"]
    assert "AUDIO_LANGUAGE_PREFERENCE" not in groups


def test_no_quality_prefixed_rule_key_exists():
    """QUALITY_PREFERENCE already exists and means resolution. A QUALITY_PREFERRED
    two characters away from it, meaning source type, is a trap."""
    for state in STATES:
        assert f"QUALITY_{state}" not in _s._LIST_KEYS


def test_every_rule_key_is_env_backed():
    """settings.get falls back to getattr(config, key), so a rule key missing
    from config.py means a value set in .env is silently ignored. Every setting
    these replaced was env-backed."""
    import config
    for prefix in ("RESOLUTION", "SOURCE", "ENCODE", "VISUAL_TAG",
                   "AUDIO_TAG", "AUDIO_CHANNELS", "LANGUAGE"):
        for state in ("PREFERRED", "EXCLUDED", "REQUIRED", "INCLUDED"):
            assert hasattr(config, f"{prefix}_{state}"), f"{prefix}_{state}"
        assert hasattr(config, f"{prefix}_STRICT"), f"{prefix}_STRICT"


def test_settings_module_survives_a_reload():
    """settings.py defines `def set`, so any module-scope call to the builtin
    set() breaks on reload once that name is bound."""
    import importlib, settings
    importlib.reload(settings)
    assert "SOURCE_EXCLUDED" in settings._LIST_KEYS


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
import streams


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
    """Two candidates, each condemned by a different category.

    Under a sequential chain the category that runs second sees a pool of one,
    drops it, relaxes against that shrunken pool, and the survivor depends
    entirely on category order: forward keeps the first candidate, reversed
    keeps the second. Evaluating every category against the FULL pool and
    unioning the votes gives the same answer either way, and here that answer
    is to relax both rules and keep both candidates.

    A fixture where no category empties its own local pool cannot detect the
    difference, because relaxation is the only pool-dependent behaviour in the
    engine.
    """
    tagged = [
        _tag("Movie.1080p.HDCAM.x264"),   # condemned by SOURCE_EXCLUDED
        _tag("Movie.720p.WEB-DL.x264"),   # condemned by RESOLUTION_EXCLUDED
    ]
    rules = _rules(source={"excluded": ["cam"]},
                   resolution={"excluded": ["720p"]})

    forward = fr.evaluate(tagged, rules)

    # evaluate() iterates rt.CATEGORIES, so the evaluation order lives THERE,
    # not in the rules dict. Reversing the dict would change nothing.
    monkeypatch.setattr(fr.rt, "CATEGORIES", tuple(reversed(rt.CATEGORIES)))
    backward = fr.evaluate(tagged, rules)

    assert [v.kept for v in forward] == [v.kept for v in backward], (
        "category order changed the outcome: "
        f"forward={[v.kept for v in forward]} backward={[v.kept for v in backward]}")
    assert [v.kept for v in forward] == [True, True], (
        "the union of votes covers the whole pool, so both non-strict rules "
        "relax and both candidates survive")


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


def test_show_override_replaces_resolution_preference():
    rules = _rules(resolution={"preferred": ["1080p"]})
    out = streams._apply_show_override(rules, {"quality_preference": "2160p,1080p"})
    assert out["resolution"]["preferred"] == ["2160p", "1080p"]


def test_show_override_allow_4k_false_excludes_2160p():
    out = streams._apply_show_override(_rules(), {"allow_4k": False})
    assert "2160p" in out["resolution"]["excluded"]


def test_show_override_prefer_hevc_adds_and_removes():
    on = streams._apply_show_override(_rules(), {"prefer_hevc": True})
    assert "hevc" in on["encode"]["preferred"]
    off = streams._apply_show_override(
        _rules(encode={"preferred": ["hevc"]}), {"prefer_hevc": False})
    assert "hevc" not in off["encode"]["preferred"]


def test_show_override_does_not_mutate_the_global_rules():
    base = _rules(resolution={"preferred": ["1080p"]})
    streams._apply_show_override(base, {"quality_preference": "720p"})
    assert base["resolution"]["preferred"] == ["1080p"], "global rules were mutated"


def test_empty_override_changes_nothing():
    base = _rules(resolution={"preferred": ["1080p"]})
    assert streams._apply_show_override(base, {}) == base


# ── rank_streams routed through the rule engine ──────────────────────────────

def test_rank_streams_signature_is_unchanged(monkeypatch):
    # Local import, not the module-level _s: some tests elsewhere pop
    # "settings" out of sys.modules to force a reload, and rank_streams'
    # settings access (via filter_rules.load_rules) is itself lazy for the
    # same reason. Importing here, immediately before the monkeypatch and the
    # call under test, is what keeps both sides looking at the same object.
    import settings as _s
    monkeypatch.setattr(_s, "get", lambda k, d=None: d)
    out = streams.rank_streams([
        streams.Stream(name="Movie.1080p.WEB-DL.x264", title="Movie.1080p.WEB-DL.x264",
                       info_hash="a" * 40, quality="1080p", seeders=10, size_gb=5.0,
                       is_season_pack=False),
    ])
    assert isinstance(out, list)
    assert all(isinstance(s, streams.Stream) for s in out)


def test_rank_streams_explained_returns_a_verdict_per_input(monkeypatch):
    import settings as _s  # see comment in the previous test

    def fake_get(key, default=None):
        if key == "SOURCE_EXCLUDED":
            return ["cam"]
        return default
    monkeypatch.setattr(_s, "get", fake_get)

    cands = [
        streams.Stream(name="Movie.1080p.WEB-DL.x264", title="Movie.1080p.WEB-DL.x264",
                       info_hash="a" * 40, quality="1080p", seeders=10, size_gb=5.0,
                       is_season_pack=False),
        streams.Stream(name="Movie.1080p.HDCAM.x264", title="Movie.1080p.HDCAM.x264",
                       info_hash="b" * 40, quality="1080p", seeders=99, size_gb=5.0,
                       is_season_pack=False),
    ]
    kept, verdicts = streams.rank_streams_explained(cands)
    assert len(verdicts) == 2
    assert len(kept) == 1
    assert kept[0].info_hash == "a" * 40
    dropped = [v for v in verdicts if not v.kept]
    assert dropped[0].rule == "SOURCE_EXCLUDED"
    assert dropped[0].value == "cam"


def test_each_scraper_declares_its_capabilities():
    import debridio, torrentio, zilean
    for module in (debridio, torrentio, zilean):
        assert isinstance(module.CAPABILITIES, frozenset), module.__name__
        assert module.CAPABILITIES <= set(rt.CATEGORIES), module.__name__


def test_zilean_supplies_every_text_derived_category_but_not_language():
    """Zilean's asymmetry is not arbitrary. rank_streams tags a candidate with
    detect_all(name + title, s.languages), so every category except language is
    read off the release title and Zilean supplies it like any other scraper.
    Only language comes from Stream.languages, which zilean.py never sets."""
    import zilean
    assert "language" not in zilean.CAPABILITIES
    assert {"resolution", "source", "encode", "visual_tag",
            "audio_tag", "audio_channels"} <= zilean.CAPABILITIES
    assert zilean.LANGUAGES_AVAILABLE is False


def test_required_rule_on_an_unsupported_category_is_warned_about():
    warnings = fr.warn_unsupported_requirements(
        _rules(language={"required": ["en"]}), ["zilean", "torrentio"])
    assert len(warnings) == 1
    assert "zilean" in warnings[0]
    assert "language" in warnings[0]


def test_no_warning_when_every_source_supports_the_category():
    warnings = fr.warn_unsupported_requirements(
        _rules(language={"required": ["en"]}), ["torrentio", "debridio"])
    assert warnings == []


def test_no_warning_without_a_required_rule():
    """preferred and excluded rules degrade gracefully on a source that cannot
    supply the category, because unknown always survives them. Only required
    is worth warning about."""
    assert fr.warn_unsupported_requirements(
        _rules(language={"preferred": ["en"], "excluded": ["ru"]}),
        ["zilean"]) == []


def test_an_unimportable_source_name_does_not_raise():
    assert fr.warn_unsupported_requirements(
        _rules(language={"required": ["en"]}), ["not_a_real_module"]) == []


def test_preferring_webdl_still_rewards_webrip_and_bare_web():
    """The retired PREFER_WEBDL matched web-dl, webrip and web alike. The sort
    term must consult the preferred list rather than one hardcoded value, so a
    migration that lists all three ranks each of them ahead of a source that
    is not on the list.

    This drives the actual sort (streams._sort_candidates), not just
    release_tags.detect_sources: a membership check against detect_sources
    alone passes identically whether the sort term is hardcoded to "webdl" or
    reads the preferred list, and would not have caught the regression this
    test exists to pin.
    """
    import streams
    rules = _rules(source={"preferred": ["webdl", "webrip", "web"]})

    def mk(name, info_hash):
        return streams.Stream(name=name, title=name, info_hash=info_hash,
                               quality="1080p", seeders=10, size_gb=5.0,
                               is_season_pack=False)

    webrip = mk("Movie.1080p.WEBRip.x264", "a" * 40)
    bare_web = mk("Movie.1080p.WEB.x264", "b" * 40)
    bluray = mk("Movie.1080p.BluRay.x264", "c" * 40)  # not on the preferred list

    ranked = streams._sort_candidates([bluray, webrip, bare_web], rules, False, {})
    names = [s.name for s in ranked]
    assert names.index(webrip.name) < names.index(bluray.name), names
    assert names.index(bare_web.name) < names.index(bluray.name), names


def test_a_source_absent_from_preferred_is_not_rewarded():
    rules = _rules(source={"preferred": ["webdl"]})
    tags = rt.detect_sources("Movie.1080p.WEBRip.x264 Movie.1080p.WEBRip.x264")
    assert not any(v in rules["source"]["preferred"] for v in tags)


def test_source_strict_does_not_make_the_size_check_fatal(monkeypatch):
    """STRICT_NO_CAM used to hard-fail the undersized check too. That coupling
    is a bug and must not survive the migration."""
    import settings as _s  # see comment in test_rank_streams_signature_is_unchanged
    def fake_get(key, default=None):
        return {"SOURCE_STRICT": True,
                "EXCLUDE_UNDERSIZED_RELEASES": True,
                "EXCLUDE_UNDERSIZED_STRICT": False}.get(key, default)
    monkeypatch.setattr(_s, "get", fake_get)

    tiny = streams.Stream(name="Movie.1080p.WEB-DL.x264", title="Movie.1080p.WEB-DL.x264",
                          info_hash="c" * 40, quality="1080p", seeders=10, size_gb=0.05,
                          is_season_pack=False)
    kept, _ = streams.rank_streams_explained([tiny], override={"runtime_minutes": 120})
    assert kept, "the size check must relax, not hard-fail, under SOURCE_STRICT"


def test_undersized_strict_makes_the_size_check_fatal(monkeypatch):
    import settings as _s  # see comment in test_rank_streams_signature_is_unchanged
    def fake_get(key, default=None):
        return {"EXCLUDE_UNDERSIZED_RELEASES": True,
                "EXCLUDE_UNDERSIZED_STRICT": True}.get(key, default)
    monkeypatch.setattr(_s, "get", fake_get)

    tiny = streams.Stream(name="Movie.1080p.WEB-DL.x264", title="Movie.1080p.WEB-DL.x264",
                          info_hash="d" * 40, quality="1080p", seeders=10, size_gb=0.05,
                          is_season_pack=False)
    kept, _ = streams.rank_streams_explained([tiny], override={"runtime_minutes": 120})
    assert kept == []


# ── Task 12: configurable SORT_ORDER ─────────────────────────────────────────

def _mk(name, info_hash, quality="1080p", seeders=10, size_gb=5.0,
        is_season_pack=False, languages=(), source="torrentio", cached=False):
    return streams.Stream(name=name, title=name, info_hash=info_hash, quality=quality,
                           seeders=seeders, size_gb=size_gb, is_season_pack=is_season_pack,
                           languages=languages, source=source, cached=cached)


def _patch_sort_order(monkeypatch, order):
    """Only SORT_ORDER is intercepted; _sort_candidates reads every other
    preference from the rules dict the caller builds, not from settings.get."""
    import settings as _s
    monkeypatch.setattr(_s, "get", lambda k, d=None: order if k == "SORT_ORDER" else d)


def test_sort_criteria_matches_the_ten_named_in_the_spec():
    assert set(streams.SORT_CRITERIA) == {
        "season_pack", "resolution", "cached", "language", "source",
        "encode", "visual_tag", "audio_tag", "seeders", "size",
    }


def test_default_sort_order_is_registered_and_omits_the_new_capabilities():
    assert list(streams.SORT_ORDER) == [
        "season_pack", "resolution", "language", "source", "encode", "seeders", "size",
    ]
    for new_capability in ("cached", "visual_tag", "audio_tag"):
        assert new_capability not in streams.SORT_ORDER, (
            f"{new_capability} must not be in the default SORT_ORDER")


def test_default_order_reproduces_todays_ranking(monkeypatch):
    """A concrete multi-candidate ordering, not just that the setting exists.

    Every candidate below differs from the "ideal" one in exactly one
    criterion, holding every more-significant criterion equal to it. Ascending
    tuple comparison then means a candidate degraded on a LESS significant
    (later) criterion must rank ABOVE one degraded on a MORE significant
    (earlier) criterion - exactly the seven-term precedence the old hardcoded
    tuple encoded: season_pack, resolution, language, source, encode, seeders,
    size.
    """
    _patch_sort_order(monkeypatch, list(streams.SORT_ORDER))
    rules = _rules(
        resolution={"preferred": ["1080p"]},
        language={"preferred": ["en"]},
        source={"preferred": ["webdl"]},
        encode={"preferred": ["hevc"]},
    )

    ideal = _mk("Show.S01E01.1080p.WEB-DL.x265", "a" * 40,
                is_season_pack=True, languages=("en",), seeders=100, size_gb=1.0)
    degraded_size = _mk("Show.S01E01.1080p.WEB-DL.x265", "b" * 40,
                         is_season_pack=True, languages=("en",), seeders=100, size_gb=9.0)
    degraded_seeders = _mk("Show.S01E01.1080p.WEB-DL.x265", "c" * 40,
                            is_season_pack=True, languages=("en",), seeders=1, size_gb=1.0)
    degraded_encode = _mk("Show.S01E01.1080p.WEB-DL.x264", "d" * 40,
                           is_season_pack=True, languages=("en",), seeders=100, size_gb=1.0)
    degraded_source = _mk("Show.S01E01.1080p.BluRay.x265", "e" * 40,
                           is_season_pack=True, languages=("en",), seeders=100, size_gb=1.0)
    degraded_language = _mk("Show.S01E01.1080p.WEB-DL.x265", "f" * 40,
                             is_season_pack=True, languages=("fr",), seeders=100, size_gb=1.0)
    degraded_resolution = _mk("Show.S01E01.2160p.WEB-DL.x265", "g" * 40, quality="2160p",
                               is_season_pack=True, languages=("en",), seeders=100, size_gb=1.0)
    degraded_season_pack = _mk("Show.S01E01.1080p.WEB-DL.x265", "h" * 40,
                                is_season_pack=False, languages=("en",), seeders=100, size_gb=1.0)

    everyone = [degraded_season_pack, degraded_resolution, degraded_language,
                degraded_source, degraded_encode, degraded_seeders, degraded_size, ideal]
    ranked = streams._sort_candidates(everyone, rules, prefer_season_pack=True, override={})

    assert [s.info_hash for s in ranked] == [
        ideal.info_hash, degraded_size.info_hash, degraded_seeders.info_hash,
        degraded_encode.info_hash, degraded_source.info_hash, degraded_language.info_hash,
        degraded_resolution.info_hash, degraded_season_pack.info_hash,
    ]


def test_reordering_seeders_before_resolution_picks_the_other_release(monkeypatch):
    """Two candidates where seeders and resolution disagree. Under the default
    order resolution decides; putting seeders first flips the winner. A test
    that cannot distinguish the two orders would not prove SORT_ORDER drives
    anything."""
    rules = _rules(resolution={"preferred": ["1080p"]})
    high_seeders_low_res = _mk("A", "a" * 40, quality="2160p", seeders=500, size_gb=5.0)
    low_seeders_high_res = _mk("B", "b" * 40, quality="1080p", seeders=5, size_gb=5.0)
    candidates = [high_seeders_low_res, low_seeders_high_res]

    _patch_sort_order(monkeypatch, ["resolution", "seeders"])
    by_resolution = streams._sort_candidates(list(candidates), rules, False, {})
    assert by_resolution[0].info_hash == low_seeders_high_res.info_hash

    _patch_sort_order(monkeypatch, ["seeders", "resolution"])
    by_seeders = streams._sort_candidates(list(candidates), rules, False, {})
    assert by_seeders[0].info_hash == high_seeders_low_res.info_hash

    assert by_resolution[0].info_hash != by_seeders[0].info_hash, (
        "reordering SORT_ORDER did not change the winner - the sort key is "
        "not actually driven by the setting")


def test_omitting_a_criterion_removes_it_from_the_sort(monkeypatch):
    """SORT_ORDER=[seeders] only: two candidates tied on seeders but different
    resolution must keep their input order, because resolution is not part of
    the sort at all."""
    rules = _rules(resolution={"preferred": ["1080p"]})
    better_resolution = _mk("A", "a" * 40, quality="1080p", seeders=10, size_gb=5.0)
    worse_resolution = _mk("B", "b" * 40, quality="2160p", seeders=10, size_gb=5.0)

    _patch_sort_order(monkeypatch, ["seeders"])
    ranked = streams._sort_candidates(
        [worse_resolution, better_resolution], rules, False, {})
    assert [s.info_hash for s in ranked] == [
        worse_resolution.info_hash, better_resolution.info_hash,
    ], "resolution must have no effect when it is absent from SORT_ORDER"


def test_duplicate_criterion_is_used_once_at_its_first_position():
    resolved = streams._resolve_sort_order(["seeders", "resolution", "seeders", "size"])
    assert resolved == ["seeders", "resolution", "size"]


def test_unknown_criterion_name_is_dropped_with_a_warning():
    resolved = streams._resolve_sort_order(["seeders", "not_a_real_criterion", "size"])
    assert resolved == ["seeders", "size"]


def test_settings_set_rejects_an_unknown_sort_criterion(monkeypatch):
    import settings as _s
    stored = {}
    monkeypatch.setattr(_s.db, "set_setting", lambda k, v: stored.__setitem__(k, v))
    with pytest.raises(ValueError) as exc:
        _s.set("SORT_ORDER", ["seeders", "popularity"])
    assert "popularity" in str(exc.value)
    assert stored == {}


def test_settings_set_accepts_a_known_sort_order(monkeypatch):
    import settings as _s
    stored = {}
    monkeypatch.setattr(_s.db, "set_setting", lambda k, v: stored.__setitem__(k, v))
    _s.set("SORT_ORDER", ["seeders", "resolution"])
    assert stored["SORT_ORDER"] == "seeders,resolution"


def test_empty_sort_order_falls_back_to_the_default():
    assert streams._resolve_sort_order([]) == list(streams.SORT_ORDER)


def test_all_bogus_sort_order_falls_back_to_the_default_literal_not_the_rejected_value():
    """The regression this guards: a SORT_ORDER=bogus in .env must not fall
    back to the raw, already-rejected config value it just dropped - that
    would reintroduce "bogus" into sort_key() and raise KeyError on every
    single rank_streams call. It must fall back to DEFAULT_SORT_ORDER, a
    plain literal no .env value can corrupt."""
    assert streams._resolve_sort_order(["bogus"]) == list(streams.DEFAULT_SORT_ORDER)


def test_empty_sort_order_falls_back_to_the_default_literal():
    assert streams._resolve_sort_order([]) == list(streams.DEFAULT_SORT_ORDER)


def test_partially_bogus_sort_order_keeps_only_the_valid_entries():
    assert streams._resolve_sort_order(["bogus", "seeders"]) == ["seeders"]


def test_bogus_sort_order_ranks_without_raising(monkeypatch):
    """End-to-end version of the KeyError regression: SORT_ORDER=bogus must
    not brick every rank_streams call."""
    _patch_sort_order(monkeypatch, ["bogus"])
    rules = _rules(resolution={"preferred": ["1080p"]})
    better = _mk("A", "a" * 40, quality="1080p", seeders=1, size_gb=5.0)
    worse = _mk("B", "b" * 40, quality="2160p", seeders=100, size_gb=5.0)
    ranked = streams._sort_candidates([worse, better], rules, False, {})
    assert ranked[0].info_hash == better.info_hash, (
        "SORT_ORDER=bogus must behave exactly like the default order, not "
        "raise and not leave candidates unsorted")


def test_empty_sort_order_setting_does_not_leave_candidates_unsorted(monkeypatch):
    """An empty SORT_ORDER must behave exactly like the default, not like 'no
    sort at all'."""
    rules = _rules(resolution={"preferred": ["1080p"]})
    better = _mk("A", "a" * 40, quality="1080p", seeders=1, size_gb=5.0)
    worse = _mk("B", "b" * 40, quality="2160p", seeders=100, size_gb=5.0)

    _patch_sort_order(monkeypatch, [])
    with_empty = streams._sort_candidates([worse, better], rules, False, {})

    _patch_sort_order(monkeypatch, list(streams.SORT_ORDER))
    with_default = streams._sort_candidates([worse, better], rules, False, {})

    assert [s.info_hash for s in with_empty] == [s.info_hash for s in with_default]
    assert with_empty[0].info_hash == better.info_hash, (
        "resolution must still decide the winner when SORT_ORDER is empty")


def test_cached_criterion_is_absent_from_default_but_works_when_added(monkeypatch):
    assert "cached" not in streams.SORT_ORDER
    rules = _rules()
    is_cached = _mk("A", "a" * 40, seeders=1, cached=True)
    not_cached = _mk("B", "b" * 40, seeders=100, cached=False)

    _patch_sort_order(monkeypatch, ["cached"])
    ranked = streams._sort_candidates([not_cached, is_cached], rules, False, {})
    assert ranked[0].info_hash == is_cached.info_hash


def test_visual_tag_criterion_is_absent_from_default_but_works_when_added(monkeypatch):
    assert "visual_tag" not in streams.SORT_ORDER
    rules = _rules(visual_tag={"preferred": ["hdr10"]})
    hdr = _mk("Movie.2024.1080p.WEB-DL.HDR10.x265", "a" * 40, seeders=1)
    sdr = _mk("Movie.2024.1080p.WEB-DL.SDR.x265", "b" * 40, seeders=100)

    _patch_sort_order(monkeypatch, ["visual_tag"])
    ranked = streams._sort_candidates([sdr, hdr], rules, False, {})
    assert ranked[0].info_hash == hdr.info_hash


def test_audio_tag_criterion_is_absent_from_default_but_works_when_added(monkeypatch):
    assert "audio_tag" not in streams.SORT_ORDER
    rules = _rules(audio_tag={"preferred": ["atmos"]})
    atmos = _mk("Movie.2024.1080p.WEB-DL.Atmos.x265", "a" * 40, seeders=1)
    plain = _mk("Movie.2024.1080p.WEB-DL.AAC.x265", "b" * 40, seeders=100)

    _patch_sort_order(monkeypatch, ["audio_tag"])
    ranked = streams._sort_candidates([plain, atmos], rules, False, {})
    assert ranked[0].info_hash == atmos.info_hash
