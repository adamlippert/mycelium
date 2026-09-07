"""The setup wizard is declared next to the settings schema: WIZARD_STEPS
name the keys each step shows, RULE_FIELDS declare the four filter-rule
keys the quality step edits, and /setup/schema serves both pre-filled.
"""
import os
import re
import sys

os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

sys.modules.pop("settings", None)

import pytest

import db
import settings

_ROOT = os.path.join(os.path.dirname(__file__), "..")


def _src(name):
    with open(os.path.join(_ROOT, name), encoding="utf-8") as f:
        return f.read()


def _drop_cached_conn():
    conn = getattr(db._tls, "conn", None)
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass
        db._tls.conn = None


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    _drop_cached_conn()
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    _drop_cached_conn()
    db.init()
    yield
    _drop_cached_conn()


def test_every_step_names_known_keys_once_with_title_and_intro():
    known = settings.fields_by_key()
    seen = []
    for s in settings.WIZARD_STEPS:
        assert set(s) == {"id", "title", "intro", "keys", "lite"}, s.get("id")
        assert s["title"].strip() and s["intro"].strip().endswith("."), s["id"]
        assert isinstance(s["lite"], bool), s["id"]
        for k in s["keys"]:
            assert k in known, f"{s['id']}: {k}"
            assert known[k]["kind"] != "custom", k
        seen.extend(s["keys"])
        for text in (s["title"], s["intro"]):
            assert chr(0x2014) not in text and " -" + "- " not in text, s["id"]
    assert len(seen) == len(set(seen)), "a key appears in two steps"
    assert [s["id"] for s in settings.WIZARD_STEPS][:2] == ["welcome", "torbox"]
    assert {s["id"] for s in settings.WIZARD_STEPS if not s["lite"]} == {"trakt", "subtitles", "zilean", "arrs"}


def test_rule_fields_are_declared_with_vocabularies_without_unknown():
    by_key = {f["key"]: f for f in settings.RULE_FIELDS}
    assert set(by_key) == {"RESOLUTION_PREFERRED", "RESOLUTION_EXCLUDED", "ENCODE_PREFERRED", "LANGUAGE_PREFERRED"}
    assert by_key["RESOLUTION_PREFERRED"]["kind"] == "ordered"
    assert all(by_key[k]["kind"] == "multiselect" for k in ("RESOLUTION_EXCLUDED", "ENCODE_PREFERRED", "LANGUAGE_PREFERRED"))
    res = [o["value"] for o in settings._resolve_options(by_key["RESOLUTION_PREFERRED"])]
    assert "2160p" in res and "1080p" in res and "unknown" not in res
    enc = [o["value"] for o in settings._resolve_options(by_key["ENCODE_PREFERRED"])]
    assert "hevc" in enc and "unknown" not in enc
    lang = [o["value"] for o in settings._resolve_options(by_key["LANGUAGE_PREFERRED"])]
    assert "en" in lang and "unknown" not in lang
    # Rule fields live outside the Settings sections but are known to the schema.
    assert "RESOLUTION_PREFERRED" in settings.fields_by_key()
    assert all(f["key"] not in {f2["key"] for s in settings.SECTIONS for f2 in s["fields"]} for f in settings.RULE_FIELDS)


def test_required_is_only_the_torbox_key():
    req = [k for k, f in settings.fields_by_key().items() if f["required"]]
    assert req == ["TORBOX_API_KEY"]


def test_wizard_schema_is_prefilled_from_current_values():
    settings.set("JELLYFIN_URL", "http://jf.test")
    settings.set("TORBOX_API_KEY", "abc")
    settings.set("RESOLUTION_PREFERRED", "1080p,2160p")
    out = settings.wizard_schema_for_ui()
    assert [s["id"] for s in out["steps"]] == [s["id"] for s in settings.WIZARD_STEPS]
    by_key = {f["key"]: f for f in out["fields"]}
    wanted = [k for s in settings.WIZARD_STEPS for k in s["keys"]]
    assert list(by_key) == wanted, "one field per step key, in step order"
    assert by_key["JELLYFIN_URL"]["value"] == "http://jf.test" and by_key["JELLYFIN_URL"]["overridden"] is True
    assert by_key["TORBOX_API_KEY"]["value"] is True, "secrets are set/not-set only"
    assert by_key["RESOLUTION_PREFERRED"]["value"] == ["1080p", "2160p"]
    assert by_key["RESOLUTION_PREFERRED"]["options"][0]["value"] == "2160p"
    assert by_key["ZILEAN_URL"]["depends_on"] == "ZILEAN_MODE=external"


def test_the_retired_translator_is_gone_and_save_accepts_rule_keys():
    import migrate_filters
    assert not hasattr(migrate_filters, "translate_wizard_keys")
    assert not hasattr(migrate_filters, "WIZARD_KEYS")
    assert hasattr(migrate_filters, "RETIRED"), "the .env warning keeps its map"
    src = _src("app.py")
    assert "translate_wizard_keys" not in src and "WIZARD_KEYS" not in src
    body = re.search(r"def setup_save\(\).*?\n(.*?)\n@app\.", src, re.S).group(1)
    assert "fields_by_key()" in body
    # The rule keys are accepted by the allow-list and validated by settings.set.
    assert "RESOLUTION_PREFERRED" in settings.fields_by_key()
    assert "QUALITY_PREFERENCE" not in settings.fields_by_key()
    with pytest.raises(ValueError):
        settings.set("RESOLUTION_PREFERRED", "1080p,8k")


def test_the_setup_routes_share_one_gate():
    src = _src("app.py")
    gate = re.search(r"def _setup_gate\(\).*?\n(.*?)\n\n\n", src, re.S)
    assert gate and 'SETUP_COMPLETE' in gate.group(1) and "auth.is_admin()" in gate.group(1)
    for route in ('@app.get("/setup/schema")', '@app.post("/setup/picker/<name>")', '@app.post("/setup/test/<kind>")'):
        assert route in src, route
        body = src.split(route, 1)[1].split("\n\n\n", 1)[0]
        assert "_setup_gate()" in body, route
    schema = src.split('@app.get("/setup/schema")', 1)[1].split("\n\n\n", 1)[0]
    assert "wizard_schema_for_ui()" in schema and "_needs_first_admin()" in schema
    picker = src.split('@app.post("/setup/picker/<name>")', 1)[1].split("\n\n\n", 1)[0]
    assert "service_tests.PICKERS" in picker and "service_tests.pick(name" in picker
    test = src.split('@app.post("/setup/test/<kind>")', 1)[1].split("\n\n\n", 1)[0]
    assert "get_json(silent=True)" in test and "service_tests.run(kind" in test
    assert 'jsonify(ok=True, detail=' in test, "the form shape the old wizard used stays"
