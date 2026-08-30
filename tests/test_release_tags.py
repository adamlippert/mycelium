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
    ("Movie.1080p.WEB.x264", {"web"}),
    ("Movie.720p.HDTV.x264", {"hdtv"}),
    ("Movie.DVDRip.XviD", {"dvdrip"}),
    ("Movie.2024.HDCAM.x264", {"cam"}),
    ("Movie.2024.TELESYNC.x264", {"ts"}),
    ("Movie.2024.DVDSCR.x264", {"scr"}),
    ("Movie.2024.1080p.WORKPRINT.x264", {"workprint"}),
    ("Movie.2024.x264", set()),
])
def test_detect_sources_are_mutually_exclusive(text, expected):
    assert set(rt.detect_sources(text)) == expected


def test_workprint_is_detected():
    """The retired _CAM_RE matched workprint too; release_tags must keep
    catching it or EXCLUDE_CAM=true silently starts letting workprint leaks
    through."""
    assert rt.detect_sources("Movie.2024.1080p.WORKPRINT.x264") == ("workprint",)


def test_remux_and_bluray_no_longer_collide():
    """The defect this replaces: EXCLUDE_BLURAY silently dropped remuxes because
    _BLURAY_RE matched the same names as _REMUX_RE."""
    assert set(rt.detect_sources("Dune.2160p.UHD.BluRay.REMUX.HEVC")) == {"remux"}
    assert "bluray" not in rt.detect_sources("Dune.2160p.UHD.BluRay.REMUX.HEVC")


@pytest.mark.parametrize("text,expected", [
    ("Movie.2024.1080p.x265.HEVC", {"hevc"}),
    ("Movie.2024.1080p.H.265", {"hevc"}),
    ("Movie.2024.1080p.x264", {"avc"}),
    ("Movie.2024.1080p.H.264.AVC", {"avc"}),
    ("Movie.2024.2160p.AV1", {"av1"}),
    ("Movie.2024.XviD", {"xvid"}),
    ("Movie.2024.1080p", set()),
])
def test_detect_encode(text, expected):
    assert set(rt.detect_encode(text)) == expected


@pytest.mark.parametrize("text,expected", [
    ("Movie.2160p.HDR10.WEB-DL", {"hdr10"}),
    ("Movie.2160p.HDR10Plus.WEB-DL", {"hdr10plus"}),
    ("Movie.2160p.HDR10+.WEB-DL", {"hdr10plus"}),
    ("Movie.2160p.DV.HDR10.WEB-DL", {"dv", "hdr10"}),
    ("Movie.2160p.DoVi.WEB-DL", {"dv", "dv_only"}),
    ("Movie.2160p.HLG.WEB-DL", {"hlg"}),
    ("Movie.2160p.10bit.WEB-DL", {"10bit"}),
    ("Movie.2160p.IMAX.WEB-DL", {"imax"}),
    ("Movie.1080p.WEB-DL", set()),
])
def test_detect_visual_tags(text, expected):
    assert set(rt.detect_visual_tags(text)) == expected


def test_trailing_dv_marker_is_detected():
    """The retired _DV_RE was \\b(dovi|dolby[\\s.]?vision|\\.dv\\.)\\b, which
    required dots on both sides of a bare "dv" and so missed a release name
    ending in ".DV" with nothing after it. Deliberately broader: catching more
    DV-only releases is the correct direction for EXCLUDE_DV_P5. See the
    CHANGELOG Unreleased entry - this is a documented behaviour change, not a
    regression."""
    tags = rt.detect_visual_tags("Movie.2024.1080p.BluRay.x264.DV")
    assert "dv" in tags
    assert "dv_only" in tags


@pytest.mark.parametrize("text", [
    "Movie.2160p.DV.HDR10+.WEB-DL",
    "Movie.2160p.DV.HDR10Plus.WEB-DL",
])
def test_hdr10_plus_is_not_an_hdr10_fallback(text):
    """Both HDR10+ and HDR10Plus must fail to satisfy the hdr10 tag when DV has
    no HDR10 base layer. The '+' spelling exercises the lookahead (word boundary
    between '0' and '+'); the 'Plus' spelling is already rejected by the trailing
    \\b word boundary in the hdr10 pattern itself."""
    tags = rt.detect_visual_tags(text)
    assert "hdr10plus" in tags
    assert "hdr10" not in tags
    assert "dv_only" in tags


@pytest.mark.parametrize("text,expected", [
    ("Movie.2160p.TrueHD.Atmos.7.1", {"truehd", "atmos"}),
    ("Movie.1080p.DTS-HD.MA.5.1", {"dts_hd", "dts"}),
    ("Movie.1080p.DDP5.1.Atmos", {"ddp", "atmos"}),
    ("Movie.1080p.AC3", {"dd"}),
    ("Movie.1080p.AAC2.0", {"aac"}),
    ("Movie.1080p.FLAC", {"flac"}),
    ("Movie.1080p.x264", set()),
    ("Movie.1080p.DD5.1", {"dd"}),
    ("Movie.1080p.DDP.Atmos", {"ddp", "atmos"}),
    ("Movie.AACS.Protected", set()),
    ("Movie.1080p.DD+5.1", {"ddp"}),
    ("Movie.1080p.E-AC3.5.1", {"ddp"}),
    ("Movie.1080p.E-AC-3", {"ddp"}),
    ("Movie.1080p.EAC3", {"ddp"}),
    ("Movie.1080p.AC-3", {"dd"}),
])
def test_detect_audio_tags(text, expected):
    assert set(rt.detect_audio_tags(text)) == expected


@pytest.mark.parametrize("text,expected", [
    ("Movie.2160p.TrueHD.7.1", {"7.1"}),
    ("Movie.1080p.DDP5.1", {"5.1"}),
    ("Movie.1080p.AAC2.0", {"2.0"}),
    ("Movie.1080p.x264", set()),
])
def test_detect_audio_channels(text, expected):
    assert set(rt.detect_audio_channels(text)) == expected


def test_detect_all_covers_every_category():
    tags = rt.detect_all("Movie.2024.1080p.WEB-DL.x265.HDR10.DDP5.1", ("en",))
    assert set(tags) == set(rt.CATEGORIES)
    assert tags["resolution"] == ("1080p",)
    assert tags["source"] == ("webdl",)
    assert tags["encode"] == ("hevc",)
    assert tags["language"] == ("en",)


def test_detect_all_uses_unknown_not_empty_for_silence():
    """An empty tuple and UNKNOWN must not both be reachable, or the rule engine
    has two spellings for the same idea."""
    tags = rt.detect_all("Some.Release.Name", ())
    for category, values in tags.items():
        assert values == (rt.UNKNOWN,), f"{category} was {values!r}"
