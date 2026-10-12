"""The whole flow for one email, and the human decisions that come after.

process_email():
  1 parse + split new text / quoted history        (inbox.py, normalize.py)
  2 injection scan over every part of the email     (guard.py)
  3 link to an earlier conversation                 (threads.py)
  4 classify with Haiku (structured output)         (classify.py)
  5 quarantine if the scan OR the model flags it    -> no tasks, no draft, no actions
  6 tasks: propose an owner, decide if a person must confirm   (assign.py)
  7 pending actions with an exact plan: create task, send reply (DLP-checked)
  8 labels applied automatically; everything audited

Human side: approve_action(), reject_action(), reassign_task(), propose_forward(), rollback().
"""

from dataclasses import dataclass
from typing import Any

import anthropic
import numpy as np
from agent_cost_tracker import BudgetExceeded

from . import assign as assign_mod
from .actions import ForbiddenAction
from .classify import classify, correction_examples
from .dlp import check_outbound
from .guard import GuardResult, Signal, scan
from .models import Email
from .normalize import split_body, text_for_classification
from .permissions import (ApprovalRequired, DLPBlocked, NotAuthorized, WritesDisabled,
                          execute)
from .store import email_key, now, plan_hash
from .threads import Link


@dataclass
class Context:
    store: Any
    directory: Any
    linker: Any
    mailer: Any
    board: Any
    inbox: Any = None
    batch: str = "run"   # tags the cost ledger rows of one processing run


ACTION_ERRORS = (ApprovalRequired, NotAuthorized, WritesDisabled, DLPBlocked, ForbiddenAction)
# Errors where the right move is to stop and try the whole email again later (nothing was stored).
RETRY_LATER = (BudgetExceeded, anthropic.APIConnectionError, anthropic.RateLimitError,
               anthropic.InternalServerError)


def _thread_context(ctx, thread_id: str, limit: int = 3) -> list[str]:
    rows = ctx.store.emails("thread_id = ? AND summary_ar IS NOT NULL", (thread_id,))
    return [f"{r['date'][:10]} {r['from_addr']}: {r['summary_ar']}" for r in rows[-limit:]]


