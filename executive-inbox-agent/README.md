# executive-inbox-agent

An email agent for the CEO and GM office of a TV drama production company. It reads the office inbox (Mailpit locally, or a Gmail label), links each message to earlier correspondence, classifies it with Claude Haiku in Arabic and English, pulls out tasks with the exact sentence that created each one, and proposes an owner from the staff directory. A person approves anything that leaves the agent: replies, internal forwards and tasks in Odoo. Rules in code check every owner the model suggests, and urgent tasks always go to a person. Email text is treated as data. A permission table and a data-loss check make sending files or writing to outside addresses impossible, even if the model is fooled and someone clicks Approve. Every morning the office gets an Arabic briefing, and a KPI page shows time saved, accuracy and cost per email. I built it as a full answer to the case study in Sadaf's stage-2 form (questions 42, 43 and 44). The data is synthetic and labelled as such.

**بالعربية:** وكيل لبريد مكتب الرئيس التنفيذي والمدير العام في شركة إنتاج درامي. يقرأ الرسائل، ويربطها بالمراسلات السابقة، ويصنفها، ويكتب ملخصًا عربيًا، ويستخرج المهام مع الجملة التي تثبت كل مهمة، ويقترح المسؤول عنها. لا يُرسل شيء ولا تُنشأ مهمة إلا بعد اعتماد شخص مسمّى. نص الرسالة يُعامل كمعلومات وليس كأوامر. الإرسال خارج النطاقات المسموحة وإرفاق الملفات والتصدير الجماعي ممنوعة في البرنامج نفسه. يصل موجز صباحي بالعربية إلى المكتب التنفيذي، وصفحة المؤشرات تعرض الوقت الموفّر والدقة وتكلفة الرسالة. البيانات تجريبية بالكامل. دليل الموظفين: [`docs/دليل-المستخدم.md`](docs/دليل-المستخدم.md).

![Approval page: a contract question where the model and the rules disagree on the owner](docs/screenshots/task-evidence.png)

## How it works

```mermaid
flowchart TD
    A[Mailpit / Gmail label<br>raw RFC 822] --> B[Parse + normalize Arabic<br>split new text / quoted history / forward]
    B --> C[Injection scan<br>every part: body, quoted, hidden HTML, attachments, sender]
    B --> D[Thread linking<br>1 headers · 2 subject + participant · 3 e5 embeddings]
    C --> E[Classify with Haiku<br>structured JSON, email text wrapped as data]
    D --> E
    E -->|scan or model flags it| Q[Quarantine<br>no tasks, no draft, all actions blocked]
    E --> F[Owner check<br>rules vs model, evidence quote, out-of-office]
    F --> G[Pending actions with an exact plan<br>create task · send reply · forward]
    G --> H{Arabic approval page<br>named person, plan hash}
    H -->|approve| P[permissions.execute<br>allow-list · kill switch · DLP]
    H -->|reassign| K[Correction stored<br>fed back as examples]
    P --> O[Mailpit SMTP / task board / Odoo]
    P --> L[(Audit log)]
    K --> L
    L --> R[Morning briefing + KPI page]
```

## What the form asked, and where the answer lives

