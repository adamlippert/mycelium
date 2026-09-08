"""admin_query: the LIKE-escaping, int-clamping and page-clamping helpers
shared by library_admin.py and requests_admin.py. Pure functions, no db."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import admin_query as aq


def test_like_pattern_wraps_with_wildcards():
    assert aq.like_pattern("heat") == "%heat%"


def test_like_pattern_escapes_percent_underscore_and_backslash():
    # backslash must be escaped first, or escaping % and _ would double-escape it
    assert aq.like_pattern("100%") == "%100\\%%"
    assert aq.like_pattern("Silo_S1") == "%Silo\\_S1%"
    assert aq.like_pattern("a\\b") == "%a\\\\b%"
    assert aq.like_pattern("a\\_b") == "%a\\\\\\_b%"


def test_clamp_int_defaults_on_non_numeric():
    assert aq.clamp_int("x", 5, 1, 10) == 5
    assert aq.clamp_int(None, 5, 1, 10) == 5


def test_clamp_int_clamps_to_bounds():
    assert aq.clamp_int(0, 5, 1, 10) == 1
    assert aq.clamp_int(999, 5, 1, 10) == 10
    assert aq.clamp_int(7, 5, 1, 10) == 7


def test_added_windows_cover_the_three_choices():
    assert aq.ADDED_WINDOWS == {"24h": "-1 day", "7d": "-7 days", "30d": "-30 days"}


def test_effective_page_passes_through_when_in_range():
    assert aq.effective_page(2, 50, 120) == 2


def test_effective_page_clamps_past_the_last_page():
    # 3 rows, per_page 2 -> last page is 2
    assert aq.effective_page(99, 2, 3) == 2


def test_effective_page_is_1_when_the_total_is_0():
    assert aq.effective_page(99, 50, 0) == 1
