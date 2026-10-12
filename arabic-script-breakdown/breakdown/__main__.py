"""Run the agent on a script and write the production files.

    python -m breakdown my_script.txt --out output                          # names: the script's own cast list
    python -m breakdown my_script.txt --aliases my_script.aliases.csv       # names: this script's alias file
    python -m breakdown data/kamera_jaddi.txt --aliases kamera_jaddi        # the example script's built-in map

With no --aliases, only the exact names in the script's cast list are accepted. Any other name the
model writes (a nickname, a title, a first name two people share) is kept as written and flagged for
a person to check. A map written for another script is never used by accident.
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

from .cast_aliases import BUILT_IN, CastNames
from .extract import DEFAULT_MODEL
from .pipeline import breakdown_script, make_client
from .report import write_csv, write_jsonl, write_schedule
from .split import cast_list, split_script


def names_for(script: str, aliases: str | None) -> tuple[CastNames, str]:
    """The alias map for this run, and a line saying which one it is."""
    if aliases in BUILT_IN:
        return BUILT_IN[aliases], f"names: built-in map '{aliases}'"
    if aliases:
        return CastNames.from_csv(Path(aliases)), f"names: alias file {aliases}"
    names = CastNames.from_cast_list(cast_list(split_script(script)[0]))
    if not names.cast:
        return names, "names: NO cast list found (a line 'الشخصيات:' then 'name: description'), so every name is flagged"
    return names, f"names: the script's cast list only ({len(names.cast)} names); nicknames will be flagged"


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Arabic script breakdown")
    parser.add_argument("script", type=Path)
    parser.add_argument("--out", type=Path, default=Path("output"))
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--effort", choices=["low", "medium", "high"], default=None)
    parser.add_argument("--aliases", default=None,
                        help="this script's alias file (CSV: cast name, other names separated by ;) "
                             f"or a built-in map: {', '.join(BUILT_IN)}. Default: the script's cast list only")
    args = parser.parse_args(argv)

    script = args.script.read_text(encoding="utf-8")
    names, which = names_for(script, args.aliases)
    print(which)
    client = make_client()
    run_id = f"run-{datetime.now():%Y%m%d-%H%M%S}"
    scenes, errors = breakdown_script(script, client, model=args.model, effort=args.effort, run_id=run_id,
                                      names=names)
    args.out.mkdir(parents=True, exist_ok=True)
    write_jsonl(scenes, args.out / "breakdown.jsonl")
    write_csv(scenes, args.out / "production_sheet.csv")
    write_schedule(scenes, args.out / "schedule.md")
    flagged = sum(bool(s.review_flags) for s in scenes)
    print(f"{len(scenes)} scenes written to {args.out}/ (run {run_id}); {flagged} scenes have names to check")
    for e in errors:
        print("FAILED", e)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
