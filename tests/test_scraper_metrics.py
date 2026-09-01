"""The Scrapers admin tab shows per-scraper latency and state.

The buffer is in-process and unpersisted on purpose: the app runs one
gunicorn worker, and an empty buffer after restart must read as unknown,
never as an outage.
"""
import os
import sys

os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import scraper_metrics


@pytest.fixture(autouse=True)
def _clean():
    scraper_metrics.reset()
    yield
    scraper_metrics.reset()


def test_no_samples_reads_unknown_not_down():
    (h,) = scraper_metrics.get_health(["torrentio"])
    assert h == {"name": "torrentio", "latency_ms": None, "state": "unknown", "samples": 0}


def test_fast_and_succeeding_reads_ok():
    for _ in range(5):
        scraper_metrics.record("torrentio", 212.0, True)
    (h,) = scraper_metrics.get_health(["torrentio"])
    assert h["state"] == "ok"
    assert h["latency_ms"] == 212
    assert h["samples"] == 5


def test_median_at_or_over_1000ms_reads_slow():
    for ms in (900, 1400, 1500):
        scraper_metrics.record("debridio", ms, True)
    (h,) = scraper_metrics.get_health(["debridio"])
    assert h["state"] == "slow"


def test_three_consecutive_failures_read_down():
    scraper_metrics.record("zilean", 100, True)
    for _ in range(3):
        scraper_metrics.record("zilean", 3000, False)
    (h,) = scraper_metrics.get_health(["zilean"])
    assert h["state"] == "down"


def test_a_success_resets_the_failure_streak():
    for _ in range(3):
        scraper_metrics.record("zilean", 3000, False)
    scraper_metrics.record("zilean", 150, True)
    (h,) = scraper_metrics.get_health(["zilean"])
    assert h["state"] != "down"


def test_the_ring_buffer_is_bounded_at_50():
    for i in range(80):
        scraper_metrics.record("torrentio", float(i), True)
    (h,) = scraper_metrics.get_health(["torrentio"])
    assert h["samples"] == 50


def test_only_requested_scrapers_appear_in_order():
    scraper_metrics.record("torrentio", 100, True)
    out = scraper_metrics.get_health(["debridio", "torrentio"])
    assert [h["name"] for h in out] == ["debridio", "torrentio"]


def test_the_wrapper_records_and_reraises():
    """merge_candidates must still see the exception; a scraper failure that
    the wrapper swallowed would be counted as an empty success upstream."""
    def boom(*a, **k):
        raise RuntimeError("upstream 502")

    timed = scraper_metrics.timed("torrentio", boom)
    with pytest.raises(RuntimeError):
        timed("movie", "tt1", None, None, None)
    (h,) = scraper_metrics.get_health(["torrentio"])
    assert h["samples"] == 1


def test_the_endpoint_is_registered():
    with open(os.path.join(os.path.dirname(__file__), "..", "app.py"), encoding="utf-8") as f:
        src = f.read()
    assert '@app.get("/ui/api/scraper-health")' in src
    # The endpoint now serves scrapers.health_rows(), which wraps get_health
    # per scraper and adds the disabled/probe states the admin page shows.
    assert "health_rows()" in src


def test_the_scraper_calls_go_through_the_wrapper():
    with open(os.path.join(os.path.dirname(__file__), "..", "scrapers.py"), encoding="utf-8") as f:
        src = f.read()
    assert "scraper_metrics.timed(" in src
