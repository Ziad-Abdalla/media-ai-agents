"""Turn a breakdown into a draft shooting schedule, a budget summary and a call sheet. No API calls.

    python -m breakdown.plan examples/breakdown.jsonl --out output/plan
    python -m breakdown.plan output/breakdown.jsonl --start 2026-11-01 --call-sheet-day 2
    python -m breakdown.plan ... --approved-by "اسم مساعد المخرج"   # removes the DRAFT mark from the call sheet

Writes: schedule.html, schedule.csv, budget_summary.md, cast_days.csv and call_sheet_day_<N>.html.
Nothing is sent to anyone: these are files for the assistant director to check, edit and share.
"""

import argparse
import csv
import json
import sys
from datetime import date
from pathlib import Path

from .planning import WEEKDAYS, Settings, budget_summary, build_schedule, load_availability, load_locations
from .production_docs import budget_markdown, call_sheet_html, cast_ids, schedule_html, write_schedule_csv
from .schema import SceneBreakdown

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TITLE = "كاميرا جدّي - الحلقة الأولى (نص اصطناعي)"


def load_breakdown(path: Path) -> list[SceneBreakdown]:
    lines = path.read_text(encoding="utf-8").splitlines()
    scenes = [SceneBreakdown.model_validate(json.loads(line)) for line in lines if line.strip()]
    return sorted(scenes, key=lambda s: s.scene_number)


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description="Draft shooting schedule, budget summary and call sheet")
    p.add_argument("breakdown", type=Path, help="breakdown.jsonl written by python -m breakdown")
    p.add_argument("--out", type=Path, default=Path("output/plan"))
    p.add_argument("--locations", type=Path, default=ROOT / "data" / "kamera_jaddi.locations.csv")
    p.add_argument("--availability", type=Path, default=ROOT / "data" / "kamera_jaddi.availability.csv")
    p.add_argument("--start", type=date.fromisoformat, default=date(2026, 11, 1), help="first shoot date")
    p.add_argument("--days-off", default="fri", help="comma-separated, e.g. fri or fri,sat")
    p.add_argument("--max-scenes", type=int, default=6)
    p.add_argument("--max-pages", type=float, default=3, help="page limit per day")
    p.add_argument("--max-sites", type=int, default=2, help="sites per day (2 = at most one company move)")
    p.add_argument("--call-sheet-day", type=int, default=1)
    p.add_argument("--approved-by", default=None, help="name of the person who approved the call sheet")
    p.add_argument("--title", default=DEFAULT_TITLE)
    args = p.parse_args(argv)

    settings = Settings(start=args.start, days_off={WEEKDAYS[d.strip()] for d in args.days_off.split(",") if d.strip()},
                        max_scenes=args.max_scenes, max_eighths=round(args.max_pages * 8), max_sites=args.max_sites)
    schedule = build_schedule(load_breakdown(args.breakdown), load_locations(args.locations),
                              load_availability(args.availability), settings)
    summary = budget_summary(schedule)

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "schedule.html").write_text(schedule_html(schedule, args.title), encoding="utf-8")
    write_schedule_csv(schedule, args.out / "schedule.csv")
    (args.out / "budget_summary.md").write_text(budget_markdown(summary), encoding="utf-8")
    ids = cast_ids(summary)
    with open(args.out / "cast_days.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["رقم", "الشخصية", "أيام العمل", "الأيام", "أيام انتظار"])
        for a in summary.actors:
            w.writerow([ids[a.name], a.name, len(a.days), " ".join(map(str, a.days)), a.hold_days])
    sheet = args.out / f"call_sheet_day_{args.call_sheet_day}.html"
    sheet.write_text(call_sheet_html(schedule, args.call_sheet_day, args.title, args.approved_by), encoding="utf-8")

    print(f"{summary.shoot_days} shoot days ({summary.night_shifts} night), {summary.company_moves} company moves, "
          f"{summary.unscheduled} unscheduled, {len(summary.flagged_scenes)} scenes need review")
    for strip, why in schedule.unscheduled:
        print(f"  scene {strip.number} not scheduled: {why}")
    print(f"Files in {args.out}/  (call sheet: {sheet.name}, {'approved' if args.approved_by else 'DRAFT'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
