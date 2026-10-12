from breakdown.report import character_schedule, location_schedule, write_csv
from breakdown.schema import SceneBreakdown


def scene(n, location, characters, eighths=2):
    return SceneBreakdown(
        scene_number=n, heading=f"مشهد {n}", int_ext="داخلي", time_of_day="نهار", location=location,
        characters=characters, props=[], costume_makeup=[], vehicles=[], animals=[], extras=[], sfx=[],
        is_flashback=False, continuous=False, length_eighths=eighths,
    )


SCENES = [scene(1, "غرفة فهد", ["فهد"]), scene(2, "المجلس", ["فهد", "أبو فهد"]), scene(3, "غرفه فهد", ["فهد"])]


def test_character_schedule_lists_scenes_per_actor():
    assert character_schedule(SCENES) == {"فهد": [1, 2, 3], "أبو فهد": [2]}


def test_location_schedule_groups_spelling_variants():
    groups = location_schedule(SCENES)
    assert groups["غرفة فهد"]["scenes"] == [1, 3]
    assert groups["غرفة فهد"]["eighths"] == 4


def test_csv_has_bom_for_excel(tmp_path):
    path = tmp_path / "sheet.csv"
    write_csv(SCENES, path)
    raw = path.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")  # the BOM that makes Excel read UTF-8
    assert "غرفة فهد" in raw.decode("utf-8-sig")
