"""Step 4 (Q43): who should own a task, and when a person must confirm it.

Two independent opinions:
  the model     suggests an owner from the directory, with a reason and a confidence
  the rules     this file: explicit instructions ("ask Noura to..."), the category's
                department (contracts -> legal, invoices -> finance, approvals -> GM),
                then department keywords in the task text
Then checks that catch the usual mistakes:
  - the two opinions disagree                         -> a person confirms
  - the model is unsure, or names someone unknown     -> a person confirms
  - the task is urgent                                -> ALWAYS a person confirms
  - the evidence quote isn't really in the email      -> a person confirms (possible invention)
  - the owner is out of office                        -> goes to the delegate, flagged
Every task keeps its evidence quote, both opinions and the reasons, so the reviewer sees why.
"""

import difflib
import re
from dataclasses import dataclass, field

from .normalize import normalize_ar

CATEGORY_DEPARTMENT = {"legal_contract": "legal", "vendor_finance": "finance", "meeting": "executive_office"}
APPROVAL_OWNER = "reem"   # approval requests go to the General Manager (staff.yaml)

# "ask Noura to ...", "Noura will ...", "please assign to Majed", "خل نورة", "اطلب من نورة", "كلّف"
DIRECTIVE = r"(ask|tell|have|get|assign(ed)? to|cc|loop in|forward to|please|kindly)\s+{name}\b|{name}\s+(will|should|to handle|can you|please)|(اطلب|خل|كلف|بلغ|وجه|حول|ارسل|خلو|تواصل مع|نسق مع)(وا|ي|و)?\s+(من\s+|ل|الى\s+)?{name}|{name}\s+(يتولى|تتولى|يتابع|تتابع|يرتب|ترتب|يجهز|تجهز)"


@dataclass
class Decision:
    proposed_owner: str | None
    rule_owner: str | None
    rule_reason: str
    owner_note: str | None
    needs_confirmation: bool
    reasons: list[str] = field(default_factory=list)


def evidence_in_email(quote: str, email_text: str, min_ratio: float = 0.85) -> bool:
    """Is the quote really in the email? Exact match on normalized text, or a near match
    (the model may fix a typo or a spacing). Empty quotes don't count."""
    q, t = normalize_ar(quote), normalize_ar(email_text)
    if len(q) < 4:
        return False
    if q in t:
        return True
    m = difflib.SequenceMatcher(None, t, q, autojunk=False).find_longest_match(0, len(t), 0, len(q))
    if m.size / len(q) >= min_ratio:
        return True
    # a few separate pieces: count how much of the quote is covered by matching blocks
    blocks = difflib.SequenceMatcher(None, t, q, autojunk=False).get_matching_blocks()
    covered = sum(b.size for b in blocks if b.size >= 6)
    return covered / len(q) >= min_ratio


def _directive_person(directory, text: str):
    t = normalize_ar(text)
    for p in directory.mentioned_people(text):
        for n in {p.name_en, p.name_ar, *p.aliases}:
            rx = DIRECTIVE.format(name=re.escape(normalize_ar(n)))
            if re.search(rx, t):
                return p
    return None


def rule_owner(directory, *, category: str, task_text: str, evidence: str, subject: str,
               email_text: str) -> tuple[str | None, str, bool]:
    """The rules' opinion: (person id or None, reason, strong). Strong means an explicit name
    or the category decided it, so it beats the model when the two disagree."""
    named = _directive_person(directory, f"{evidence}\n{email_text}")
    if named:
        return named.id, f"the email asks for {named.name_en} by name", True

    if category == "approval_needed":
        return APPROVAL_OWNER, "approval requests go to the General Manager", True
    if category in CATEGORY_DEPARTMENT:
        head = directory.head_of(CATEGORY_DEPARTMENT[category])
        return head.id, f"{category} goes to {CATEGORY_DEPARTMENT[category]} (head: {head.name_en})", True

    # keyword scores: the task itself counts double, then the subject
    scores: dict[str, int] = {}
    for text, weight in ((f"{task_text} {evidence}", 2), (subject, 1)):
        for dept, s in directory.department_scores(text).items():
            scores[dept] = scores.get(dept, 0) + s * weight
    scores.pop("executive_office", None)  # the office is who we route FOR, not a default owner
    if not scores:
        return None, "no department keyword matched", False
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
        return None, f"tie between {ranked[0][0]} and {ranked[1][0]}", False
    dept = ranked[0][0]
    # a specific person in that department whose responsibilities match, else the head
    people = [p for p in directory.people.values() if p.department == dept]
    best = max(people, key=lambda p: len(directory.responsibility_hits(p, f"{task_text} {evidence}")))
    if directory.responsibility_hits(best, f"{task_text} {evidence}"):
        return best.id, f"keywords match {dept}; responsibilities of {best.name_en}", False
    head = directory.head_of(dept)
    return head.id, f"keywords match {dept} (head: {head.name_en})", False


def decide(directory, *, task, category: str, priority: str, subject: str, email_text: str,
           received: str) -> Decision:
    reasons: list[str] = []
    model_owner = task.suggested_owner_id if directory.get(task.suggested_owner_id) else None
    if task.suggested_owner_id and not model_owner:
        reasons.append(f"model suggested '{task.suggested_owner_id}', who is not in the directory")

    r_owner, r_reason, strong = rule_owner(directory, category=category, task_text=task.what_ar,
                                   evidence=task.evidence_quote, subject=subject, email_text=email_text)

    # Out of office: both opinions are compared AFTER moving to the delegate.
    notes = []

    def present(pid):
        if not pid:
            return None
        person, note = directory.available(directory.get(pid), received)
        if note:
            notes.append(note)
        return person.id

    model_owner, r_owner = present(model_owner), present(r_owner)

    if model_owner and r_owner and model_owner != r_owner:
        reasons.append(f"model says {model_owner}, rules say {r_owner}")
    if not r_owner:
        reasons.append(f"rules found no owner ({r_reason})")
    if not model_owner:
        reasons.append("model gave no valid owner")
    if task.owner_confidence == "low":
        reasons.append("model is not confident")
    if task.urgent or priority == "urgent":
        reasons.append("urgent task: always confirmed by a person")
    if not evidence_in_email(task.evidence_quote, email_text):
        reasons.append("evidence quote not found in the email")
    if notes:
        reasons.append("owner is away; proposed the delegate")

    # Which one to propose when they differ: an explicit name or the category is a strong
    # rule; otherwise prefer the model, which read the whole email.
    proposed = r_owner if (strong and r_owner) else (model_owner or r_owner)
    return Decision(proposed_owner=proposed, rule_owner=r_owner, rule_reason=r_reason,
                    owner_note="; ".join(dict.fromkeys(notes)) or None,
                    needs_confirmation=bool(reasons), reasons=reasons)
