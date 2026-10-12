from gulf_srt.edits import compare, main, replaced_words, report, suggestions
from gulf_srt.replace import read_replacements
from gulf_srt.segment import Cue
from gulf_srt.srt import write_srt

DRAFT = [
    Cue(0.0, 2.0, ["يا ابن الحلال، أنا أقوم بدري"]),
    Cue(2.0, 4.0, ["على شأن الرياضة"]),
    Cue(5.0, 7.0, ["تراك صدقت نفسك"]),
    Cue(8.0, 9.0, ["هاها"]),
]
FINAL = [
    Cue(0.0, 2.0, ["يا ابن الحلال، أنا أقوم بدري"]),  # kept as is
    Cue(2.0, 4.0, ["علشان الرياضة"]),  # the editor fixed a word
    Cue(5.2, 7.4, ["تراك صدقت نفسك"]),  # only moved in time
]  # the laughter line was deleted


def test_lines_changed_retimed_and_word_edit_rate():
    result = compare(DRAFT, FINAL)
    assert (result["lines"], result["changed"], result["retimed"]) == (4, 2, 1)
    # «على شأن» -> «علشان» is 2 edits, the deleted «هاها» is 1, out of 11 final words.
    assert (result["word_edits"], result["final_words"]) == (3, 11)


def test_swaps_become_suggested_rules_that_start_switched_off(tmp_path):
    swaps = replaced_words(DRAFT, FINAL)
    assert swaps[("على شأن", "علشان")] == 1
    text = suggestions(swaps + swaps, {("على شأن", "علشان"): {"ep01", "ep02"}})
    assert "# على شأن => علشان" in text and "# 2 times, 2 episode(s)" in text
    file = tmp_path / "suggested.txt"
    file.write_text(text, encoding="utf-8")
    assert read_replacements(file) == []  # nothing is used until a person approves it


def test_report_table_has_a_total():
    table = report([("ep01", compare(DRAFT, FINAL)), ("ep02", compare(FINAL, FINAL))])
    assert "| ep02 | 3 | 0 (0%) | 0 | 0.0% |" in table
    assert "| **All** | 7 | 2 (29%) | 1 | 13.6% |" in table


def test_folders_are_paired_by_file_name(tmp_path, capsys):
    (tmp_path / "draft").mkdir()
    (tmp_path / "final").mkdir()
    write_srt(DRAFT, tmp_path / "draft" / "ep01.srt")
    write_srt(FINAL, tmp_path / "final" / "ep01.srt")
    write_srt(DRAFT, tmp_path / "draft" / "ep02.srt")  # not edited yet: no final, so not counted
    write_srt(FINAL, tmp_path / "final" / "ep03_final.srt")  # saved under another name
    main([str(tmp_path / "draft"), str(tmp_path / "final"), "--report", str(tmp_path / "kpi.md"),
          "--suggest", str(tmp_path / "fixes.txt"), "--min-count", "1"])
    kpi = (tmp_path / "kpi.md").read_text(encoding="utf-8")
    assert "| ep01 | 4 | 2 (50%) | 1 |" in kpi and "| ep02 |" not in kpi
    assert "1 draft(s) with no final of the same name: ep02.srt" in kpi
    assert "1 final(s) with no draft of the same name: ep03_final.srt" in kpi
    assert "ep03_final.srt has no draft" in capsys.readouterr().err
    assert "# على شأن => علشان" in (tmp_path / "fixes.txt").read_text(encoding="utf-8")
