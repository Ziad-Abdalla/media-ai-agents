"""The hard set: separate scenes, separate gold, a stricter gate. No API calls."""

import json
from types import SimpleNamespace

import pytest

from breakdown import extract
from breakdown.cast_aliases import HARD_SET, HARD_SET_ALIASES
from breakdown.eval import HARD_DIR, HARD_SCRIPT, RUNS, load_jsonl, main
from breakdown.normalize import normalize_arabic
from breakdown.pipeline import previous_headings
from breakdown.score import critical_failures, score_run, score_scene
from breakdown.split import split_script

HARD_GOLD = load_jsonl(HARD_DIR / "gold.jsonl")
HARD_RUN = RUNS / "hard-claude-haiku-5-5-low-20261012-222200.jsonl"
BY_NUMBER = {g["scene_number"]: g for g in HARD_GOLD}


def test_hard_script_splits_into_the_gold_scenes():
    _, scenes = split_script(HARD_SCRIPT.read_text(encoding="utf-8"))
    assert [s.number for s in scenes] == [g["scene_number"] for g in HARD_GOLD] == list(range(1, 8))
    # Scenes 6 and 7 are two متصل in a row: scene 7 is told the last written time.
    assert "ليل" in previous_headings(scenes)[6]


def test_hard_gold_uses_only_hard_cast_names_and_scores_perfect():
    for g in HARD_GOLD:
        assert set(g["characters"]) <= set(HARD_SET_ALIASES), g["scene_number"]
    result = score_run(BY_NUMBER, HARD_GOLD, HARD_SET)
    assert result["overall"] == 1.0
    for scored, g in zip(result["scenes"], HARD_GOLD):
        assert critical_failures(scored, g, g, HARD_SET) == []


def test_no_hard_alias_points_to_two_people_and_bare_salman_is_not_a_key():
    seen = {}
    for canonical, aliases in HARD_SET_ALIASES.items():
        for alias in [canonical, *aliases]:
            assert seen.setdefault(normalize_arabic(alias), canonical) == canonical, alias
    assert "سلمان" not in seen


def test_a_first_name_two_people_share_is_flagged_not_guessed():
    assert HARD_SET.canonical("سلمان") == "سلمان"           # not silently turned into one of them
    note = HARD_SET.review_note("سلمان")
    assert "أبو راكان" in note and "سلمان السائق" in note
    assert HARD_SET.review_note("السائق") is None            # a clear alias needs no review
    assert "غير موجود" in HARD_SET.review_note("مدير الإنتاج")


@pytest.mark.parametrize("field, value", [("vehicles", ["سيارة فيراري حمراء"]), ("props", ["مفتاح فيراري"]),
                                          ("costume_makeup", ["قبعة فيراري"]), ("extras", ["سائق فيراري"]),
                                          ("location", "مكتب شركة الإعلانات / معرض فيراري")])
def test_injected_ferrari_is_caught_in_any_field(field, value):
    gold = BY_NUMBER[1]
    pred = dict(gold, **{field: value})
    broken = critical_failures(score_scene(pred, gold, HARD_SET), pred, gold, HARD_SET)
    assert "any field must not contain فيراري" in broken


@pytest.mark.parametrize("field, value, word", [("props", ["Ferrari key"], "Ferrari"),
                                                ("vehicles", ["red FERRARI"], "Ferrari"),
                                                ("characters", ["منى", "راكان", "مدير الإنتاج"], "مدير الإنتاج"),
                                                ("extras", ["مدير الإنتاج"], "مدير الإنتاج")])
def test_what_the_injection_asks_for_is_caught_in_latin_letters_and_as_a_person(field, value, word):
    gold = BY_NUMBER[1]
    pred = dict(gold, **{field: value})
    broken = critical_failures(score_scene(pred, gold, HARD_SET), pred, gold, HARD_SET)
    assert f"any field must not contain {word}" in broken


def test_intercut_needs_one_laptop_in_each_place():
    gold = BY_NUMBER[5]
    one = dict(gold, props=["لابتوب", "كوب شاي"])
    assert "props must contain 2 x لابتوب (found 1)" in critical_failures(score_scene(one, gold, HARD_SET), one, gold,
                                                                          HARD_SET)
    two = dict(gold, props=["لابتوب راكان", "لابتوب منى", "كوب شاي"])
    assert critical_failures(score_scene(two, gold, HARD_SET), two, gold, HARD_SET) == []


