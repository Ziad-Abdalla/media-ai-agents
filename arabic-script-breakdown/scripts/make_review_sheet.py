"""Build eval/REVIEW_FOR_ZIAD.md: one table a native speaker can check the gold labels with.

It also lists where the saved model runs disagreed with the gold, because those
are the labels most worth a second look (either the model is wrong, or the label is).

    python scripts/make_review_sheet.py
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from breakdown.eval import GOLD, RUNS, SCRIPT, load_jsonl  # noqa: E402
from breakdown.score import scene_errors, score_scene  # noqa: E402
from breakdown.split import split_script  # noqa: E402

OUT = ROOT / "eval" / "REVIEW_FOR_ZIAD.md"


def excerpt(text: str, limit: int = 170) -> str:
    """The first action lines of a scene (skip the heading and the dialogue)."""
    body = [line.strip() for line in text.splitlines()[1:] if line.strip()]
    action = [line for line in body if ":" not in line[:25]]
    short = " ".join(action or body)  # scene 8 has no plain action lines, so fall back to everything
    return short[:limit] + ("…" if len(short) > limit else "")


def disagreements(golds: list[dict]) -> dict[int, set[str]]:
    found: dict[int, set[str]] = {g["scene_number"]: set() for g in golds}
    for run in sorted(RUNS.glob("*.jsonl")):
        preds = {p["scene_number"]: p for p in load_jsonl(run)}
        for g in golds:
            pred = preds.get(g["scene_number"])
            for err in scene_errors(score_scene(pred, g), pred, g):
                found[g["scene_number"]].add(err)
    return found


def cell(value) -> str:
    return "، ".join(value) if value else "—"


def main() -> None:
    golds = load_jsonl(GOLD)
    _, scenes = split_script(SCRIPT.read_text(encoding="utf-8"))
    texts = {s.number: s for s in scenes}
    disagree = disagreements(golds)

    out = [
        "# Gold labels: native-speaker review",
        "",
        "These are the answers the eval treats as correct. I drafted them; they need your check as the",
        "native speaker before the README can say they were reviewed. It should take about 20 minutes.",
        "",
        "**How to review:** open `data/kamera_jaddi.txt` next to this file. For each row, read the scene and",
        "check the label columns. If something is wrong, write the fix in the last column (or edit",
        "`eval/gold.jsonl` directly). When done, re-run `python scripts/make_review_sheet.py` and",
        "`python -m breakdown.eval --from-run <a saved run>` to see the new scores (free, no API call).",
        "",
        "**The labeling rules** (the same rules the agent gets in its prompt):",
        "- Characters = people physically in the scene, speaking or silent. Talked about, in a photo or on a",
        "  screen = not present. Names as in the cast list (سعد → أبو فهد).",
        "- Props = objects seen or handled on set. Not things only said in dialogue, not furniture, not costume.",
        "- `متصل` scenes take the time of the scene before. `آخر الليل` counts as ليل.",
        "",
        "Columns: **#** scene · **Scene start** first action lines · **I/E · Time** · **Location** ·",
        "**Characters** · **Props** · **Why this scene is in the set** · **Models disagreed** (from saved runs).",
        "",
        "| # | Scene start | I/E · Time | Location | Characters | Props | Why this scene is in the set "
        "| Models disagreed | Your fix |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for g in golds:
        n = g["scene_number"]
        time = g["time_of_day"] + (" (متصل)" if g["continuous"] else "") + (" · فلاش باك" if g["is_flashback"] else "")
        dis = "<br>".join(sorted(disagree[n])) or "—"
        out.append(
            f"| {n} | {excerpt(texts[n].text)} | {g['int_ext']} · {time} | {g['location']} "
            f"| {cell(g['characters'])} | {cell(g['props'])} | {g['hard_case']} | {dis} | |"
        )
    OUT.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"Wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
