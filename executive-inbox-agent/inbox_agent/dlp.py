"""Step 5b (Q44): data-loss prevention check on EVERY outgoing message, in code.

It runs twice: when the draft is created (so the approval page can show the result) and
again right before sending (in case anything changed). A person approving a reply can't
override a block: there is no "send anyway" button.

What it blocks:
  - any attachment (the agent has no permission to attach files, ever)
  - any recipient outside the allowed domains (company + approved partners)
  - for internal forwards and the briefing: any recipient outside the company
  - a reply that adds recipients who were not in the conversation
  - confidential content going outside the company: "سري" / "confidential" markers,
    IBANs, Saudi ID / iqama numbers, lists of staff email addresses, file-sharing links
"""

import re
from dataclasses import dataclass, field

from .normalize import normalize_ar

CONFIDENTIAL_MARKERS = ["سري", "سري للغايه", "سري وخاص", "للاستخدام الداخلي", "داخلي فقط",
                        "confidential", "strictly confidential", "internal only", "not for distribution",
                        "do not forward", "لا يعاد توجيهها"]
IBAN = re.compile(r"\bSA\d{2}\s?(\d{4}\s?){5}\b", re.IGNORECASE)
SAUDI_ID = re.compile(r"(?<!\d)[12]\d{9}(?!\d)")
EMAIL_ADDR = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")
FILE_SHARE = re.compile(r"(drive\.google|dropbox|wetransfer|onedrive|sharepoint|mega\.nz|box\.com)",
                        re.IGNORECASE)


@dataclass
class DLPResult:
    reasons: list[str] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return bool(self.reasons)

    def as_dict(self) -> dict:
        return {"blocked": self.blocked, "reasons": self.reasons}


def check_outbound(kind: str, *, to: list[str], body: str, directory, cc: list[str] | None = None,
                   attachments: list | None = None, conversation: list[str] | None = None) -> DLPResult:
    """kind: send_reply / forward_internal / send_briefing. Returns the reasons it's blocked."""
    r = DLPResult()
    recipients = [a.lower() for a in (to or []) + (cc or [])]
    if not recipients:
        r.reasons.append("no recipient")
    if attachments:
        r.reasons.append("attachments are forbidden for the agent (attach_files)")

    outside = [a for a in recipients if not directory.is_allowed_recipient(a)]
    if outside:
        r.reasons.append(f"recipient outside allowed domains: {', '.join(outside)}")

    if kind in ("forward_internal", "send_briefing"):
        external = [a for a in recipients if not directory.is_internal(a)]
        if external:
            r.reasons.append(f"{kind} may only go inside the company: {', '.join(external)}")
    if kind == "send_briefing":
        target = directory.company["executive_briefing_to"].lower()
        if recipients != [target]:
            r.reasons.append(f"the briefing may only go to {target}")
    if kind == "send_reply" and conversation is not None:
        new_people = [a for a in recipients if a not in {c.lower() for c in conversation}]
        if new_people:
            r.reasons.append(f"reply adds people who were not in the conversation: {', '.join(new_people)}")

    leaves_company = any(not directory.is_internal(a) for a in recipients)
    if leaves_company:
        text = normalize_ar(body)
        markers = [m for m in CONFIDENTIAL_MARKERS if normalize_ar(m) in text]
        if markers:
            r.reasons.append(f"confidential marker in an external message: {', '.join(markers)}")
        if IBAN.search(body or ""):
            r.reasons.append("bank account number (IBAN) in an external message")
        if SAUDI_ID.search(normalize_ar(body)):
            r.reasons.append("national ID / iqama number in an external message")
        addrs = [m.group(0).lower() for m in EMAIL_ADDR.finditer(body or "")]
        foreign = sorted({a for a in addrs if not directory.is_allowed_recipient(a)})
        if foreign:
            r.reasons.append(f"mentions an address outside allowed domains: {', '.join(foreign)}")
        internal_addrs = [a for a in addrs if directory.is_internal(a)]
        if len(internal_addrs) >= 3:
            r.reasons.append("list of staff email addresses in an external message")
        if FILE_SHARE.search(body or ""):
            r.reasons.append("file-sharing link in an external message")
    return r