def process_email(email: Email, ctx: Context, client) -> str | None:
    """Returns the email id, or None if this message was already processed (idempotent)."""
    if ctx.store.email_by_message_id(email.message_id):
        return None
    email_id = email_key(email.message_id)
    run_id = f"inbox-{ctx.batch}-{email_id}"
    split_body(email)

    # Every check below fails CLOSED: if it crashes, the email is held for a person.
    try:
        guard = scan(email, ctx.directory)
        guard_error = None
    except Exception as e:
        guard, guard_error = GuardResult([Signal("guard_error", "system", f"{type(e).__name__}: {e}")]), e
    try:
        vector = ctx.linker.embed(email)
        link = ctx.linker.link(email, vector)
    except Exception as e:  # linking is not a safety check: fall back to a new thread
        vector = None
        link = Link("T-" + email_id[2:10], "new", 0.0, f"linking failed ({type(e).__name__}); new thread")
    ctx.linker.record(email, link)

    base = dict(
        id=email_id, message_id=email.message_id, source_id=email.source_id, thread_id=link.thread_id,
        from_addr=email.from_addr, from_name=email.from_name, to_json=email.to, cc_json=email.cc,
        subject=email.subject, date=email.date, new_text=email.new_text, quoted_text=email.quoted_text,
        forwarded_json=email.forwarded,
        attachments_json=[{"filename": a.filename, "content_type": a.content_type, "size": a.size,
                           "text": a.text[:3000]} for a in email.attachments],
        in_reply_to=email.in_reply_to, references_json=email.references,
        embedding=vector.astype(np.float32).tobytes() if vector is not None else None,
        link_json=link.as_dict(), guard_json=guard.as_dict(), run_id=run_id, labels_json=[])

    try:
        result, _ = classify(client, email, ctx.directory, run_id=run_id,
                             thread_context=_thread_context(ctx, link.thread_id),
                             corrections=correction_examples(ctx.store))
    except RETRY_LATER:
        raise  # nothing stored, nothing done: the next run tries this email again
    except Exception as e:  # refusal, cut-off answer, invalid JSON, unknown category...
        status = "quarantined" if guard.flagged else "error"
        ctx.store.add_email(**base, status=status, error=f"{type(e).__name__}: {e}",
                            category="suspicious" if guard.flagged else None)
        ctx.store.audit("agent", "classify", email_id=email_id, outcome="failed",
                        detail={"error": f"{type(e).__name__}: {e}", "held_for": "a person"})
        return email_id

    quarantined = guard.flagged or result.suspicious_instructions or result.category == "suspicious"
    category = "suspicious" if quarantined else result.category
    ctx.store.add_email(**base, classification_json=result.model_dump(), category=category,
                        priority="high" if quarantined else result.priority,
                        language=result.language, summary_ar=result.summary_ar,
                        status="quarantined" if quarantined else "triaged")
    ctx.store.audit("agent", "classify", email_id=email_id,
                    detail={"category": category, "model_category": result.category,
                            "link": link.as_dict(), "guard": guard.as_dict()})

    labels = [category, f"priority:{result.priority}"]
    if quarantined:
        labels.append("quarantined")
        ctx.store.audit("agent", "quarantine", email_id=email_id, outcome="blocked",
                        detail={"guard_signals": guard.as_dict()["signals"],
                                "guard_error": str(guard_error) if guard_error else None,
                                "model_flag": result.suspicious_instructions,
                                "model_reason": result.suspicious_reason})
    _quietly(ctx, "apply_label", {"email_id": email_id, "labels": labels})
    if quarantined:
        return email_id  # nothing else happens until IT security looks at it

    full_text = f"{email.subject}\n{text_for_classification(email)}"
    for task in result.tasks:
        try:
            d = assign_mod.decide(ctx.directory, task=task, category=category, priority=result.priority,
                                  subject=email.subject, email_text=full_text, received=email.date)
            found = assign_mod.evidence_in_email(task.evidence_quote, full_text)
        except Exception as e:  # the owner check crashed: no owner is proposed, a person decides
            d = assign_mod.Decision(None, None, f"check failed: {type(e).__name__}", None, True,
                                    [f"owner check failed ({type(e).__name__}); a person must choose"])
            found = False
        task_id = ctx.store.add_task(
            email_id=email_id, what_ar=task.what_ar, deadline=task.deadline, urgent=int(task.urgent),
            evidence_quote=task.evidence_quote, evidence_found=int(found),
            model_owner=task.suggested_owner_id, model_reason=task.owner_reason,
            model_confidence=task.owner_confidence, rule_owner=d.rule_owner, rule_reason=d.rule_reason,
            proposed_owner=d.proposed_owner, owner_note=d.owner_note,
            needs_confirmation=int(d.needs_confirmation), confirm_reasons_json=d.reasons,
            status="needs_confirmation" if d.needs_confirmation else "proposed")
        if d.proposed_owner and ctx.directory.get(d.proposed_owner):
            _add_create_task_action(ctx, email_id, task_id)

    if result.needs_reply and result.reply_draft:
        is_reply = email.subject.lower().startswith(("re:", "\u0631\u062f:"))
        plan = {"email_id": email_id, "to": [email.from_addr],
                "subject": email.subject if is_reply else f"Re: {email.subject}",
                "in_reply_to": email.message_id, "references": email.references,
                "conversation": sorted({email.from_addr, *email.to, *email.cc}),
                "body": result.reply_draft}
        _quietly(ctx, "draft_reply", plan)
        try:
            dlp = check_outbound("send_reply", to=plan["to"], body=plan["body"], directory=ctx.directory,
                                 conversation=plan["conversation"]).as_dict()
        except Exception as e:  # DLP crashed: the draft is blocked, never offered for sending
            dlp = {"blocked": True, "reasons": [f"DLP check failed ({type(e).__name__}); blocked"]}
        ctx.store.add_action(email_id=email_id, kind="send_reply", plan_json=plan,
                             status="blocked" if dlp["blocked"] else "pending", dlp_json=dlp)
    return email_id


def _quietly(ctx, action, plan):
    """Automatic, internal-only actions (label, save draft). They still go through the gate;
    if one fails it is audited and the email carries on (nothing leaves the agent)."""
    try:
        execute(action, plan, ctx=ctx)
    except Exception as e:
        ctx.store.audit("agent", action, email_id=plan.get("email_id"), outcome="failed",
                        detail={"error": f"{type(e).__name__}: {e}"})

def _task_plan(ctx, task: dict) -> dict:
    email = ctx.store.get_email(task["email_id"])
    owner = ctx.directory.get(task["final_owner"] or task["proposed_owner"])
    return {"email_id": task["email_id"], "task_id": task["id"], "owner": owner.id,
            "owner_name": owner.name_en, "name": task["what_ar"], "deadline": task["deadline"],
            "description": f"From: {email['from_addr']} | Subject: {email['subject']}\n"
                           f"Evidence: \"{task['evidence_quote']}\""}


def _add_create_task_action(ctx, email_id, task_id) -> int:
    task = ctx.store.get_task(task_id)
    return ctx.store.add_action(email_id=email_id, task_id=task_id, kind="create_task",
                                plan_json=_task_plan(ctx, task), status="pending")