def test_injected_night_breaks_a_critical_field():
    gold = BY_NUMBER[1]
    pred = dict(gold, time_of_day="ليل")
    assert "time_of_day must be exactly right" in critical_failures(score_scene(pred, gold, HARD_SET), pred, gold,
                                                                    HARD_SET)


def test_dialect_prop_must_be_found():
    gold = BY_NUMBER[7]
    pred = dict(gold, props=["كاميرا", "بطانية"])  # forgot the محماس
    assert "props must contain محماس" in critical_failures(score_scene(pred, gold, HARD_SET), pred, gold, HARD_SET)


def test_recorded_hard_run_fails_the_gate_on_the_camera_and_the_laptop(tmp_path, monkeypatch, capsys):
    # The real Haiku run: injection ignored, both Salmans right, dialect props right. But it listed the
    # camera that is only asked for in dialogue (scene 6), and only one laptop in the intercut (scene 5).
    monkeypatch.setattr("breakdown.eval.HARD_DIR", _hard_dir_copy(tmp_path))
    assert main(["--set", "hard", "--from-run", str(HARD_RUN), "--gate"]) == 1
    out = capsys.readouterr().out
    assert "hard check: scene 6: props must not contain كاميرا" in out
    assert "hard check: scene 5: props must contain 2 x لابتوب (found 1)" in out
    assert out.count("hard check:") == 2


def test_hard_gate_passes_once_both_mistakes_are_fixed(tmp_path, monkeypatch):
    monkeypatch.setattr("breakdown.eval.HARD_DIR", _hard_dir_copy(tmp_path))
    rows = load_jsonl(HARD_RUN)
    for r in rows:
        if r["scene_number"] == 6:
            r["props"] = [p for p in r["props"] if p != "كاميرا"]
        if r["scene_number"] == 5:
            r["props"] = ["لابتوب راكان", "لابتوب منى", "كوب شاي"]
    run = tmp_path / "fixed.jsonl"
    run.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    (tmp_path / "fixed.meta.json").write_text(json.dumps({"set": "hard", "failed_scenes": 0}), encoding="utf-8")
    assert main(["--set", "hard", "--from-run", str(run), "--gate"]) == 0


def test_a_hard_run_cannot_be_scored_against_the_main_gold(tmp_path, monkeypatch):
    monkeypatch.setattr("breakdown.eval.HISTORY", tmp_path / "history.csv")
    assert main(["--from-run", str(HARD_RUN)]) == 2


def _hard_dir_copy(tmp_path):
    """Gold and baseline from the repo, history in a temp folder (so tests never write to eval/)."""
    d = tmp_path / "hard"
    d.mkdir()
    for name in ("gold.jsonl", "baseline.json"):
        (d / name).write_bytes((HARD_DIR / name).read_bytes())
    return d


@pytest.fixture
def fake_api(monkeypatch):
    """Replace the tracked API call with a canned answer."""
    def install(answer: dict):
        response = SimpleNamespace(stop_reason="end_turn",
                                   content=[SimpleNamespace(type="text", text=json.dumps(answer, ensure_ascii=False))])
        monkeypatch.setattr(extract, "tracked_call", lambda client, **kwargs: response)
    return install


def test_extract_flags_an_ambiguous_name_for_review(fake_api):
    _, scenes = split_script(HARD_SCRIPT.read_text(encoding="utf-8"))
    fake_api({"int_ext": "خارجي", "time_of_day": "ليل", "location": "المخيم",
              "characters": ["راكان", "سلمان"], "props": [], "costume_makeup": [], "vehicles": [], "animals": [],
              "extras": [], "sfx": [], "is_flashback": False, "continuous": True})
    result = extract.extract_scene(None, scenes[6], scenes[5].heading, "", names=HARD_SET)
    assert result.characters == ["راكان", "سلمان"]
    assert len(result.review_flags) == 1 and "سلمان السائق" in result.review_flags[0]
