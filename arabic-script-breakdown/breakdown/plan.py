"""Turn a breakdown into a draft shooting schedule, a budget summary and call sheets. No API calls.

    python -m breakdown.plan examples/breakdown.jsonl --out output/plan --call-sheet-day 2,3
    python -m breakdown.plan output/breakdown.jsonl --locations my.locations.csv --availability my.availability.csv
    python -m breakdown.plan ... --call-sheet-day 2 --approved-by "اسم مساعد المخرج"   # removes the DRAFT mark

Writes: schedule.html, schedule.csv, budget_summary.md, cast_days.csv and call_sheet_day_<N>.html.
Approval is refused while that day has open problems (review flags, times that don't fit the light),
unless --override-problems is given too. Every approval is added to approvals.csv (who, when, what was overridden).
Nothing is sent to anyone: these are files for the assistant director to check, edit and share.
"""

import argparse
import csv
import json
import sys
from datetime import date, datetime
from pathlib import Path

from .planning import (
    WEEKDAYS,
    Schedule,
    Settings,
    TimeRules,
    budget_summary,
    build_schedule,
    load_availability,
    load_locations,
)
from .production_docs import (
    Approval,
    budget_markdown,
    call_sheet_html,
    cast_ids,
    open_problems,
    schedule_html,
    write_schedule_csv,
)
from .schema import SceneBreakdown

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE_BREAKDOWN = ROOT / "examples" / "breakdown.jsonl"
EXAMPLE_LOCATIONS = ROOT / "data" / "kamera_jaddi.locations.csv"
EXAMPLE_AVAILABILITY = ROOT / "data" / "kamera_jaddi.availability.csv"
DEFAULT_TITLE = "كاميرا جدّي - الحلقة الأولى (نص اصطناعي)"


def load_breakdown(path: Path) -> list[SceneBreakdown]:
    lines = path.read_text(encoding="utf-8").splitlines()
    scenes = [SceneBreakdown.model_validate(json.loads(line)) for line in lines if line.strip()]
    return sorted(scenes, key=lambda s: s.scene_number)


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Draft shooting schedule, budget summary and call sheets")
    p.add_argument("breakdown", type=Path, help="breakdown.jsonl written by python -m breakdown")
    p.add_argument("--out", type=Path, default=Path("output/plan"))
    p.add_argument("--locations", type=Path, help="this production's locations file (required for a real script)")
    p.add_argument("--availability", type=Path, help="this production's cast availability file (required too)")
    p.add_argument("--start", type=date.fromisoformat, default=date(2026, 10, 31),
                   help="first shoot date (the example starts on a Saturday: the week runs Saturday to Thursday)")
    p.add_argument("--days-off", default="fri", help="comma-separated, e.g. fri or fri,sat")
    p.add_argument("--max-scenes", type=int, default=6)
    p.add_argument("--max-pages", type=float, default=3, help="page limit per day")
    p.add_argument("--max-sites", type=int, default=2, help="sites per day (2 = at most one company move)")
    p.add_argument("--sunrise", help="HH:MM for every date (default: the Riyadh table, about 10 minutes off)")
    p.add_argument("--sunset", help="HH:MM for every date")
    p.add_argument("--call-sheet-day", default="1", help="shoot day number(s) for call sheets: 2, or 2,3, or all")
    p.add_argument("--approved-by", default=None, help="name of the person who approves these call sheets")
    p.add_argument("--override-problems", action="store_true",
                   help="approve even with open problems; they stay listed on the sheet under the approver's name")
    p.add_argument("--title", default=DEFAULT_TITLE)
    return p.parse_args(argv)


def input_files(args: argparse.Namespace) -> tuple[Path, Path] | str:
    """The locations and availability files, or an error message.

    The synthetic example files are only used for the example breakdown. A real script must bring its
    own: a schedule built on another show's availability would look fine and be wrong.
    """
    if args.locations and args.availability:
        return args.locations, args.availability
    if args.breakdown.resolve() == EXAMPLE_BREAKDOWN:
        return args.locations or EXAMPLE_LOCATIONS, args.availability or EXAMPLE_AVAILABILITY
    return ("This is not the example breakdown, so give this production's own files: "
            "--locations <file.csv> --availability <file.csv> (see docs/دليل-المستخدم.md).")


