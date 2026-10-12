import json
from pathlib import Path

from breakdown.score import match_lists, prf, regression_check, score_run, score_scene

GOLD = {
    "scene_number": 1, "int_ext": "داخلي", "time_of_day": "ليل", "location": "بيت أبو فهد - المجلس",
    "characters": ["أبو فهد", "أم فهد", "فهد"], "props": ["فنجال قهوة", "جوال"],
}


def test_perfect_scene():
    s = score_scene(dict(GOLD), GOLD)
    assert s["int_ext"] and s["time_of_day"] and s["location"]
    assert s["characters"] == {"tp": 3, "extra": [], "missing": []}


def test_aliases_count_as_the_same_person():
    matched, extra, missing = match_lists(["سعد", "نورة", "فهود"], GOLD["characters"], "characters")
    assert len(matched) == 3 and not extra and not missing


def test_mentioned_character_is_a_false_positive():
    # The model listed Turki, who is only talked about in the scene.
    matched, extra, missing = match_lists(["أبو فهد", "فهد", "تركي"], GOLD["characters"], "characters")
    assert extra == ["تركي"]
    assert missing == ["أم فهد"]


def test_location_spelling_differences_are_fine():
    pred = dict(GOLD, location="بيت ابو فهد، المجلس")
    assert score_scene(pred, GOLD)["location"]


def test_missing_scene_counts_as_all_wrong():
    s = score_scene(None, GOLD)
    assert not s["int_ext"] and not s["location"]
    assert s["props"]["missing"] == ["فنجال قهوة", "جوال"]


def test_prf_numbers():
    assert prf(2, 1, 1) == (2 / 3, 2 / 3, 2 / 3)
    assert prf(0, 0, 0) == (1.0, 1.0, 1.0)  # nothing to find, nothing invented: perfect


def test_empty_props_scene_is_perfect_when_model_lists_nothing():
    gold = dict(GOLD, props=[])
    assert score_scene(dict(gold), gold)["props"] == {"tp": 0, "extra": [], "missing": []}


def test_gate_blocks_a_drop_bigger_than_threshold():
    base = {"characters": 0.90, "props": 0.70}
    assert regression_check({"characters": 0.88, "props": 0.70}, base, 0.05) == []
    failures = regression_check({"characters": 0.80, "props": 0.72}, base, 0.05)
    assert len(failures) == 1 and failures[0].startswith("characters")


def test_whole_gold_file_scores_perfect_against_itself():
    golds = [json.loads(line) for line in
             (Path(__file__).parent.parent / "eval" / "gold.jsonl").read_text(encoding="utf-8").splitlines()]
    result = score_run({g["scene_number"]: g for g in golds}, golds)
    assert result["overall"] == 1.0
    assert len(golds) == 26
