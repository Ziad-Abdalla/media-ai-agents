# agent-cost-tracker

A small Python library that every Claude API call in my agents goes through.
It records what each call cost, tagged by **operation** (what the call was for) and
**run** (which agent run it belonged to), stores it in SQLite, and refuses to make
a call once a hard budget is used up.

```python
from anthropic import Anthropic
from agent_cost_tracker import tracked_call, BudgetExceeded

client = Anthropic()
response = tracked_call(
    client,
    operation="extract_purchase_request",   # what this call is for
    run_id="run-42",                         # which agent run it belongs to
    model="claude-haiku-5-5",
    max_tokens=1024,
    messages=[{"role": "user", "content": "..."}],
)
```

Then:

```
python -m agent_cost_tracker report
```

```
By operation:
  extract_purchase_request           calls=   6  $  0.00412
...
Cost per run: 6 runs, mean $0.00069, max $0.00093
Total: $0.00412 of $15.00 budget (0.03% used)
```

## Why per operation, not per call

A single call's cost tells you almost nothing. What a business cares about is
"what does it cost us to turn one email into one purchase order?" That is the
cost of the **operation** (and of the **run**, which is all operations for one
request). If extraction costs $0.0007 per request, I can multiply by the number of
requests a month and get a real number to put in front of a manager. Per-operation
totals also show *which step* is expensive, which is where you act.

## The first two things I do when cost spikes

1. **Find what grew.** Run the report and compare by operation, by model and by
   token type (input, output, cache write, cache read). Usually one operation on
   one model grew, and usually it's input tokens (a prompt that got longer, e.g.
   a whole email thread pasted in instead of the last message).
2. **Cap it, then cut it.** The hard budget already stops runaway spend. Then for
   that one operation: move it to a smaller model or lower effort if quality
   allows, trim the prompt, and cache the part of the prompt that never changes
   (system prompt, schemas) so it's billed at the cache-read price.

## How it works

| File | What it does |
|---|---|
| `agent_cost_tracker/prices.py` | Price table (one place to update). |
| `agent_cost_tracker/ledger.py` | SQLite table `calls`, one row per API call. |
| `agent_cost_tracker/tracker.py` | `tracked_call()`: check budget, call, time it, price it, save the row. |
| `agent_cost_tracker/report.py` | The report: by operation, model, day, cost per run, budget used. |

Budget check happens **before** the call: if total spend in the ledger is already at
or over `COST_BUDGET_USD`, `BudgetExceeded` is raised and no request is sent. One call
can still cross the line (we don't know its cost until it returns), so the budget can
be overshot by at most one call.

Optional soft alert: `tracked_call(..., alert_usd=0.50)` logs a warning when that
operation's total passes $0.50 but keeps going.

### Prices used (USD per 1M tokens, Anthropic pricing as of 2026-10)

| Model | Input | Output | Cache write (5 min) | Cache read |
|---|---|---|---|---|
| claude-haiku-5-5 (prompt ≤ 100K tokens) | 0.10 | 0.50 | 0.125 | 0.01 (assumed: 0.1× input) |
| claude-haiku-5-5 (prompt > 100K tokens) | 0.50 | 2.50 | 0.625 | 0.05 (assumed: 0.1× input) |
| claude-sonnet-5-5 | 2.00 | 10.00 | 2.50 | 0.20 |

"Prompt" here means input + cache write + cache read tokens for that call.

## Install

```
pip install -e ../agent-cost-tracker                                  # local, next to your project
pip install git+https://github.com/Ziad-Abdalla/agent-cost-tracker   # from GitHub
```

Settings (environment variables or a `.env` file, see `.env.example`):

| Variable | Default | Meaning |
|---|---|---|
| `COST_DB_PATH` | `./costs.sqlite` | Ledger file. Point several projects at the same file to share one budget. |
| `COST_BUDGET_USD` | `15` | Hard stop for total spend in the ledger. |

## Tests

```
python -m venv .venv && .venv/Scripts/pip install -e ".[dev]"
.venv/Scripts/python -m pytest
```

The tests use a fake client, so they never call the API and cost nothing.
