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


def build_report(conn: sqlite3.Connection) -> str:
    by_operation = conn.execute(
        "SELECT operation, COUNT(*), SUM(cost_usd) FROM calls "
        "GROUP BY operation ORDER BY SUM(cost_usd) DESC").fetchall()
    by_model = conn.execute(
        "SELECT model, COUNT(*), SUM(cost_usd) FROM calls "
        "GROUP BY model ORDER BY SUM(cost_usd) DESC").fetchall()
    by_day = conn.execute(
        "SELECT substr(ts, 1, 10), COUNT(*), SUM(cost_usd) FROM calls "
        "GROUP BY substr(ts, 1, 10) ORDER BY 1").fetchall()

    # Cost per run: add up each run first, then take the mean and max.
    runs = conn.execute(
        "SELECT run_id, SUM(cost_usd) AS c FROM calls WHERE run_id IS NOT NULL GROUP BY run_id"
    ).fetchall()
    run_costs = [r["c"] for r in runs]

    tokens = conn.execute(
        "SELECT SUM(input_tokens), SUM(output_tokens), SUM(cache_creation_tokens), "
        "SUM(cache_read_tokens) FROM calls").fetchone()

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
    parts.append(f"Total: ${total:.5f} of ${budget:.2f} budget ({100 * total / budget:.2f}% used)")
    return "\n\n".join(parts)