def call_sheet_days(spec: str, schedule: Schedule) -> list[int] | str:
    """'2' or '2,3' or 'all' -> day numbers, or an error message if a day does not exist."""
    if spec.strip() == "all":
        return [d.number for d in schedule.days]
    try:
        days = [int(x) for x in spec.split(",") if x.strip()]
    except ValueError:
        return f"--call-sheet-day must be a number, a list like 2,3, or all (got {spec!r})"
    wrong = [n for n in days if not 1 <= n <= len(schedule.days)]
    if wrong:
        return f"no shoot day {', '.join(map(str, wrong))}: the schedule has days 1 to {len(schedule.days)}"
    return days


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args(argv)
    files = input_files(args)
    if isinstance(files, str):
        print(files)
        return 2
    settings = Settings(start=args.start, days_off={WEEKDAYS[d.strip()] for d in args.days_off.split(",") if d.strip()},
                        max_scenes=args.max_scenes, max_eighths=round(args.max_pages * 8), max_sites=args.max_sites)
    rules = TimeRules(sunrise=args.sunrise, sunset=args.sunset)
    schedule = build_schedule(load_breakdown(args.breakdown), load_locations(files[0]),
                              load_availability(files[1]), settings)
    summary = budget_summary(schedule)

    # Check everything before writing anything, so a mistake never leaves half the files behind.
    sheet_days = call_sheet_days(args.call_sheet_day, schedule)
    if isinstance(sheet_days, str):
        print(sheet_days)
        return 2
    problems = {n: open_problems(schedule.day(n), rules) for n in sheet_days}
    if args.approved_by and not args.override_problems and any(problems.values()):
        print("Not approved: these call sheets still have open problems. Solve them and run again, or add "
              "--override-problems to approve anyway under your name (they stay listed on the sheet).")
        for n, items in problems.items():
            for item in items:
                print(f"  day {n}: {item}")
        return 3

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
    approval = Approval(args.approved_by, args.override_problems) if args.approved_by else None
    for n in sheet_days:
        sheet = args.out / f"call_sheet_day_{n}.html"
        sheet.write_text(call_sheet_html(schedule, n, args.title, approval, rules), encoding="utf-8")
    if approval:
        log_approvals(args.out / "approvals.csv", schedule, sheet_days, approval, problems)

    print(f"{summary.shoot_days} shoot days ({summary.night_shifts} night), {summary.company_moves} company moves, "
          f"{summary.unscheduled} unscheduled, {len(summary.flagged_scenes)} scenes need review")
    for strip, why in schedule.unscheduled:
        print(f"  scene {strip.number} not scheduled: {why}")
    for n, items in problems.items():
        if items:
            print(f"  day {n}: {len(items)} open problem(s) on the call sheet")
    status = f"approved by {args.approved_by}" if approval else "DRAFT"
    print(f"Files in {args.out}/  (call sheets for day {', '.join(map(str, sheet_days))}: {status})")
    return 0


def log_approvals(path: Path, schedule: Schedule, days: list[int], approval: Approval,
                  problems: dict[int, list[str]]) -> None:
    """One row per approved call sheet: who, when, which day, and any problems they overrode."""
    new = not path.exists()
    with open(path, "a", encoding="utf-8-sig" if new else "utf-8", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["الوقت", "اليوم", "التاريخ", "اعتمدها", "مشاكل تم تجاوزها"])
        for n in days:
            w.writerow([datetime.now().isoformat(timespec="seconds"), n, schedule.day(n).date.isoformat(),
                        approval.by, " | ".join(problems[n])])


if __name__ == "__main__":
    raise SystemExit(main())
