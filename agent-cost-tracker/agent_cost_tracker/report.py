"""Text report over the ledger: where is the money going?"""

import sqlite3

from .tracker import budget_usd


def _table(title: str, rows: list[sqlite3.Row]) -> str:
    lines = [title]
    for r in rows:
        lines.append(f"  {str(r[0]):<34} calls={r[1]:>4}  ${r[2]:>9.5f}")
    if not rows:
        lines.append("  (no calls yet)")
    return "\n".join(lines)


def build_report(conn: sqlite3.Connection, operation: str | None = None) -> str:
    # Optional filter on one operation. With operation=None, "? IS NULL" is true
    # for every row, so nothing is filtered out.
    match = "(? IS NULL OR operation = ?)"
    params = (operation, operation)

    by_operation = conn.execute(
        f"SELECT operation, COUNT(*), SUM(cost_usd) FROM calls WHERE {match} "
        "GROUP BY operation ORDER BY SUM(cost_usd) DESC", params).fetchall()
    by_model = conn.execute(
        f"SELECT model, COUNT(*), SUM(cost_usd) FROM calls WHERE {match} "
        "GROUP BY model ORDER BY SUM(cost_usd) DESC", params).fetchall()
    by_day = conn.execute(
        f"SELECT substr(ts, 1, 10), COUNT(*), SUM(cost_usd) FROM calls WHERE {match} "
        "GROUP BY substr(ts, 1, 10) ORDER BY 1", params).fetchall()

    # Cost per run: add up each run first, then take the mean and max.
    runs = conn.execute(
        f"SELECT run_id, SUM(cost_usd) AS c FROM calls WHERE {match} "
        "AND run_id IS NOT NULL GROUP BY run_id", params).fetchall()
    run_costs = [r["c"] for r in runs]

    tokens = conn.execute(
        "SELECT SUM(input_tokens), SUM(output_tokens), SUM(cache_creation_tokens), "
        f"SUM(cache_read_tokens) FROM calls WHERE {match}", params).fetchone()

    total = sum(r[2] for r in by_operation)
    budget = budget_usd()

    parts = [
        _table("By operation:", by_operation),
        _table("By model:", by_model),
        _table("By day (UTC):", by_day),
    ]
    if run_costs:
        mean = sum(run_costs) / len(run_costs)
        parts.append(f"Cost per run: {len(run_costs)} runs, mean ${mean:.5f}, max ${max(run_costs):.5f}")
    parts.append(
        "Tokens: input={} output={} cache_write={} cache_read={}".format(*(t or 0 for t in tokens)))
    if operation:
        # The budget covers the whole ledger, so a filtered total isn't compared to it.
        parts.append(f"Total for {operation}: ${total:.5f}")
    elif budget > 0:
        parts.append(f"Total: ${total:.5f} of ${budget:.2f} budget ({100 * total / budget:.2f}% used)")
    else:
        parts.append(f"Total: ${total:.5f} (budget is $0, so every call is blocked)")
    return "\n\n".join(parts)
