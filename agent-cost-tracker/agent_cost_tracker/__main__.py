"""Command line: python -m agent_cost_tracker report [--operation NAME]"""

import sys

from dotenv import find_dotenv, load_dotenv

from . import ledger
from .report import build_report


def main() -> None:
    load_dotenv(find_dotenv(usecwd=True))
    args = sys.argv[1:]  # e.g. ["report"] or ["report", "--operation", "extract_purchase_request"]
    if args == ["report"]:
        operation = None
    elif len(args) == 3 and args[0] == "report" and args[1] == "--operation":
        operation = args[2]
    else:
        print("usage: python -m agent_cost_tracker report [--operation NAME]")
        sys.exit(2)
    conn = ledger.connect()
    print(f"Ledger: {ledger.db_path()}\n")
    print(build_report(conn, operation))


if __name__ == "__main__":
    main()
