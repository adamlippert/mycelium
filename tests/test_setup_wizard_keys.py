"""The setup wizard (templates/setup.html, frontend/src/pages/setup/) posts
QUALITY_PREFERENCE/ALLOW_4K/PREFER_HEVC/AUDIO_LANGUAGE_PREFERENCE - keys the
filter-rules model retired. migrate_filters.translate_wizard_keys() is the
one place that maps those posted field names onto the rule-model keys the
filter engine actually reads; app.setup_save calls it instead of storing the
retired keys. See migrate_filters.translate_wizard_keys's docstring for the
per-key semantics this pins.
"""
import os, sys
os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import migrate_filters


def test_quality_preference_becomes_resolution_preferred():
    out = migrate_filters.translate_wizard_keys({"QUALITY_PREFERENCE": "1080p,2160p,720p"})
    assert out == {"RESOLUTION_PREFERRED": ["1080p", "2160p", "720p"]}


def test_allow_4k_false_excludes_2160p():
    out = migrate_filters.translate_wizard_keys({"ALLOW_4K": "false"})
    assert out == {"RESOLUTION_EXCLUDED": ["2160p"]}


def test_allow_4k_true_is_a_noop():
    """migrate() itself only ever writes RESOLUTION_EXCLUDED when ALLOW_4K is
    False; mirroring that here means a wizard rerun that flips 4K back on
    does not reach into RESOLUTION_EXCLUDED and silently drop a value an
    admin added by hand in the rule editor."""
    out = migrate_filters.translate_wizard_keys({"ALLOW_4K": "true"})
    assert out == {}


def test_prefer_hevc_true_becomes_encode_preferred():
    out = migrate_filters.translate_wizard_keys({"PREFER_HEVC": "true"})
    assert out == {"ENCODE_PREFERRED": ["hevc"]}


def test_prefer_hevc_false_is_a_noop():
    out = migrate_filters.translate_wizard_keys({"PREFER_HEVC": "false"})
    assert out == {}


def test_audio_language_preference_becomes_language_preferred():
    out = migrate_filters.translate_wizard_keys({"AUDIO_LANGUAGE_PREFERENCE": "nl,en"})
    assert out == {"LANGUAGE_PREFERRED": ["nl", "en"]}


def test_empty_values_are_a_noop():
    """A blank field means the user did not touch that category this save -
    it must not wipe whatever RESOLUTION_PREFERRED/LANGUAGE_PREFERRED already
    holds from a previous save or the boot-time migration."""
    out = migrate_filters.translate_wizard_keys({
        "QUALITY_PREFERENCE": "",
        "AUDIO_LANGUAGE_PREFERENCE": "",
    })
    assert out == {}


def test_keys_absent_from_the_form_are_a_noop():
    out = migrate_filters.translate_wizard_keys({})
    assert out == {}


def test_retired_keys_are_never_returned():
    """The whole point of the helper is that a caller can write its result
    straight into settings without a retired key slipping back into
    storage - assert on every key at once, translating all four fields in
    one call, the way a real wizard save does."""
    out = migrate_filters.translate_wizard_keys({
        "QUALITY_PREFERENCE": "1080p",
        "ALLOW_4K": "false",
        "PREFER_HEVC": "true",
        "AUDIO_LANGUAGE_PREFERENCE": "en",
    })
    assert set(out) == {
        "RESOLUTION_PREFERRED", "RESOLUTION_EXCLUDED",
        "ENCODE_PREFERRED", "LANGUAGE_PREFERRED",
    }
    assert not (set(out) & set(migrate_filters.WIZARD_KEYS))


def test_setup_save_calls_the_shared_translator():
    """app.py must reuse migrate_filters.translate_wizard_keys rather than
    duplicating the QUALITY_PREFERENCE/ALLOW_4K/PREFER_HEVC/
    AUDIO_LANGUAGE_PREFERENCE mapping inline. Source-level check, not an
    import of app.py: importing it pulls in the whole Flask app, scheduler
    and every integration client."""
    app_py_path = os.path.join(os.path.dirname(__file__), "..", "app.py")
    with open(app_py_path) as f:
        source = f.read()
    start = source.index("def setup_save")
    end = source.index("\n\n\n", start)
    body = source[start:end]
    assert "migrate_filters.translate_wizard_keys" in body
    assert "migrate_filters.WIZARD_KEYS" in body
