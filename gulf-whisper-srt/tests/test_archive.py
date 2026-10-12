from gulf_srt.archive import build_from_subtitles, entries_from_cues, load_entries, make_index, search, write_index
from gulf_srt.segment import Cue
from gulf_srt.srt import write_srt

CUES = [
    Cue(10.0, 12.0, ["يا أبو حمد، صلح الشاهي"]),
    Cue(20.0, 22.0, ["خلنا نصلح لعبود شاهي"]),
    Cue(30.0, 32.0, ["عبود اول واحد يجي للدوام"]),
]
ENTRIES = entries_from_cues(CUES, "ep01.srt")


def cues_found(entries, query, mode="attached"):
    return [h["cue"] for h in search(entries, query, mode)]


def test_search_ignores_spelling_variants_and_punctuation():
    hits = search(ENTRIES, "ابو حمد")
    assert [(h["cue"], h["start"]) for h in hits] == [(1, 10.0)]


def test_names_are_found_with_attached_letters_but_not_inside_other_words():
    assert cues_found(ENTRIES, "عبود") == [2, 3]  # «لعبود» counts
    assert cues_found(ENTRIES, "عبود", "word") == [3]
    other = entries_from_cues([Cue(0, 1, ["الله معبود"]), Cue(2, 3, ["محمد قال الحمد لله"])], "ep02.srt")
    assert cues_found(other, "عبود") == [] and cues_found(other, "حمد") == []
    assert cues_found(other, "حمد", "anywhere") == [2]


def test_ali_the_name_is_not_ala_the_preposition():
    entries = entries_from_cues([Cue(0, 1, ["رحت على البيت"]), Cue(2, 3, ["وين علي؟"])], "ep03.srt")
    assert cues_found(entries, "علي") == [2]
    assert cues_found(entries, "على") == [1]


def test_empty_query_finds_nothing():
    assert search(ENTRIES, "؟") == []


def test_build_from_a_folder_of_subtitles(tmp_path):
    (tmp_path / "season1").mkdir()
    write_srt(CUES, tmp_path / "season1" / "ep01.srt")
    write_srt(CUES[:1], tmp_path / "ep02.srt")
    index = build_from_subtitles([tmp_path], index_folder=tmp_path)
    assert {e["file"] for e in index["entries"]} == {"season1/ep01.srt", "ep02.srt"}
    write_index(index, tmp_path / "archive.json")
    write_index(make_index([]), tmp_path / "empty.index.json")
    (tmp_path / "unrelated.json").write_text('{"hello": 1}', encoding="utf-8")
    assert len(load_entries(tmp_path)) == 4  # every index in the folder, other JSON ignored
    assert {h["file"] for h in search(load_entries(tmp_path / "archive.json"), "أبو حمد")} == {
        "season1/ep01.srt", "ep02.srt"}


def test_same_episode_name_in_two_seasons_and_no_double_hits(tmp_path):
    for season in ("s1", "s2"):
        (tmp_path / season).mkdir()
        write_srt(CUES[:1], tmp_path / season / "ep01.srt")
        write_index(make_index(entries_from_cues(CUES[:1], "ep01.srt")), tmp_path / season / "ep01.index.json")
    # An archive built from the same files sits next to the per-episode indexes.
    write_index(build_from_subtitles([tmp_path], index_folder=tmp_path), tmp_path / "archive.json")
    hits = search(load_entries(tmp_path), "أبو حمد")
    assert sorted(h["file"] for h in hits) == ["s1/ep01.srt", "s2/ep01.srt"]
