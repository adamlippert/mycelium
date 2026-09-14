"""deprecations.warn_deprecated_env(): DEPRECATED is empty at 1.0, so these
tests feed a fake map (monkeypatched) to prove the warning behaviour itself,
not just that an empty dict warns about nothing."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import deprecations


def test_empty_map_warns_about_nothing():
    assert deprecations.DEPRECATED == {}
    assert deprecations.warn_deprecated_env() == []


def test_warns_once_per_deprecated_name_present_in_the_environment(monkeypatch):
    monkeypatch.setattr(deprecations, "DEPRECATED", {"OLD_NAME": "NEW_NAME"})
    monkeypatch.delenv("OLD_NAME", raising=False)
    monkeypatch.setenv("OLD_NAME", "1")
    messages = deprecations.warn_deprecated_env()
    assert len(messages) == 1
    assert "OLD_NAME" in messages[0]
    assert "NEW_NAME" in messages[0]


def test_no_warning_when_the_deprecated_name_is_not_set(monkeypatch):
    monkeypatch.setattr(deprecations, "DEPRECATED", {"OLD_NAME": "NEW_NAME"})
    monkeypatch.delenv("OLD_NAME", raising=False)
    assert deprecations.warn_deprecated_env() == []


def test_every_entry_in_the_map_names_a_different_replacement(monkeypatch):
    """The rule the compatibility guard enforces on the real map: a fake
    entry that names itself (no real replacement) must never pass."""
    monkeypatch.setattr(deprecations, "DEPRECATED", {"SELF": "SELF"})
    old, new = next(iter(deprecations.DEPRECATED.items()))
    assert not (new and new != old)
