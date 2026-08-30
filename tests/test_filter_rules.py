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