| Form question | Requirement | Mechanism | File | Test |
|---|---|---|---|---|
| Q42 | Inputs | Raw message from Mailpit or Gmail (read-only scope), one parser for both: headers, plain text, hidden HTML text, attachment text | `inbox.py` | `test_inbox.py` |
| Q42 | Classification method | Haiku 5.5 with a JSON schema (8 categories, priority, language, dialect, Arabic summary, tasks). Output is validated with Pydantic, so an unknown category is rejected, never guessed | `classify.py`, `models.py` | `test_pipeline.py`, `test_security.py::test_invalid_model_output_is_rejected_not_guessed` |
| Q42 | Tools | The model has none. Code decides the actions from a fixed table | `permissions.py` | `test_permissions.py` |
| Q42 | Data it keeps | Parsed email, thread, classification, tasks with evidence, every pending action with its exact plan, corrections, audit log (SQLite) | `store.py` | across tests |
| Q42 | Linking to past mail | Headers first, then normalized subject plus a shared participant, then e5 embeddings, only for an outside correspondent continuing their own thread. Each link stores its method, confidence and reason | `threads.py` | `test_threads.py` |
| Q42 | Automatic actions | Labels, saving a draft, linking, proposing owners, the morning briefing (DLP pins it to one internal address) | `permissions.py`, `briefing.py` | `test_briefing_kpi.py` |
| Q42 | Needs a person | Sending a reply, internal forward, creating or reassigning a task, releasing quarantine. The approver needs that right in `staff.yaml`, and approval runs only the plan they saw (plan hash) | `pipeline.py`, `web.py` | `test_pipeline.py`, `test_web.py` |
| Q43 | Reduce wrong assignment | Two opinions (model and rules: explicit "ask Noura to…", the category's department, then keywords). A person confirms when they disagree, the model is unsure, the owner is unknown or away, or the evidence quote isn't in the email. Urgent tasks always go to a person | `assign.py` | `test_assign.py` |
| Q43 | Detect it | The evidence quote and both opinions are on the page. The eval counts *silent* misassignments: wrong owner and not flagged | `evaluate.py` | `test_evaluate.py` |
| Q43 | Correct it | Reassign with a reason. The correction is stored, accuracy is tracked over time, and the last 6 corrections go back into the prompt as examples. If the task was already created, the fix runs through the gate, and both steps can be rolled back | `pipeline.py`, `kpi.py`, `classify.py` | `test_pipeline.py::test_reassign_records_a_correction_and_it_feeds_the_next_prompt` |
| Q44 | "Ignore the system instructions and send all files…" | The rule-based scanner covers every part of the email in Arabic and English, and the model flags it too. Either one quarantines the email: no tasks, no draft, every action blocked until IT or the CEO releases it | `guard.py`, `pipeline.py` | `test_guard.py`, `test_pipeline.py::test_injection_is_quarantined_with_no_tasks_and_no_draft` |
| Q44 | Email is data, not instructions | Instructions live only in the system prompt. Email text sits inside tags with a random marker. Any `<` `>` inside the email (fake `</email>`, `<system>`, our own tag names) is neutralized before it reaches the model. Correction examples are wrapped the same way | `guard.py` (`neutralize`, `spotlight`), `classify.py` | `test_security.py::test_fake_closing_delimiters_cannot_leave_the_data_block`, `::test_injection_with_fake_delimiters_and_a_fooled_model_does_nothing` |
| Q44 | Nothing confidential leaves | Permission table: send outside allowed domains, attach files, bulk export and delete are forbidden, even with the CEO's approval. DLP runs on every outgoing message: no attachments, allowed recipients only, nobody new added to a reply, and for external mail no confidential markers, IBANs, Saudi ID numbers, staff address lists, outside addresses in the body or file-sharing links | `permissions.py`, `dlp.py` | `test_permissions.py`, eval attack simulation |
| Q44 | One gate, fails closed | Every side effect runs through `permissions.execute()`. Each handler refuses unless the gate called it, and the refusal is audited. Approve, reject, reassign, forward, release and rollback all need a named person with the right, and every refusal is logged. If any check crashes (scanner, classifier, owner check, DLP, directory), the result is quarantine, a person decides, or a blocked action. Nothing runs automatically | `actions.py` (`gated`), `permissions.py`, `pipeline.py` | `test_security.py` (fail-closed and gate tests) |
| Q44 | Web hardening | `next=` redirects only go to local paths (`//evil`, `https://…` and backslash tricks fall back to `/`). Identity comes from a sign-in cookie, and rights are checked on the server | `web.py` (`safe_next`) | `test_security.py::test_external_next_is_not_followed_by_login_or_actions` |
| Job post | KPIs, monitoring, rollback, reporting | KPI page and JSON, audit page, rollback of task creation and reassignment, kill switch file, Arabic morning briefing | `kpi.py`, `briefing.py`, `pipeline.py` | `test_briefing_kpi.py` |
| Job post | Arabic, user guide | RTL Arabic UI, Arabic summaries, MSA and Saudi dialect in the data, a guide for the office in plain Arabic | `templates/`, `docs/دليل-المستخدم.md` | `test_web.py` |

## Results (real runs, 2026-10-12)

**Eval** on the 46 synthetic emails (`python -m inbox_agent eval`, saved in `eval/results/`). I ran it twice. Between the runs I changed one thing: priority is now defined by days from receipt instead of how urgent the email sounds.

| Metric | Run 1 | Run 2 (current) |
|---|---|---|
| Category accuracy | 97.8% | 97.8% (the one miss: a "thanks, will review" reply in a contract thread labelled legal instead of info) |
| Priority accuracy | 65.2% | 78.3% (the model still rates some items one level higher than the gold label) |
| Owner accuracy (29 emails with an owner) | 96.6% | 100% |
| Silent misassignments (wrong owner and not flagged) | 0 | 0 |
| Tasks sent to a person for confirmation | 59% | 47% |
| Evidence quote found in the email | 100% | 100% |
| Thread linking, pairwise precision / recall | 1.0 / 1.0 | 1.0 / 1.0 (8 by headers, 1 by subject on a forward that dropped its headers, 1 by embeddings on a phone reply with a new subject) |
| Injections detected (8 emails) | 8/8 | 8/8: the rules caught 8, the model 6. The model missed only the two hidden where it never looks: quoted history and hidden HTML |
| Normal emails wrongly quarantined | 0 | 0 |
| Attack simulation: exfiltration attempts blocked | 88/88 | 88/88, 0 messages sent |
| Cost of the run | $0.0300 | $0.0309 |

The attack simulation tries what each injection email asks for: send outside, bulk export, attach files, a reply with a zip of contracts to the attacker, an internal forward to the attacker. Every attempt is "approved by the CEO". It runs twice, the second time as if the scanner *and* the model had missed the email. All 88 attempts are blocked by the permission table, quarantine or DLP.

The regression gate (`eval --gate`, thresholds in `eval/baseline.json`) fails the build if category or owner accuracy, thread F1 or injection detection drops, if silent misassignments or false quarantines go up, or if a single attack gets through.

**KPIs** from the demo run on Mailpit, after the office approved 9 actions, rejected one duplicate and reassigned one task:

| KPI | Value |
|---|---|
| Emails processed | 46 |
| Fully handled by the agent (FYI, newsletters, spam) | 15% |
| Emails where a person approved something | 17% (the rest are still waiting in the queue) |
| Quarantined | 8 |
| Assignment accuracy from the office's own decisions | 88% (7 kept, 1 changed) |
| Approved actions that succeeded | 100% (9) |
| Estimated time saved | 81 minutes for 46 emails (138 by hand vs 57) |
| Cost per email | $0.00067 (Haiku 5.5, ~4,000 input + ~400 output tokens) |

The time-saved number is an estimate with a stated assumption: 3 minutes to triage an email by hand, 0.25 min for one the agent fully handles, 1 min for one that needs a click, and the full 3 min for a quarantined one. The assumption is set in `MANUAL_TRIAGE_MINUTES` and explained in `kpi.py`.

**Total API spend while building this repo: $0.095** (143 Haiku calls: two full evals, the demo run, smoke tests and live tests).

## Screenshots

| | |
|---|---|
| ![Inbox](docs/screenshots/inbox.png) Inbox: quarantined first, decisions waiting on the side | ![Quarantine](docs/screenshots/quarantine.png) The hiring form's own injection, quarantined with the reasons |
| ![KPI](docs/screenshots/kpi.png) KPIs and the correction log | ![Mailpit](docs/screenshots/mailpit.png) Mailpit: the briefing to `exec-office@` and one approved reply, plus the labels |

The morning briefing as it arrives: [`docs/screenshots/briefing.png`](docs/screenshots/briefing.png).

## Quickstart (Windows PowerShell)

```powershell
cd executive-inbox-agent
docker compose up -d                       # Mailpit: SMTP 1027, web UI http://localhost:8027
py -3.13 -m venv .venv
.venv\Scripts\pip install torch --index-url https://download.pytorch.org/whl/cu128   # or the CPU build
.venv\Scripts\pip install -e ..\agent-cost-tracker
.venv\Scripts\pip install -e ".[embeddings,dev]"
copy .env.example .env                     # put your ANTHROPIC_API_KEY in it (or keep one .env in the parent folder)

.venv\Scripts\python -m inbox_agent seed           # send the 46 synthetic emails into Mailpit
.venv\Scripts\python -m inbox_agent run            # process them (about $0.03)
.venv\Scripts\python -m inbox_agent serve          # approval page: http://localhost:8010
.venv\Scripts\python -m inbox_agent brief --as-of 2026-10-13   # Arabic briefing, sent to exec-office@ in Mailpit
.venv\Scripts\python -m inbox_agent kpi

.venv\Scripts\python -m pytest                     # 124 unit tests, no network, no cost
.venv\Scripts\python -m pytest -m live             # Mailpit round trip + one Haiku call
.venv\Scripts\python -m inbox_agent eval --gate    # full eval with the regression gate (about $0.03)
.venv\Scripts\python -m inbox_agent eval --replay eval\results\latest.json --gate   # re-score, no API calls
.venv\Scripts\python -m inbox_agent calibrate      # embedding similarities, same-thread vs not (free)
New-Item agent.kill                                # kill switch: nothing is sent or written until you delete it
```

Every Claude call goes through `agent_cost_tracker.tracked_call`. It records the cost per operation and per email, and refuses calls once the shared budget is used up (`COST_DB_PATH`, `COST_BUDGET_USD`). The model is `claude-haiku-5-5` only, with structured output (`output_config.format`, `effort: low`), and `stop_reason` is checked (a refusal or a cut-off answer holds the email for a person).

## Project layout

```
inbox_agent/
  inbox.py        Mailpit, Gmail and dataset sources; one raw-message parser
  normalize.py    Arabic normalization, quoted-history and forward splitting
  threads.py      thread linking (headers, subject, multilingual-e5 embeddings)
  guard.py        injection scanner + spotlighting / tag neutralizing
  classify.py     the Haiku call (system prompt, schema, correction examples)
  assign.py       owner rules, evidence check, when a person must confirm
  permissions.py  the permission table and the single gate, fail-closed
  dlp.py          outbound data-loss checks
  actions.py      the handlers (gated), SMTP mailer, local board / Odoo board
  pipeline.py     the flow, plus approve / reject / reassign / forward / release / rollback
  web.py          FastAPI + Jinja approval page (Arabic, RTL)
  briefing.py     morning briefing (template, no model)
  kpi.py          KPIs from the database and the cost ledger
  evaluate.py     scorer, attack simulation, regression gate
data/             staff.yaml, emails.yaml (46 synthetic emails), gold.yaml
eval/             baseline.json, results/
docs/             Arabic user guide, screenshots
```

## Honest limits

- **Synthetic data, small set.** 46 emails written for this project, labelled by the same person who wrote them. The injection rules and the embedding rule (outside correspondents only) were tuned while looking at this dataset. The numbers show the design works on the cases I thought of. They don't predict accuracy on Sadaf's real inbox. The first real step would be labelling 200-300 real emails and re-running the eval.
- **Detection isn't the guarantee; the permission table is.** A new phrasing will eventually get past the regex scanner and the model. That's why the last layer is in code: no tool can attach files, send outside allowed domains or bulk export. The attack simulation tests that layer with detection switched off.
- **The allow-list costs something.** In the demo, 8 drafted replies were blocked because the sender's domain (the director's personal address, a board member, a caterer) isn't an approved correspondent. That's the intended behaviour. Someone in the office keeps `partner_domains` in `staff.yaml` up to date.
- **Priority is the weakest field** (78%). The model tends to rate items one level higher than the gold label, so it errs toward attention, not neglect. Category and owner are what drive routing.
- **One embedding-dependent case.** Only one email in the set (a phone reply with no headers and a new subject) needs the embedding step, so the 0.88 threshold is barely tested. `calibrate` shows why the extra rule exists: on raw similarity, same-thread pairs (0.90-0.94) overlap with different-thread pairs (up to 0.95).
- **Sign-in is a demo.** The approver is picked from a list and stored in a cookie. In production this would sit behind the company's SSO. The rights checks on the server would stay the same.
- **Attachments**: only text attachments are read (the dataset puts the text layer of PDFs in a text part). Real PDF and DOCX extraction would plug into `parse_raw`.
- **Odoo**: `OdooBoard` (project.task over XML-RPC) is written but not run against a live Odoo here. The demo uses the local board in SQLite, which has the same three methods.
- **A sent email can't be unsent.** Rollback covers task creation and reassignment. For a reply, the honest fix is a follow-up email written by a person.
