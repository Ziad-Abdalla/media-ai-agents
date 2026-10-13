# agent-cost-tracker

A small Python library that every Claude API call in my Python agents goes through.
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
python -m agent_cost_tracker report                                       # everything in the ledger
python -m agent_cost_tracker report --operation extract_purchase_request  # one operation only
```

Real output of the second command after the odoo-request-agent demo (6 emails, one Haiku 5.5 call each):

```
By operation:
  extract_purchase_request           calls=   6  $  0.00168

By model:
  claude-haiku-5-5                   calls=   6  $  0.00168

By day (UTC):
  2026-10-12                         calls=   6  $  0.00168

Cost per run: 6 runs, mean $0.00028, max $0.00032

Tokens: input=9503 output=1463 cache_write=0 cache_read=0

Total for extract_purchase_request: $0.00168
```

## Why per operation, not per call

A single call's cost tells you almost nothing. What a business cares about is
"what does it cost us to turn one email into one purchase order?" That is the
cost of the **operation** (and of the **run**, which is all operations for one
request). If extraction costs $0.00028 per request (the number above), I can multiply by the number of
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
| `agent_cost_tracker/tracker.py` | `tracked_call()`: check the model has a price and the budget isn't used up, call, time it, price it, save the row. |
| `agent_cost_tracker/report.py` | The report: by operation, model, day, cost per run, budget used. Optional `--operation` filter. |
| `agent_cost_tracker/__main__.py` | The `report` command. |

Two checks happen **before** the call, so a failed check never costs money:

- If the model isn't in the price table, `KeyError` is raised and no request is sent
  (otherwise we'd pay for a call we can't record).
- If total spend in the ledger is already at or over `COST_BUDGET_USD`,
  `BudgetExceeded` is raised and no request is sent.

We don't know a call's cost until it returns, so the last call that starts under the
line can end above it. With one agent making one call at a time, that's at most one
call over. The check and the save are not one transaction, so with N calls running at
the same time (threads, or several projects sharing one ledger) up to N calls can
cross the line. To close that gap I'd reserve an estimated cost in the ledger inside a
lock before the call, then replace it with the real cost after.

`latency_ms` and `stop_reason` are saved on every row for debugging; the report
doesn't show them.

Optional soft alert: `tracked_call(..., alert_usd=0.50)` logs a warning when that
operation's total passes $0.50 but keeps going.

### Prices used (USD per 1M tokens, Anthropic pricing as of 2026-10)

| Model | Input | Output | Cache write (5 min) | Cache read |
|---|---|---|---|---|
| claude-haiku-5-5 (prompt ≤ 100K tokens) | 0.10 | 0.50 | 0.125 | 0.01 (assumed: 0.1× input) |
| claude-haiku-5-5 (prompt > 100K tokens) | 0.50 | 2.50 | 0.625 | 0.05 (assumed: 0.1× input) |
| claude-sonnet-5-5 | 2.00 | 10.00 | 2.50 | 0.20 |

"Prompt" here means input + cache write + cache read tokens for that call.

Assumes the 5-minute cache and normal (non-batch) requests. 1-hour cache writes (2× input)
and the Batch API discount (50% off) aren't modelled.

## Install

```
pip install -e ../agent-cost-tracker     # from a project folder in media-ai-agents (the sibling folder)
```

Settings are environment variables (see `.env.example`). The `report` command reads a
`.env` file itself; when you use `tracked_call` from your own app, your app loads its
`.env` (for example with `python-dotenv`), because the library only reads `os.environ`.

| Variable | Default | Meaning |
|---|---|---|
| `COST_DB_PATH` | `./costs.sqlite` | Ledger file. Point several projects at the same file to share one budget. |
| `COST_BUDGET_USD` | `15` | Hard stop for total spend in the ledger. |

## Tests

Windows:

```
python -m venv .venv
.venv\Scripts\pip install -e ".[dev]"
.venv\Scripts\python -m pytest
```

macOS / Linux:

```
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest
```

The tests use a fake client, so they never call the API and cost nothing.

## Not covered

My n8n flow (n8n-email-approval-flow) calls Claude from an HTTP node, not from Python,
so it doesn't go through this library. It works out its own cost and saves it in its own
`ai_usage` table in Postgres, outside this ledger and its budget.
