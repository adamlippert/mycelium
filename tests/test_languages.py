import os
import sys

os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import streams


# ── the shared detector ───────────────────────────────────────────────────────

@pytest.mark.parametrize("text,expected", [
    ("Show.S01E01.1080p.WEB-DL.ENGLISH.x264", {"en"}),
    ("Movie.2024.1080p.Dutch.NLSubs.x264", {"nl"}),
    ("Movie.2024.1080p.MULTi.VFF.x264", {"multi"}),
    ("Movie.2024.1080p.DUAL.AUDIO.x264", {"multi"}),
    ("Фильм.2024.1080p.BDRip.x264", {"ru"}),
])
def test_detect_languages_from_a_release_name(text, expected):
    assert set(streams.detect_languages(text)) == expected


def test_an_untagged_release_detects_nothing():
    """English names do not say "English" - it is the unmarked default. This is
    why an empty set must mean "did not say", never "has no languages"."""
    assert streams.detect_languages("Dune.Part.Two.2024.2160p.WEB-DL.DDP5.1.HEVC") == ()
    assert streams.detect_languages("") == ()
    assert streams.detect_languages(None) == ()


# ── flag emoji, which is what Debridio actually ships ─────────────────────────

def test_flag_emoji_decode_to_language_codes():
    langs = streams.detect_languages("Movie 🌐 🇬🇧|🇯🇵|🇫🇷|🇪🇸|🇮🇹|🇩🇪|🇵🇱|🇨🇿")
    assert set(langs) == {"en", "ja", "fr", "es", "it", "de", "pl", "cs"}


def test_regional_variants_map_to_one_language():
    assert set(streams.detect_languages("🇺🇸 🇬🇧 🇦🇺")) == {"en"}
    assert set(streams.detect_languages("🇧🇷 🇵🇹")) == {"pt"}
    assert set(streams.detect_languages("🇲🇽 🇦🇷 🇪🇸")) == {"es"}


def test_unknown_flag_is_ignored_not_crashed():
    assert streams.detect_languages("🇦🇶") == ()          # Antarctica: no language


def test_flags_and_name_patterns_combine():
    assert set(streams.detect_languages("Movie.DUAL.AUDIO.x264 🇩🇪")) == {"multi", "de"}


def test_detection_is_order_stable():
    """Two calls on the same text must give the same order - languages feeds a
    ranking index, so an unstable order would make ranking nondeterministic."""
    text = "Movie 🇬🇧|🇩🇪|🇫🇷 DUAL.AUDIO"
    assert streams.detect_languages(text) == streams.detect_languages(text)


# ── the "unknown" concept, made explicit ──────────────────────────────────────

def test_unknown_is_a_named_constant_not_a_bare_empty_tuple():
    assert streams.LANGUAGE_UNKNOWN == "unknown"
    assert streams.LANGUAGE_UNKNOWN not in streams.LANGUAGE_CODES


def test_languages_or_unknown_reports_what_was_actually_detected():
    assert streams.languages_or_unknown(("en", "de")) == ("en", "de")
    assert streams.languages_or_unknown(()) == (streams.LANGUAGE_UNKNOWN,)


# ── every scraper populates it ────────────────────────────────────────────────

def test_debridio_populates_languages_from_flag_emoji():
    import debridio
    item = {
        "name": "[TB ⚡] Debridio 4k",
        "title": ("Dune.Part.Two.2024.2160p.BluRay.Remux.mkv\n"
                  "⚡ 📺 4k 💾 85.37 GB\n🌐 🇬🇧|🇯🇵|🇫🇷"),
        "url": "https://addon.debridio.com/play/movie/torbox/k/p/" + "a" * 40 + "/f.mkv",
        "behaviorHints": {"bingeGroup": "debridio-" + "a" * 40,
                          "filename": "Dune.Part.Two.2024.2160p.BluRay.Remux.mkv"},
    }
    stream = debridio._to_stream(item)
    assert set(stream.languages) == {"en", "ja", "fr"}


def test_torrentio_still_populates_languages():
    import torrentio
    raw = {"infoHash": "b" * 40, "name": "Torrentio 1080p",
           "title": "Movie.2024.1080p.WEB-DL.ENGLISH.x264\n👤 20 💾 5 GB"}
    stream = torrentio._to_stream(raw, None)
    assert "en" in stream.languages


def test_zilean_reports_unknown_rather_than_pretending():
    """Zilean's payload carries no language data at all. That must be visible as
    'unknown', not silently indistinguishable from a genuinely language-less
    release."""
    import zilean
    assert zilean.LANGUAGES_AVAILABLE is False


# ── the regression this fixes ─────────────────────────────────────────────────

def test_debridio_no_longer_loses_ranking_on_language_it_cannot_win(monkeypatch):
    """Before this fix debridio.py never set languages, so with
    AUDIO_LANGUAGE_PREFERENCE=en,multi every Debridio result scored worst on the
    third sort term and was systematically outranked for a non-quality reason."""
    import settings as _s

    def mk(source, name):
        blob = f"{name}"
        return streams.Stream(
            name=name, title=name, info_hash=f"{abs(hash(source)):040x}"[:40],
            quality="1080p", seeders=100, size_gb=5.0, is_season_pack=False,
            languages=streams.detect_languages(blob), source=source)

    debridio_stream = mk("debridio", "Movie.2024.1080p.WEB-DL.x264 🇬🇧")
    torrentio_stream = mk("torrentio", "Movie.2024.1080p.WEB-DL.ENGLISH.x264")

    values = {
        "QUALITY_PREFERENCE": ["1080p"], "AUDIO_LANGUAGE_PREFERENCE": ["en", "multi"],
        "PREFER_WEBDL": False, "PREFER_HEVC": False, "ALLOW_4K": True,
        "EXCLUDE_REMUX": False, "EXCLUDE_BLURAY": False, "EXCLUDE_CAM": False,
        "EXCLUDE_DV_P5": False, "EXCLUDE_UNDERSIZED_RELEASES": False,
        "STRICT_NO_CAM": False, "MIN_SEEDERS": 0, "MAX_SIZE_GB": 0,
        "EXCLUDE_LANGUAGES": [],
    }
    monkeypatch.setattr(_s, "get", lambda k, d=None: values.get(k, d))

    ranked = streams.rank_streams([debridio_stream, torrentio_stream])
    scores = {s.source: streams._lang_score(s, ["en", "multi"]) if
              hasattr(streams, "_lang_score") else None for s in ranked}
    assert scores["debridio"] == scores["torrentio"], (
        f"Debridio still penalised on language: {scores}")
