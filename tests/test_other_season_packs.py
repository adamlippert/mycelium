"""A pack for another season is not a pack for this one. Scrapers match on
the series, so a season 4 search returns season 1 and 2 packs too; those
must neither count as season packs nor map their files onto season 4."""
import debridio
import strm_generator as sg
import torrentio


def test_a_release_naming_another_season_is_not_a_pack_for_this_one():
    assert torrentio.names_other_season("Reacher (2022) Season 1 S01 (1080p AMZN WEB-DL)", 4) is True
    assert torrentio.names_other_season("Reacher.2022.S02.1080p.DS4K", 4) is True
    assert torrentio.names_other_season("Reacher.S04.1080p.Ru.Ultradox", 4) is False
    assert torrentio.names_other_season("Reacher (2022) Season 4 S04", 4) is False
    assert torrentio.names_other_season("Reacher S01-S04 Complete", 4) is False, "a range naming this season"
    assert torrentio.names_other_season("Reacher S01-S03 Complete", 4) is True
    assert torrentio.names_other_season("Reacher Complete Series 1080p", 4) is False, "no season stated: cannot tell"
    assert torrentio.names_other_season("Reacher.S01E03.1080p", 4) is False, "SxxEyy is an episode tag, not a pack claim"
    assert torrentio.names_other_season("Reacher S01", None) is False

    assert torrentio._looks_like_season_pack("Reacher (2022) Season 1 S01 (1080p)", 4) is False
    assert torrentio._looks_like_season_pack("Reacher (2022) Season 1 S01 (1080p)", 1) is True
    assert torrentio._looks_like_season_pack("Reacher.S04.1080p.Ru.Ultradox", 4) is True
    assert torrentio._looks_like_season_pack("Reacher Complete Series", 4) is True
    assert torrentio._looks_like_season_pack("Reacher.S04E01.1080p", 4) is False


def test_debridio_applies_the_same_rule():
    item = {"name": "Debridio ⚡", "title": "Reacher (2022) Season 1 S01 1080p\n💾 12 GB", "url": "https://x/" + "a" * 40 + "/0",
            "behaviorHints": {"filename": "Reacher.S01.1080p.WEB-DL"}}
    assert debridio._to_stream(item, 4).is_season_pack is False
    assert debridio._to_stream(item, 1).is_season_pack is True
    assert debridio._to_stream(item).is_season_pack is True, "no season asked: name alone decides, as before"


def _f(fid, name):
    return {"id": fid, "name": name, "size": 1000 + fid}


def test_order_mapping_never_applies_to_files_tagged_for_another_season():
    s1 = [_f(i, f"Reacher S01/Reacher (2022) S01E{i + 1:02d} 1080p.mkv") for i in range(8)]
    assert sg.map_episodes_to_files(s1, 4, list(range(1, 9))) == {}, "eight season 1 files are not season 4 in order"
    assert sg.map_episodes_to_files(s1, 1, list(range(1, 9))) == {n: n - 1 for n in range(1, 9)}
    x_tagged = [_f(i, f"Reacher/reacher 1x{i + 1:02d}.mkv") for i in range(3)]
    assert sg.map_episodes_to_files(x_tagged, 4, [1, 2, 3]) == {}
    untagged = [_f(7, "pack/b.mkv"), _f(5, "pack/a.mkv"), _f(9, "pack/c.mkv")]
    assert sg.map_episodes_to_files(untagged, 4, [1, 2, 3]) == {1: 5, 2: 7, 3: 9}, "untagged files still map by order"
    folder_only = [_f(i, f"Reacher S01E01 folder/Episode {i + 1}.mkv") for i in range(2)]
    assert sg.map_episodes_to_files(folder_only, 4, [1, 2]) == {1: 0, 2: 1}, "a tag in the folder name is not the file's"
