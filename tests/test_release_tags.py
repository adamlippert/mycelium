import os, sys
os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
import release_tags as rt


@pytest.mark.parametrize("text,expected", [
    ("Movie.2024.2160p.WEB-DL.x265", "2160p"),
    ("Movie.2024.4K.UHD.BluRay", "2160p"),
    ("Movie.2024.1080p.WEB-DL", "1080p"),
    ("Movie.2024.720p.HDTV", "720p"),
    ("Movie.2024.480p.DVDRip", "480p"),
    ("Movie.2024.WEB-DL.x264", rt.UNKNOWN),
])
def test_detect_resolution(text, expected):
    assert rt.detect_resolution(text) == expected


@pytest.mark.parametrize("text,expected", [
    ("Dune.2160p.UHD.BluRay.REMUX.HEVC", {"remux"}),
    ("Movie.1080p.BDRemux.x264", {"remux"}),
    ("Movie.1080p.BluRay.x264", {"bluray"}),
    ("Movie.1080p.BDRip.x264", {"bdrip"}),
    ("Movie.1080p.BRRip.x264", {"brrip"}),
    ("Movie.1080p.WEB-DL.DDP5.1", {"webdl"}),
    ("Movie.1080p.WEBRip.x264", {"webrip"}),
    ("Movie.720p.HDTV.x264", {"hdtv"}),
    ("Movie.DVDRip.XviD", {"dvdrip"}),
    ("Movie.2024.HDCAM.x264", {"cam"}),
    ("Movie.2024.TELESYNC.x264", {"ts"}),
    ("Movie.2024.DVDSCR.x264", {"scr"}),
    ("Movie.2024.x264", set()),
])
def test_detect_sources_are_mutually_exclusive(text, expected):
    assert set(rt.detect_sources(text)) == expected


def test_remux_and_bluray_no_longer_collide():
    """The defect this replaces: EXCLUDE_BLURAY silently dropped remuxes because
    _BLURAY_RE matched the same names as _REMUX_RE."""
    assert set(rt.detect_sources("Dune.2160p.UHD.BluRay.REMUX.HEVC")) == {"remux"}
    assert "bluray" not in rt.detect_sources("Dune.2160p.UHD.BluRay.REMUX.HEVC")