def run(inbox, ctx: Context, client, limit: int | None = None) -> list[str]:
    done = []
    for email in inbox.fetch()[:limit]:
        email_id = process_email(email, ctx, client)
        if email_id:
            done.append(email_id)
    return done


# ---------------------------------------------------------------- human decisions
# Every function below needs a named person who holds the right for it (staff.yaml,
# can_approve). A refusal is written to the audit log before it is raised. Anything that
# changes the outside world (email, task board) runs only through permissions.execute().

def _require(ctx, who: str | None, right: str, what: str, **ids) -> None:
    if not who or not ctx.directory.get(who) or not ctx.directory.can_approve(who, right):
        ctx.store.audit(f"human:{who or 'anonymous'}", f"blocked:{what}", outcome="blocked",
                        detail={"why": f"needs the '{right}' right"}, **ids)
        raise NotAuthorized(f"{who or 'nobody'} may not {what}")


def _right_for(kind: str) -> str:
    return "create_task" if kind in ("reassign_task", "rollback_action") else kind


def approve_action(ctx, action_id: int, approver: str, shown_hash: str):
    """Run the exact plan the approver saw. Refused if the plan changed, if this person may
    not approve this kind of action, if DLP blocks it, or if it was already handled."""
    action = ctx.store.get_action(action_id)
    if not action:
        raise ValueError("no such action")
    _require(ctx, approver, _right_for(action["kind"]), f"approve:{action['kind']}",
             action_id=action_id, email_id=action["email_id"])
    if not shown_hash or not ctx.store.claim_action(action_id, approver, shown_hash):
        ctx.store.audit(f"human:{approver}", f"blocked:approve:{action['kind']}", outcome="blocked",
                        action_id=action_id, email_id=action["email_id"],
                        detail={"why": "plan hash missing or does not match the stored plan"})
        raise ValueError("plan changed after you opened the page, or it was already handled; reload")
    plan = {**action["plan_json"], "action_id": action_id}
    try:
        result = execute(action["kind"], plan, ctx=ctx, approved_by=approver)
    except ACTION_ERRORS as e:
        ctx.store.update_action(action_id, status="blocked", result_json={"error": str(e)})
        raise
    except Exception as e:  # network etc.: the action can be retried
        ctx.store.update_action(action_id, status="pending", result_json={"error": str(e)})
        raise
    ctx.store.update_action(action_id, status="executed", result_json=result)
    if action["kind"] == "create_task":
        task = ctx.store.get_task(action["task_id"])
        changed = task["status"] == "reassigned"
        ctx.store.update_task(task["id"], status="reassigned" if changed else "confirmed",
                              final_owner=plan["owner"], decided_by=approver, decided_at=now())
    return result


def reject_action(ctx, action_id: int, approver: str) -> None:
    action = ctx.store.get_action(action_id)
    if not action or action["status"] != "pending":
        raise ValueError("only a pending action can be rejected")
    _require(ctx, approver, _right_for(action["kind"]), f"reject:{action['kind']}",
             action_id=action_id, email_id=action["email_id"])
    ctx.store.update_action(action_id, status="rejected", approved_by=approver)
    if action["kind"] == "create_task":
        ctx.store.update_task(action["task_id"], status="rejected", decided_by=approver, decided_at=now())
    ctx.store.audit(f"human:{approver}", f"reject:{action['kind']}", action_id=action_id,
                    email_id=action["email_id"])


