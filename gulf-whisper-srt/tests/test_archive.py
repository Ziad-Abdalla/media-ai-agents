from gulf_srt.archive import build_from_subtitles, entries_from_cues, load_entries, make_index, search, write_index
from gulf_srt.segment import Cue
from gulf_srt.srt import write_srt

CUES = [
    Cue(10.0, 12.0, ["يا أبو حمد، صلح الشاهي"]),
    Cue(20.0, 22.0, ["خلنا نصلح لعبود شاهي"]),
    Cue(30.0, 32.0, ["عبود اول واحد يجي للدوام"]),
]
ENTRIES = entries_from_cues(CUES, "ep01.srt")


def test_search_ignores_spelling_variants_and_punctuation():
    hits = search(ENTRIES, "ابو حمد")
    assert [(h["cue"], h["start"]) for h in hits] == [(1, 10.0)]


def test_search_finds_names_with_attached_particles_unless_whole_word():
    assert [h["cue"] for h in search(ENTRIES, "عبود")] == [2, 3]  # «لعبود» counts
    assert [h["cue"] for h in search(ENTRIES, "عبود", whole_word=True)] == [3]


def test_empty_query_finds_nothing():
    assert search(ENTRIES, "؟") == []


def test_build_from_a_folder_of_subtitles(tmp_path):
    (tmp_path / "season1").mkdir()
    write_srt(CUES, tmp_path / "season1" / "ep01.srt")
    write_srt(CUES[:1], tmp_path / "ep02.srt")
    index = build_from_subtitles([tmp_path])
    assert len(index["entries"]) == 4
    write_index(index, tmp_path / "archive.json")
    write_index(make_index([]), tmp_path / "empty.index.json")
    (tmp_path / "unrelated.json").write_text('{"hello": 1}', encoding="utf-8")
    assert len(load_entries(tmp_path)) == 4  # every index in the folder, other JSON ignored
    assert {h["file"].split("/")[-1] for h in search(load_entries(tmp_path / "archive.json"), "أبو حمد")} == {
        "ep01.srt", "ep02.srt"}
