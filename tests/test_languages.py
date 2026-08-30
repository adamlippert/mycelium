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

_RANK_SETTINGS = {
    "RESOLUTION_PREFERRED": ["1080p"],
    "LANGUAGE_PREFERRED": ["en", "multi"],
    "LANGUAGE_EXCLUDED": [],
    "SOURCE_PREFERRED": [], "SOURCE_EXCLUDED": [], "SOURCE_STRICT": False,
    "ENCODE_PREFERRED": [],
    "VISUAL_TAG_EXCLUDED": [],
    "RESOLUTION_EXCLUDED": [],
    "EXCLUDE_UNDERSIZED_RELEASES": False,
    "MIN_SEEDERS": 0, "MAX_SIZE_GB": 0,
}


def test_debridio_no_longer_loses_ranking_on_language_it_cannot_win(monkeypatch):
    """Before this fix debridio.py never set languages, so with
    AUDIO_LANGUAGE_PREFERENCE=en,multi every Debridio result scored worst on the
    third sort term and was systematically outranked for a non-quality reason.

    This goes through the real debridio._to_stream()/torrentio._to_stream()
    wiring (not a hand-built Stream() and not the private _lang_score closure)
    so that reverting debridio.py to `languages=()` makes this test fail."""
    import debridio
    import settings as _s
    import torrentio

    # Same quality/seeders/size on both sides, so the language sort term is the
    # only thing that can separate them (or, if the bug is back, put them in a
    # detectably different order).
    debridio_item = {
        "name": "[TB ⚡] Debridio 1080p",
        "title": "Movie.2024.1080p.WEB-DL.x264 🌐 🇬🇧\n👤 42 💾 4.20 GB",
        "url": "https://addon.debridio.com/play/movie/torbox/k/p/" + "a" * 40 + "/f.mkv",
        "behaviorHints": {"bingeGroup": "debridio-" + "a" * 40,
                          "filename": "Movie.2024.1080p.WEB-DL.x264.mkv"},
    }
    debridio_stream = debridio._to_stream(debridio_item)
    assert debridio_stream is not None
    assert "en" in debridio_stream.languages, (
        "debridio._to_stream() did not populate languages from the flag emoji "
        f"in the title - got {debridio_stream.languages!r}")

    torrentio_raw = {
        "infoHash": "b" * 40, "name": "Torrentio",
        "title": "Movie.2024.1080p.WEB-DL.ENGLISH.x264\n👤 42 💾 4.20 GB",
    }
    torrentio_stream = torrentio._to_stream(torrentio_raw, None)
    assert "en" in torrentio_stream.languages

    monkeypatch.setattr(_s, "get", lambda k, d=None: _RANK_SETTINGS.get(k, d))

    ranked = streams.rank_streams([debridio_stream, torrentio_stream])
    # Everything but the language term ties (quality, seeders, size); with the
    # fix in place both score index 0 for "en" and the stable sort keeps input
    # order. If debridio.py stops populating languages, debridio scores worse
    # than torrentio's explicit ENGLISH tag and drops to second place.
    assert [s.source for s in ranked] == ["debridio", "torrentio"], (
        f"Debridio still penalised on language: {[s.source for s in ranked]}")


def test_a_release_flagged_in_a_non_preferred_language_ranks_below_an_untagged_one(monkeypatch):
    """More data can move a release DOWN, not just up. Once a release positively
    declares French/German only, it is a known non-match for
    AUDIO_LANGUAGE_PREFERENCE=en,multi - worse than a release that simply never
    said anything at all (merely unknown). See the note in
    streams.detect_languages for why that direction is intentional."""
    import settings as _s

    def mk(source, name):
        return streams.Stream(
            name=name, title=name, info_hash=f"{abs(hash(source + name)):040x}"[:40],
            quality="1080p", seeders=10, size_gb=5.0, is_season_pack=False,
            languages=streams.detect_languages(name), source=source)

    untagged = mk("torrentio", "Movie.2024.1080p.WEB-DL.x264")
    fr_de_only = mk("debridio", "Movie.2024.1080p.WEB-DL.x264 🇫🇷🇩🇪")
    assert untagged.languages == ()
    assert set(fr_de_only.languages) == {"fr", "de"}

    monkeypatch.setattr(_s, "get", lambda k, d=None: _RANK_SETTINGS.get(k, d))

    ranked = streams.rank_streams([fr_de_only, untagged])
    assert [s.source for s in ranked] == ["torrentio", "debridio"], (
        "a release that positively declares a non-preferred language should "
        f"rank worse than one that said nothing: {[s.source for s in ranked]}")
