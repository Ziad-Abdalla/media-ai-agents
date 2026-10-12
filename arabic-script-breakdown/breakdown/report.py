"""Turn scene breakdowns into the files a production team actually uses.

1. production_sheet.csv: one row per scene (opens in Excel with Arabic shown correctly).
2. schedule.md: for each actor, which scenes they are needed in; for each location,
   which scenes are shot there. This is what a scheduler groups the shooting days by.
"""

import csv
import json
from collections import defaultdict
from pathlib import Path

from .normalize import item_key
from .schema import SceneBreakdown

COLUMNS = [
    ("scene_number", "رقم المشهد"),
    ("int_ext", "داخلي/خارجي"),
    ("time_of_day", "الوقت"),
    ("location", "المكان"),
    ("characters", "الشخصيات"),
    ("props", "الإكسسوار"),
    ("costume_makeup", "الأزياء والمكياج"),
    ("vehicles", "المركبات"),
    ("animals", "الحيوانات"),
    ("extras", "الكومبارس"),
    ("sfx", "المؤثرات"),
    ("is_flashback", "فلاش باك"),
    ("continuous", "متصل"),
    ("length_eighths", "الطول (أثمان صفحة)"),
]


def _cell(value) -> str:
    if isinstance(value, list):
        return "، ".join(value)
    if isinstance(value, bool):
        return "نعم" if value else ""
    return str(value)


def write_jsonl(scenes: list[SceneBreakdown], path: Path) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for s in scenes:
            f.write(json.dumps(s.model_dump(), ensure_ascii=False) + "\n")


def write_csv(scenes: list[SceneBreakdown], path: Path) -> None:
    # "utf-8-sig" adds a BOM at the start of the file. Without it, Excel guesses the
    # wrong encoding and the Arabic shows up as garbage characters.
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([arabic for _, arabic in COLUMNS])
        for s in scenes:
            row = s.model_dump()
            writer.writerow([_cell(row[key]) for key, _ in COLUMNS])


def character_schedule(scenes: list[SceneBreakdown]) -> dict[str, list[int]]:
    """Actor -> the scenes they are needed for, most-needed actor first."""
    needed: dict[str, list[int]] = defaultdict(list)
    for s in scenes:
        for name in s.characters:
            needed[name].append(s.scene_number)
    return dict(sorted(needed.items(), key=lambda kv: -len(kv[1])))


def location_schedule(scenes: list[SceneBreakdown]) -> dict[str, dict]:
    """Location -> its scenes and total length. Spellings are grouped with item_key."""
    groups: dict[str, dict] = {}
    for s in scenes:
        key = item_key(s.location)
        group = groups.setdefault(key, {"name": s.location, "scenes": [], "eighths": 0})
        group["scenes"].append(s.scene_number)
        group["eighths"] += s.length_eighths
    return {g["name"]: g for g in sorted(groups.values(), key=lambda g: -len(g["scenes"]))}


def write_schedule(scenes: list[SceneBreakdown], path: Path) -> None:
    lines = ["# Schedule view", "", "## Actors: which scenes each one is needed for", "",
             "| الشخصية | عدد المشاهد | المشاهد |", "|---|---|---|"]
    for name, nums in character_schedule(scenes).items():
        lines.append(f"| {name} | {len(nums)} | {', '.join(map(str, nums))} |")
    lines += ["", "## Locations: shoot these scenes together", "",
              "| المكان | عدد المشاهد | المشاهد | الطول (صفحات) |", "|---|---|---|---|"]
    for name, g in location_schedule(scenes).items():
        lines.append(f"| {name} | {len(g['scenes'])} | {', '.join(map(str, g['scenes']))} | {g['eighths'] / 8:.2f} |")
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
