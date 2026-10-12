"""Command line.

  python -m inbox_agent seed                  send the synthetic dataset into Mailpit (SMTP 1027)
  python -m inbox_agent run                   read Mailpit, process new emails (Haiku + rules)
  python -m inbox_agent run --source dataset  same, straight from data/emails.yaml
  python -m inbox_agent serve                 approval page on http://localhost:8010
  python -m inbox_agent brief                 build the Arabic morning briefing and send it
                                              to the executive office address (in Mailpit)
  python -m inbox_agent kpi                   KPI report as JSON
  python -m inbox_agent eval [--gate]         score against data/gold.yaml (calls the API)
  python -m inbox_agent eval --replay FILE    re-score saved predictions (no API calls)
  python -m inbox_agent calibrate             similarity of same-thread vs other pairs (free)
  python -m inbox_agent rollback ACTION_ID --by PERSON
"""

import argparse
import json
import smtplib
import sys
from datetime import date, datetime

from . import config


def _context(with_embedder=True, source="mailpit"):
    from .actions import LocalBoard, Mailer
    from .directory import Directory
    from .inbox import DatasetInbox, GmailInbox, MailpitInbox, build_gmail_service
    from .pipeline import Context
    from .store import Store
    from .threads import E5Embedder, ThreadLinker

    store = Store()
    directory = Directory()
    ignore = [directory.company["office_inbox"], directory.company["agent_address"]]
    if source == "mailpit":
        inbox = MailpitInbox(office_inbox=directory.company["office_inbox"],
                             agent_address=directory.company["agent_address"])
    elif source == "gmail":
        inbox = GmailInbox(build_gmail_service())
    else:
        inbox = DatasetInbox()
    linker = ThreadLinker(store, E5Embedder() if with_embedder else None, ignore_addresses=ignore)
    return Context(store=store, directory=directory, linker=linker, mailer=Mailer(),
                   board=LocalBoard(store), inbox=inbox,
                   batch=datetime.now().strftime("%Y%m%dT%H%M%S"))


def _client():
    import anthropic
    return anthropic.Anthropic()


def cmd_seed(args):
    from .inbox import build_mime, load_dataset
    items = load_dataset()
    with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=15) as smtp:
        for item in items:
            msg = build_mime(item)
            smtp.send_message(msg, to_addrs=list(item.get("to") or []) + list(item.get("cc") or []))
    print(f"Sent {len(items)} synthetic emails to Mailpit ({config.SMTP_HOST}:{config.SMTP_PORT}).")


def cmd_run(args):
    from .pipeline import run
    ctx = _context(source=args.source)
    done = run(ctx.inbox, ctx, _client(), limit=args.limit)
    print(f"Processed {len(done)} new emails. Open the approval page: python -m inbox_agent serve")


def cmd_serve(args):
    import uvicorn
    from .web import create_app
    ctx = _context(with_embedder=False)
    uvicorn.run(create_app(ctx), host="127.0.0.1", port=args.port)


def cmd_brief(args):
    from .briefing import build_and_send
    ctx = _context(with_embedder=False)
    path = build_and_send(ctx, args.as_of or date.today().isoformat(), send=not args.no_send)
    print(f"Briefing saved to {path}" + ("" if args.no_send else
          f" and sent to {ctx.directory.company['executive_briefing_to']} (Mailpit)"))


def cmd_kpi(args):
    from . import kpi
    from .store import Store
    print(json.dumps(kpi.compute(Store()), indent=2, ensure_ascii=False))


def cmd_eval(args):
    from . import evaluate
    if args.replay:
        scores = evaluate.replay(args.replay)
    else:
        from .threads import E5Embedder
        only = args.only.split(",") if args.only else None
        result = evaluate.run_eval(_client(), E5Embedder(), only=only)
        scores = result["scores"]
        print(f"API calls: {result['api_calls']}  cost: ${result['cost_usd']:.4f}")
    shown = {k: v for k, v in scores.items() if not isinstance(v, (dict, list))}
    print(json.dumps(shown, indent=2, ensure_ascii=False))
    for key in ("wrong_owner_ids", "category_errors", "false_quarantine_ids"):
        if scores.get(key):
            print(key, json.dumps(scores[key], ensure_ascii=False))
    if args.gate:
        fails = evaluate.gate(scores)
        if fails:
            print("REGRESSION GATE FAILED:\n  " + "\n  ".join(fails))
            sys.exit(1)
        print("Regression gate passed.")


def cmd_calibrate(args):
    import numpy as np
    from .evaluate import load_gold
    from .inbox import DatasetInbox
    from .normalize import split_body
    from .threads import E5Embedder, embedding_text
    gold = load_gold()
    emails = [split_body(e) for e in DatasetInbox().fetch()]
    vecs = E5Embedder().encode([embedding_text(e) for e in emails])
    sims = vecs @ vecs.T
    same, other = [], []
    for i, a in enumerate(emails):
        for j in range(i):
            (same if gold[a.source_id]["thread"] == gold[emails[j].source_id]["thread"] else other).append(
                (float(sims[i, j]), emails[j].source_id, a.source_id))
    same.sort()
    other.sort(reverse=True)
    print("same-thread pairs, lowest similarity first:")
    for s in same[:8]:
        print(f"  {s[0]:.3f} {s[1]}-{s[2]}")
    print("different-thread pairs, highest similarity first:")
    for s in other[:8]:
        print(f"  {s[0]:.3f} {s[1]}-{s[2]}")
    print(f"same mean {np.mean([s[0] for s in same]):.3f} | other mean {np.mean([s[0] for s in other]):.3f}"
          f" | threshold {config.THREAD_SIMILARITY_THRESHOLD}")


def cmd_rollback(args):
    from .pipeline import rollback
    ctx = _context(with_embedder=False)
    print(rollback(ctx, args.action_id, args.by))


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")  # Arabic in a Windows console
    p = argparse.ArgumentParser(prog="inbox_agent")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("seed").set_defaults(fn=cmd_seed)
    r = sub.add_parser("run")
    r.add_argument("--source", choices=["mailpit", "dataset", "gmail"], default="mailpit")
    r.add_argument("--limit", type=int)
    r.set_defaults(fn=cmd_run)
    s = sub.add_parser("serve")
    s.add_argument("--port", type=int, default=8010)
    s.set_defaults(fn=cmd_serve)
    b = sub.add_parser("brief")
    b.add_argument("--as-of")
    b.add_argument("--no-send", action="store_true")
    b.set_defaults(fn=cmd_brief)
    sub.add_parser("kpi").set_defaults(fn=cmd_kpi)
    e = sub.add_parser("eval")
    e.add_argument("--only")
    e.add_argument("--gate", action="store_true")
    e.add_argument("--replay")
    e.set_defaults(fn=cmd_eval)
    sub.add_parser("calibrate").set_defaults(fn=cmd_calibrate)
    rb = sub.add_parser("rollback")
    rb.add_argument("action_id", type=int)
    rb.add_argument("--by", required=True)
    rb.set_defaults(fn=cmd_rollback)
    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