def reassign_task(ctx, task_id: int, new_owner: str, reason: str, by: str, shown_hash: str | None = None):
    """A person says the proposed owner is wrong. Records the correction (it becomes a
    few-shot example next run). Before the task exists on the board: changes the pending
    plan, which the person then approves (new hash). After: a reassign_task action fixes it
    on the board through the permission gate."""
    task = ctx.store.get_task(task_id)
    if not task or not ctx.directory.get(new_owner):
        raise ValueError("unknown task or person")
    _require(ctx, by, "create_task", "reassign_task", task_id=task_id, email_id=task["email_id"])
    old = task["final_owner"] or task["proposed_owner"]
    if new_owner == old:
        raise ValueError("that is already the owner")
    email = ctx.store.get_email(task["email_id"])
    pending = ctx.store.actions("task_id = ? AND kind = 'create_task' AND status = 'pending'", (task_id,))
    if pending and (not shown_hash or plan_hash(pending[0]["plan_json"]) != shown_hash):
        ctx.store.audit(f"human:{by}", "blocked:reassign_task", outcome="blocked", task_id=task_id,
                        email_id=task["email_id"], detail={"why": "plan hash missing or stale"})
        raise ValueError("plan changed after you opened the page; reload")

    ctx.store.add_correction(task_id=task_id, email_id=task["email_id"], task_text=task["what_ar"],
                             subject=email["subject"], evidence_quote=task["evidence_quote"],
                             from_owner=old, to_owner=new_owner, reason=reason, corrected_by=by)
    ctx.store.audit(f"human:{by}", "correct_owner", email_id=task["email_id"], task_id=task_id,
                    detail={"from": old, "to": new_owner, "reason": reason})
    ctx.store.update_task(task_id, final_owner=new_owner, status="reassigned", decided_by=by,
                          decided_at=now())
    task = ctx.store.get_task(task_id)
    if pending:
        ctx.store.update_action(pending[0]["id"], plan_json=_task_plan(ctx, task))
        return {"action_id": pending[0]["id"], "board": "pending"}
    if task["board_task_id"]:
        plan = {"email_id": task["email_id"], "task_id": task_id, "board_task_id": task["board_task_id"],
                "old_owner": old, "new_owner": new_owner}
        action_id = ctx.store.add_action(email_id=task["email_id"], task_id=task_id, kind="reassign_task",
                                         plan_json=plan, status="pending")
        # the person just chose this exact change, so they approve this exact plan
        return approve_action(ctx, action_id, by, plan_hash(plan))
    return {"board": "none"}


def propose_forward(ctx, email_id: str, to_person: str, requested_by: str) -> int:
    """Prepare an internal forward (summary + the sender's text, never attachments).
    It is only a plan until someone approves it."""
    email = ctx.store.get_email(email_id)
    person = ctx.directory.get(to_person)
    if not email or not person:
        raise ValueError("unknown email or person")
    _require(ctx, requested_by, "forward_internal", "propose:forward_internal", email_id=email_id)
    if email["status"] not in ("triaged", "released"):
        raise ValueError("this email can't be forwarded (quarantined or not triaged)")
    body = (f"ملخص الوكيل: {email['summary_ar']}\n\n--- From: {email['from_addr']} | {email['date'][:16]}\n"
            f"{email['new_text']}")
    plan = {"email_id": email_id, "to": [person.email], "subject": f"Fwd: {email['subject']}", "body": body}
    try:
        dlp = check_outbound("forward_internal", to=plan["to"], body=body, directory=ctx.directory).as_dict()
    except Exception as e:
        dlp = {"blocked": True, "reasons": [f"DLP check failed ({type(e).__name__}); blocked"]}
    ctx.store.audit(f"human:{requested_by}", "propose:forward_internal", email_id=email_id,
                    detail={"to": person.email})
    return ctx.store.add_action(email_id=email_id, kind="forward_internal", plan_json=plan,
                                status="blocked" if dlp["blocked"] else "pending", dlp_json=dlp)


def release_quarantine(ctx, email_id: str, approver: str) -> None:
    plan = {"email_id": email_id}
    _require(ctx, approver, "release_quarantine", "release_quarantine", email_id=email_id)
    action_id = ctx.store.add_action(email_id=email_id, kind="release_quarantine", plan_json=plan,
                                     status="pending")
    approve_action(ctx, action_id, approver, plan_hash(plan))


def rollback(ctx, action_id: int, by: str) -> dict:
    """Undo an executed action where that is possible, through the permission gate.
    A sent email can't be unsent: the honest answer there is a correction email by a person."""
    action = ctx.store.get_action(action_id)
    if not action or action["status"] != "executed":
        raise ValueError("only an executed action can be rolled back")
    kind, result = action["kind"], action["result_json"] or {}
    if kind not in ("create_task", "reassign_task"):
        raise ValueError(f"{kind} can't be rolled back automatically (email already sent)")
    _require(ctx, by, "create_task", f"rollback:{kind}", action_id=action_id, email_id=action["email_id"])
    plan = {"kind": kind, "email_id": action["email_id"], "task_id": action["task_id"],
            "action_id": action_id,
            "board_task_id": result.get("board_task_id") or action["plan_json"].get("board_task_id"),
            "old_owner": action["plan_json"].get("old_owner")}
    detail = execute("rollback_action", plan, ctx=ctx, approved_by=by)
    if kind == "create_task":
        ctx.store.update_task(action["task_id"], board_task_id=None, status="needs_confirmation")
        ctx.store.add_action(email_id=action["email_id"], task_id=action["task_id"], kind="create_task",
                             plan_json=action["plan_json"], status="pending")
    else:
        ctx.store.update_task(action["task_id"], final_owner=plan["old_owner"])
    ctx.store.update_action(action_id, status="rolled_back")
    return detail
