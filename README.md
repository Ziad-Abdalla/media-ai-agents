# media-ai-agents

Seven Arabic-first AI agents and automations for a media and TV production company. They cover the office inbox, purchase requests into Odoo, equipment and studio bookings in n8n, a knowledge assistant that answers staff questions from company documents (Arabic RAG), an Arabic evaluation set for script breakdowns, and Whisper subtitles for Saudi and Gulf dialect. The same rules hold in every project: a person approves anything that writes to a real system or leaves the company, a retry or a double-click never does the same thing twice (idempotency), every action is audited and can be rolled back, permissions are checked in code before the model sees anything, email and document text is treated as data so prompt injection can't make the agent act, and every Claude call goes through one shared cost tracker with a hard budget.

<div dir="rtl">

**بالعربي باختصار:** سبعة مشاريع ذكاء اصطناعي تخدم شركة إنتاج إعلامي وتعمل بالعربي أولاً: وكيل لبريد مكتب الإدارة، وطلبات الشراء إلى Odoo، وحجز الاستوديوهات والمعدات عبر n8n، ومساعد يجيب الموظفين من مستندات الشركة فقط مع ذكر المصدر، وتفريغ السيناريو العربي مع مجموعة اختبار عربية، وترجمة مبدئية للهجة السعودية والخليجية بـ Whisper. لا يُكتب شيء في أي نظام ولا يخرج أي بريد إلا بعد موافقة شخص، وكل خطوة مسجلة ويمكن التراجع عنها، وتكلفة كل استدعاء للنموذج محسوبة ولها سقف. كل البيانات اصطناعية للتجربة.

</div>

## The projects

| Project | What it does | Key tech | Headline result | Unit tests |
|---|---|---|---|---|
| [agent-cost-tracker](agent-cost-tracker/) | Small library every Claude call goes through: cost per operation and per run, stored in SQLite, hard budget stop | Python, Anthropic SDK, SQLite | Odoo demo ledger: 6 Haiku calls, $0.00168 total, $0.00028 mean per run | 15 |
| [odoo-request-agent](odoo-request-agent/) | Reads approved purchase requests from email (Arabic, English, Saudi dialect) and prepares a draft Purchase Order in Odoo, charged to the right production and checked against its budget | Python, Claude Haiku 5.5, Odoo 17 XML-RPC, FastAPI, Docker | 100% of 270 fields right on the eval (99.6% on the first run); about $0.34 per 1,000 requests | 146 |
| [n8n-email-approval-flow](n8n-email-approval-flow/) | n8n workflow for studio, equipment, crew and location bookings by email, with a clash check and a manager approval email | n8n, Claude Haiku 5.5, Postgres, Odoo node, Docker | Live run: 7 of 8 requests auto-routed, 1 clash caught, $0.00064 AI cost per booking | 41 |
| [arabic-script-breakdown](arabic-script-breakdown/) | Breaks an Arabic TV screenplay down scene by scene, then drafts a shooting schedule, a call sheet and a budget summary; Arabic eval set and regression gate | Python, Claude Haiku / Sonnet 5.5, structured output | Overall score 0.995 on 26 scenes with Haiku at $0.016 per script, about 16 times cheaper than Sonnet (gold labels still pending native-speaker review) | 116 |
| [gulf-whisper-srt](gulf-whisper-srt/) | Local Arabic subtitles from audio or video: SRT, WebVTT, transcript, searchable dialogue index, QC report and review page | faster-whisper (large-v3-turbo), Python, no paid API | Pooled WER 13.3% on MSA, 42.1% on Saudi dialect TV clips (public data) | 93 |
| [executive-inbox-agent](executive-inbox-agent/) | Email agent for the CEO and GM office: threads, Arabic summaries, tasks with evidence, owner suggestions, approval page and morning briefing | Python, Claude Haiku 5.5, e5 embeddings, FastAPI, Mailpit | 88 of 88 attack attempts blocked; owner accuracy 96.6%; $0.00067 per email | 132 |
| [arabic-knowledge-assistant](arabic-knowledge-assistant/) | Answers staff questions in Arabic (formal or Saudi dialect) or English only from company documents, with a citation on every sentence and permissions applied before retrieval | Python, bge-m3 + BM25, Claude Haiku 5.5, FastAPI | 55-question eval: 0 leaks in 11 access-denied and injection questions, 17 of 17 correct refusals, hit@6 1.00 | 95 |

Test counts are the unit tests (no network, no API cost). Some projects also have a few `live` tests that are skipped by default. Each project README explains how its numbers were measured and what they don't show.

## Safety principles

These apply wherever an agent can act on a real system:

- **A person approves every write.** Nothing is written to Odoo, sent by email or assigned to someone until a named person presses Approve, and the page shows exactly what will happen.
- **Safe to retry.** Each action has an idempotency key, so a lost reply, a retry or two clicks at once never create a second PO, booking or email.
- **Audit and rollback.** Every action is logged with who approved it, and a run can be rolled back. A kill switch stops the agent's writes.
- **Permissions in code, failing closed.** What a user or the agent may do is checked in code, not left to the model. If a check crashes, the action is blocked and a person decides.
- **Prompt-injection defence.** Email and document text goes to the model as data. The model has no tools; it only fills fields, and code builds the plan from those fields, so an injected instruction has nothing to call.
- **Cost tracking.** Every Claude call goes through `agent-cost-tracker`, which records cost per operation and refuses calls once the budget is used up.
- **Measured before trusted.** The AI steps have eval sets and, where it matters, a regression gate that fails a release if the numbers drop.

## Quickstart

Clone once. Every project is a folder in this repo.

```powershell
git clone https://github.com/Ziad-Abdalla/media-ai-agents
cd media-ai-agents
```

Use Python 3.13 and one virtual environment per project. The projects that call Claude use the shared cost tracker in `agent-cost-tracker/`. Install it from that sibling folder **before** the project, because PyPI has an unrelated package with the same name:

```powershell
cd odoo-request-agent
py -3.13 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ..\agent-cost-tracker
pip install -e ".[dev]"
copy .env.example .env        # then add your ANTHROPIC_API_KEY
python -m pytest
```

Each project README has its full steps. The knowledge assistant and the inbox agent need PyTorch, and gulf-whisper-srt downloads the Whisper model on first run.

Three projects need Docker Desktop. The ports are chosen so they can all run at the same time:

| Project | Services and host ports |
|---|---|
| odoo-request-agent | Odoo 8069, Postgres 5433, Mailpit SMTP 1025 and inbox 8025 |
| n8n-email-approval-flow | n8n 5678, Postgres 5434, Mailpit SMTP 1026 and inbox 8026 |
| executive-inbox-agent | Mailpit SMTP 1027 and inbox 8027 |

## About the data

These are demos. All emails, people, vendors, productions, budgets, documents and the screenplay are synthetic, written for these projects. The Whisper examples use public licensed datasets (SADA and FLEURS). The numbers above show that the pipelines and the checks work on that data. They are not accuracy claims about any company's real documents or footage.

## License

MIT, see [LICENSE](LICENSE).
