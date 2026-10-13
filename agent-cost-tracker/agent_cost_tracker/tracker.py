"""tracked_call: the one function every Claude API call goes through."""

import logging
import os
import time

from . import ledger
from .prices import cost_usd, price_key

log = logging.getLogger(__name__)


class BudgetExceeded(RuntimeError):
    """Raised before a call when the total spend has reached the budget."""


def budget_usd() -> float:
    return float(os.environ.get("COST_BUDGET_USD", "15"))


def tracked_call(client, *, operation: str, run_id: str | None = None,
                 alert_usd: float | None = None, db_path: str | None = None,
                 **create_kwargs):
    """Call client.messages.create(**create_kwargs), record the cost, return the response.

    operation: a short name for *what* this call is for, like "extract_request".
    run_id:    groups several calls that belong to one agent run.
    alert_usd: optional soft limit. If this operation's total spend goes over it,
               we log a warning but do not stop.
    """
    conn = ledger.connect(db_path)
    try:
        # 1. Checks BEFORE spending anything.
        # Fail now if we can't price this model, so we never pay for a call we can't record.
        price_key(create_kwargs["model"], 0)
        # Hard stop: refuse the call if the budget is already used up.
        spent = ledger.total_spend(conn)
        limit = budget_usd()
        if spent >= limit:
            raise BudgetExceeded(f"Spent ${spent:.4f} of ${limit:.2f} budget. No call made.")

        # 2. Make the real call and time it.
        started = time.perf_counter()
        response = client.messages.create(**create_kwargs)
        latency_ms = int((time.perf_counter() - started) * 1000)

        # 3. Work out the cost from the usage numbers the API sends back.
        usage = response.usage
        cache_write = usage.cache_creation_input_tokens or 0
        cache_read = usage.cache_read_input_tokens or 0
        model = create_kwargs["model"]  # price by the model we asked for
        cost = cost_usd(model, usage.input_tokens, usage.output_tokens,
                        cache_write, cache_read)

        # 4. Save one row in the ledger.
        ledger.record_call(
            conn,
            operation=operation,
            run_id=run_id,
            model=model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_creation_tokens=cache_write,
            cache_read_tokens=cache_read,
            latency_ms=latency_ms,
            cost_usd=cost,
            stop_reason=response.stop_reason,
        )

        # 5. Soft alert per operation.
        if alert_usd is not None:
            op_total = ledger.total_spend(conn, operation)
            if op_total > alert_usd:
                log.warning("Operation %r has spent $%.4f (alert at $%.4f)",
                            operation, op_total, alert_usd)
        return response
    finally:
        conn.close()
