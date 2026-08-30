import os, sys
os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
import settings as _s


@pytest.fixture
def ui(tmp_path, monkeypatch):
    monkeypatch.setattr(_s.db, "get_all_settings", lambda: {})
    return _s.all_for_ui()


def _group(ui):
    return next(g for g in ui if g["id"] == "filter_rules")


def test_the_filter_rules_group_exists_with_all_thirty_five_keys(ui):
    assert len(_group(ui)["items"]) == 35


def test_every_list_key_carries_its_vocabulary(ui):
    """The editor renders a dropdown from options. A key without them would
    render an empty picker with no way to add a value."""
    missing = [i["key"] for i in _group(ui)["items"]
               if i["kind"] == "list" and not i["options"]]
    assert missing == []


def test_every_rule_key_is_hot_reloadable(ui):
    """The editor saves without a restart. A key marked otherwise would make
    the UI tell the user to restart for a change that takes effect at once."""
    assert all(i["hot_reload"] for i in _group(ui)["items"])


def test_key_names_match_what_the_editor_writes(ui):
    """The editor writes hidden inputs named setting_<KEY>. If these names
    drift, saving silently stops working while every test still passes."""
    keys = {i["key"] for i in _group(ui)["items"]}
    for prefix in ("RESOLUTION", "SOURCE", "ENCODE", "VISUAL_TAG",
                   "AUDIO_TAG", "AUDIO_CHANNELS", "LANGUAGE"):
        for state in ("PREFERRED", "EXCLUDED", "REQUIRED", "INCLUDED"):
            assert f"{prefix}_{state}" in keys
        assert f"{prefix}_STRICT" in keys


def test_strict_keys_are_bools_and_state_keys_are_lists(ui):
    for item in _group(ui)["items"]:
        expected = "bool" if item["key"].endswith("_STRICT") else "list"
        assert item["kind"] == expected, item["key"]


def test_the_save_endpoint_still_reads_the_setting_prefix():
    """The editor's hidden inputs are named setting_<KEY> because that is what
    /ui/settings parses. This pins the prefix so a rename cannot pass silently.

    app.py is read as TEXT rather than imported: importing it pulls in
    apscheduler, which is not installed in the test environment, and no other
    test imports app either.
    """
    import pathlib
    import re

    source = pathlib.Path(__file__).resolve().parent.parent.joinpath("app.py").read_text()
    match = re.search(r"def ui_save_settings.*?(?=\ndef |\n@app)", source, re.S)
    assert match, "ui_save_settings not found in app.py"
    assert 'startswith("setting_")' in match.group(0), (
        "the save endpoint no longer filters on the setting_ prefix; the "
        "rules editor writes hidden inputs with that prefix and would "
        "silently stop saving")
