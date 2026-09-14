"""The Logs admin tab polls a structured feed instead of raw lines.

Parsing lives next to the buffer because the format string lives there;
a malformed line (multi-line traceback continuation) must never crash the
endpoint, it rides along as message-only.
"""
import os
import sys

os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from _routes import src_for_route

import log_buffer


def _fill(lines):
    log_buffer._buffer.clear()
    log_buffer._buffer.extend(lines)


def test_lines_parse_into_time_level_name_msg():
    _fill(["2026-08-31 20:11:25,123 INFO [mycelium] started up"])
    (line,) = log_buffer.get_structured()
    assert line == {"time": "20:11:25", "level": "INFO", "name": "mycelium", "msg": "started up"}


def test_a_malformed_line_survives_as_message_only():
    _fill(["Traceback (most recent call last):"])
    (line,) = log_buffer.get_structured()
    assert line["msg"] == "Traceback (most recent call last):"
    assert line["level"] == ""


def test_min_level_filters_below_it():
    _fill([
        "2026-08-31 20:00:00,000 DEBUG [x] noise",
        "2026-08-31 20:00:01,000 INFO [x] info",
        "2026-08-31 20:00:02,000 WARNING [x] warn",
        "2026-08-31 20:00:03,000 ERROR [x] boom",
    ])
    levels = [l["level"] for l in log_buffer.get_structured(min_level="WARNING")]
    assert levels == ["WARNING", "ERROR"]
    # malformed lines are level "" and survive any filter: hiding a traceback
    # because it has no level would hide exactly what the reader came for
    _fill(["party time", "2026-08-31 20:00:00,000 DEBUG [x] noise"])
    assert [l["msg"] for l in log_buffer.get_structured(min_level="ERROR")] == ["party time"]


def test_limit_takes_the_newest():
    _fill([f"2026-08-31 20:00:00,000 INFO [x] m{i}" for i in range(10)])
    out = log_buffer.get_structured(limit=3)
    assert [l["msg"] for l in out] == ["m7", "m8", "m9"]


def test_the_endpoint_is_registered_and_admin_only():
    src = src_for_route("/ui/api/logs")
    import re
    m = re.search(r'@bp\.get\("/ui/api/logs"\)(.{0,400})', src, re.S)
    assert m
    assert "auth.is_admin()" in m.group(1)
    assert "get_structured(" in m.group(1)


def test_the_legacy_ui_logs_route_is_admin_only_too():
    """/ui/logs served the last 100 raw log lines - scraper URLs, CDN URLs,
    tokens, exception text - to any logged-in user, not just admins, while
    its sibling /ui/api/logs already checked auth.is_admin(). Item 4 of the
    1.0 readiness blocker pass closes that gap."""
    src = src_for_route("/ui/logs")
    import re
    m = re.search(r'@bp\.get\("/ui/logs"\)\n(.*?)(?=\n@(?:bp|app)\.|\Z)', src, re.S)
    assert m
    assert "auth.is_admin()" in m.group(1)
