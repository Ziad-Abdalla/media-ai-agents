"""Command line: python -m agent_cost_tracker report"""

import sys

from dotenv import find_dotenv, load_dotenv

from . import ledger
from .report import build_report


def main() -> None:
    load_dotenv(find_dotenv(usecwd=True))
    if len(sys.argv) < 2 or sys.argv[1] != "report":
        print("usage: python -m agent_cost_tracker report")
        sys.exit(2)
    conn = ledger.connect()
    print(f"Ledger: {ledger.db_path()}\n")
    print(build_report(conn))


if __name__ == "__main__":
    main()
