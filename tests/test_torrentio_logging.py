"""Item 3 of the 1.0 readiness blocker pass.

fetch_streams used to log the full request URL at INFO, which embeds
TORRENTIO_OPTS - a config segment users paste from Torrentio's own
configure page that can carry a debrid API key - straight into
log_buffer, which /ui/api/logs serves to any logged-in user. The fix logs
the imdb id and media type only.
"""
import logging
import os
import sys

os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

sys.modules.pop("settings", None)

import torrentio

_SECRET_OPTS = "debridkey=SUPERSECRET123|qualityfilter=cam"


class _FakeResponse:
    def raise_for_status(self):
        pass

    def json(self):
        return {"streams": []}


def test_the_opts_segment_never_reaches_the_logs(monkeypatch, caplog):
    monkeypatch.setattr(torrentio, "TORRENTIO_OPTS", _SECRET_OPTS)
    monkeypatch.setattr(torrentio.requests, "get", lambda *a, **k: _FakeResponse())

    with caplog.at_level(logging.INFO, logger="torrentio"):
        torrentio.fetch_streams("movie", "tt0111161")

    for record in caplog.records:
        assert _SECRET_OPTS not in record.getMessage()
        assert "SUPERSECRET123" not in record.getMessage()

    joined = "\n".join(r.getMessage() for r in caplog.records)
    assert "tt0111161" in joined
    assert "movie" in joined
