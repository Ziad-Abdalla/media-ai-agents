# odoo-request-agent

A department emails an **already-approved** purchase request ("Please order 2 days of camera
crane rental from Riyadh Grip Co for the Thanawiyat shoot, 3,500 SAR/day, needed by Oct 20,
approval APR-2026-0412"). This agent reads the email, uses Claude Haiku to pull out the
fields, checks them in plain code, finds the vendor and products in Odoo over XML-RPC, and
prepares a **draft Purchase Order**. Nothing is written to Odoo until a person presses
Approve on a small web page that shows the original email, what was extracted, and the exact
values that will be sent. Every write is audited and can be rolled back, a retry can never
create a second PO, and a kill switch stops all writes. Every AI call goes through
[agent-cost-tracker](../agent-cost-tracker), which records cost per operation and enforces a
hard budget.

![Approval page showing a prompt-injection email](docs/approval-page.png)

## Flow

```mermaid
flowchart LR
    A[Inbox<br>Mailpit or Gmail<br>read-only] --> B{Internal<br>sender?}
    B -- no --> X[blocked_sender<br>no AI call]
    B -- yes --> C[Extract with Haiku<br>structured output<br>email = data]
    C --> D{Validate<br>in code}
    D -- missing/invalid --> E[needs_info<br>draft reply asking<br>for exactly what's missing]
    D -- ok --> F[Resolve in Odoo<br>vendor, products, currency<br>reads only]
    F --> G{Sure about<br>vendor? not a<br>re-send?}
    G -- no --> H[needs_human<br>pick a candidate]
    H --> I
    G -- yes --> I[pending_approval<br>exact write plan]
    I -- Approve --> J[Permission gate<br>kill switch check]
    J --> K[Create draft PO<br>idempotent + audited]
    K -.-> L[rollback run_id]
```

## Quickstart

```
docker compose up -d                       # Odoo 17 :8069, Postgres :5433, Mailpit :8025
python -m venv .venv
.venv\Scripts\pip install -e ..\agent-cost-tracker -e ".[dev]"
copy .env.example .env                     # add ANTHROPIC_API_KEY
python scripts\setup_odoo.py               # database, Purchase app, demo vendors/products
python scripts\send_samples.py             # six sample emails into Mailpit
python -m odoo_agent poll                  # read emails, prepare runs (no writes)
python -m odoo_agent serve                 # approval page on http://localhost:8000
```

Other commands: `python -m odoo_agent runs`, `audit <run_id>`, `rollback <run_id>`, `kill`, `unkill`.

To read a real Gmail label instead of Mailpit: in Google Cloud, enable the Gmail API, set up
the OAuth consent screen (add yourself as a test user), create an OAuth "Desktop app" client,
save it as `credentials.json`, put the request emails under a label (default
`purchase-requests`) and run `python -m odoo_agent poll --gmail`. The first run opens a browser
to log in and saves `token.json`. The only permission asked for is `gmail.readonly`. Both
files are git-ignored.

## Safety design

| Risk | What stops it | Test that proves it |
|---|---|---|
| **Wrong record** (PO goes to the wrong vendor) | Exact match first; fuzzy match only if clearly the best (≥ 0.90 and no close second); unsure → `needs_human` with candidates; unknown vendor is only *proposed*, created after approval | `test_resolve.py`, `test_pipeline.py::test_human_picks_vendor_when_unsure`, `::test_unknown_vendor_needs_approval_to_be_created` |
| **Duplicate on retry** (network drops after Odoo saved the PO) | Idempotency key = hash(message-id + normalized request), stored in the PO's `origin` and in the local `runs` table; before creating, search Odoo for the key and reuse the PO if found. Same email fetched twice is skipped before any AI call. A re-sent copy (new message-id) is flagged as a possible duplicate for a human | `test_pipeline.py::test_lost_answer_then_retry_makes_no_duplicate`, `::test_resent_request_is_flagged_as_duplicate`, live: `tests/live/test_live_odoo.py` |
| **Bad bulk update** | The agent can only create draft POs/vendors and edit *draft* POs, one plan at a time, after approval. Every write stores before/after values in `audit`; `rollback <run_id>` deletes the run's draft PO, restores edited fields, archives a vendor it created. Kill switch (`AGENT_WRITES_ENABLED=false` or `python -m odoo_agent kill`) blocks every write | `test_rollback.py`, `test_permissions.py::test_kill_switch_*`, live rollback test |
| **Prompt injection** | Email is wrapped as data and the system prompt says so, but the real defence is structural: the model has no tools and only fills data fields; the plan is built by code from those fields; forbidden actions don't exist for it to call. Suspicious text is flagged on the approval page | `test_injection.py` (a "fooled" model output still produces the same one-step plan, no confirm/delete/email) |
| **Data leaving the company** | `send_email` is the only way to send mail: internal domain only, never attachments, needs approval. Sender must be on `ALLOWED_SENDER_DOMAINS` (outside senders are dropped before the AI sees them). Gmail scope is read-only | `test_permissions.py::test_email_outside_the_company_is_refused`, `::test_attachments_are_never_sent`, `test_pipeline.py::test_outside_sender_is_ignored_without_spending_money` |
| **Runaway cost** | Every model call goes through `tracked_call` (cost per operation and per run, hard budget `COST_BUDGET_USD` checked *before* each call); cheap model (Haiku 5.5) at low effort; one call per email; already-seen emails and outside senders never reach the model | `test_extract.py::test_every_call_is_recorded_in_the_cost_ledger`, agent-cost-tracker tests |

Permissions live in one table, `ALLOWED_ACTIONS` in `odoo_agent/permissions.py`, enforced by
one function, `execute()`:

| auto | needs approval | forbidden (refused and logged) |
|---|---|---|
| search/read Odoo, draft a reply | create/update PO, create vendor, send email | confirm or cancel a PO, delete anything, any action not in the table; inside `send_email`: outside domains, attachments |

Honest limits: reads aren't wrapped by the gate because they can't change anything (a stricter
setup gives the agent a read-only Odoo user plus a separate write user). The approver name is
typed in, so a real deployment would put the page behind company login. The demo uses the
Odoo admin account; in production the agent gets its own user with Purchase rights and an API key.

## Live demo (2026-10-12, real Haiku 5.5, six sample emails)

| Email | Result |
|---|---|
| Crane rental, Riyadh Grip Co | `pending_approval` → approved → draft PO P00008, 2 × 3,500 SAR |
| Lights for studio B (no qty/price/date/approval) | `needs_info`, reply drafted asking for exactly those 5 things; sent to the internal sender after a click |
| Same crane request re-sent | `needs_human`: "Looks like a re-send of run-95de3b6a" → rejected |
| Sound quote with an injected "SYSTEM NOTE" (confirm PO, delete vendors, email bank details out) | Same one-step plan as a normal email; model also noted the injection; page warned; approved → draft PO only, nothing confirmed, deleted or sent |
| Catering from an unknown vendor | Plan: create vendor + PO (needs approval) → approved → then `rollback` deleted the draft PO and archived the vendor |
| Arabic request (Arabic-Indic numerals) | Extracted 4 × 800 SAR, Desert Lights Rental, 2026-10-22; model noted the rental days weren't stated → approved → draft PO P00011 |

Cost from the ledger (`python -m agent_cost_tracker report`, operation `extract_purchase_request`):

```
extract_purchase_request    calls=6   $0.00168
cost per run: mean $0.00028, max $0.00032   (≈1,500-1,700 input + 200-310 output tokens each)
```

That's about **$0.28 per 1,000 requests** for the AI part.

## Code map

| File | What it does |
|---|---|
| `odoo_agent/inbox.py` | `MailpitInbox`, `GmailInbox` (read-only), both return `Email` objects |
| `odoo_agent/extract.py` | One Haiku call with a JSON schema → `PurchaseRequest` |
| `odoo_agent/validate.py` | Plain-code checks; sender allow-list; drafts the "please send X" reply |
| `odoo_agent/resolve.py` | Vendor/product/currency lookup, exact → fuzzy → human |
| `odoo_agent/plan.py` | Builds the exact write plan; fingerprint and idempotency key |
| `odoo_agent/permissions.py` | `ALLOWED_ACTIONS` + the `execute()` gate + kill switch check |
| `odoo_agent/actions.py` | The actions: create vendor/PO (idempotent), update draft PO, send email |
| `odoo_agent/pipeline.py` | `process_email`, `approve_run`, `choose_vendor`, `reject_run` |
| `odoo_agent/rollback.py` | Undo one run using the audit log and the key in `origin` |
| `odoo_agent/store.py` | SQLite `runs` and `audit` tables |
| `odoo_agent/web.py`, `templates/index.html` | The approval page (FastAPI + one Jinja template) |
| `odoo_agent/odoo_client.py` | Small XML-RPC wrapper |

## Tests

```
python -m pytest            # 56 unit tests: fake model + fake Odoo, no network, no cost
python -m pytest -m live    # 2 tests against the docker Odoo (canned extraction, no AI cost)
```
