"""Step 5a (Q44): treat email content as data, and catch attempts to instruct the agent.

Three layers, and only the last one has to be perfect:
  1. spotlight()  wraps every piece of email text in tags with a random marker the sender
                  cannot guess, and tells the model that text inside is data, not orders.
  2. scan()       a rule-based detector (Arabic + English) over EVERY part of the email: the
                  new text, quoted history, the forwarded message, hidden HTML text and the
                  text of attachments. A hit quarantines the email.
  3. permissions.py + dlp.py   even if 1 and 2 both miss, the agent has no tool that can
                  attach files, bulk-export, or send outside allowed domains. That is enforced
                  in code, so a fooled model still can't leak anything.
"""

import re
import secrets
from dataclasses import dataclass, field

from .models import Email
from .normalize import normalize_ar

# Patterns run on normalize_ar() text: lower-case, أ/إ/آ -> ا, ة -> ه, ى -> ي, no diacritics.
EN_RULES = {
    "ignore_instructions": r"\b(ignore|disregard|forget|override|bypass)\b.{0,40}\b(instruction|instructions|rules|prompt|guidelines|policy|policies)\b",
    "system_prompt_probe": r"\b(system prompt|your instructions|hidden instructions|developer mode|maintenance mode|jailbreak|you are now)\b",
    "addressing_the_ai": r"\b(note to|attention|message for|instructions? for)\s+(the\s+)?(ai|assistant|agent|bot|llm|language model|automated system)\b|\b(ai|assistant|agent|bot)\s*(system)?\s*:\s*(please\s+)?(send|forward|reply|mark|approve|export|ignore)",
    "bulk_exfiltration": r"\b(send|forward|export|email|share|upload|attach|copy)\b.{0,30}\b(all|every|entire|full|complete|whole)\b.{0,30}\b(files?|documents?|contracts?|emails?|inbox|attachments?|folders?|data|records|budgets?|invoices?|staff list|contacts?)\b.{0,80}(\bto\s+\S+@\S+|\byou (have|can (see|access|read))|\bin your (inbox|system|access|memory)|personal (email|gmail|address))",
    "secrets_request": r"\b(send|reply|share|provide|forward)\b.{0,40}\b(bank details|iban|passwords?|credentials|api keys?|login)\b",
}
AR_RULES = {
    "ignore_instructions": r"(تجاهل|تجاهلي|انس|انسي|تخط|تجاوز|اهمل)\s.{0,30}(التعليمات|تعليمات|الاوامر|القواعد|التوجيهات)",
    "system_prompt_probe": r"(تعليمات النظام|تعليماتك|وضع الصيانه|وضع المطور|اطبع التعليمات|موجه النظام)",
    "addressing_the_ai": r"(يا|ايها|يا ايها|الى|عزيزي)\s+(ال)?(مساعد|المساعد الذكي|الذكاء الاصطناعي|البوت|الوكيل الذكي|النظام الالي)|(تعليمات|ملاحظه|رساله|تنبيه)\s+(لل|الى ال|ل)(مساعد|وكيل|نظام|بوت|ذكاء)",
    "bulk_exfiltration": r"(ارسل|ارسلي|حول|حولي|حوّل|اعد توجيه|صدر|شارك|ابعث|ابعثي|انسخ|ارفق|طرش)\s.{0,30}(جميع|كل|كامل|كافه)\s.{0,20}(ال)?(ملفات|الملفات|عقود|العقود|ايميلات|الايميلات|رسايل|رسائل|الرسائل|مستندات|المستندات|بيانات|البيانات|المرفقات|ميزانيه|الميزانيه|فواتير|الفواتير|ملف).{0,80}(\S+@\S+|لديك|عندك|اللي عندك|الي عندك|هالايميل|هالبريد|هذا الايميل|هذا البريد|الايميل التالي|العنوان التالي|ايميلي|بريدي الخاص|بريدي الشخصي)",
    "secrets_request": r"(ارسل|ارسلي|زودنا|ابعث|شارك|حول).{0,40}(بيانات الحساب البنكي|الايبان|ايبان|كلمه المرور|كلمات المرور|الحساب البنكي)",
}
# "send <sensitive thing> ... to someone@domain": fires only if that address is outside the
# company and its approved partners (a talent agent asking for his own signed contract is normal).
SEND_TO_ADDRESS = re.compile(
    r"(send|forward|email|share|ارسل|ارسلي|حول|ابعث|شارك|طرش).{0,120}?"
    r"(contracts?|phone numbers|budgets?|bank|files|schedule|passwords?|عقود|عقودهم|ارقام|هواتف|جوالات|ميزانيه|"
    r"الحساب البنكي|ملفات|الملفات|جدول التصوير|كلمات المرور)"
    r".{0,100}?([\w.+-]+@[\w-]+(?:\.[\w-]+)+)", re.IGNORECASE | re.DOTALL)

COMPILED = [(name, re.compile(rx, re.IGNORECASE | re.DOTALL)) for name, rx in EN_RULES.items()] + \
           [(name, re.compile(rx, re.IGNORECASE | re.DOTALL)) for name, rx in AR_RULES.items()]


@dataclass
class Signal:
    rule: str        # which rule fired
    surface: str     # where: new_text, quoted_text, forwarded, hidden_html, attachment:<name>, sender
    snippet: str     # the matching words, so a person can see why


@dataclass
class GuardResult:
    signals: list[Signal] = field(default_factory=list)

    @property
    def flagged(self) -> bool:
        return bool(self.signals)

    def as_dict(self) -> dict:
        return {"flagged": self.flagged,
                "signals": [vars(s) for s in self.signals]}


def _surfaces(email: Email) -> list[tuple[str, str]]:
    out = [("subject", email.subject), ("new_text", email.new_text or email.body),
           ("quoted_text", email.quoted_text)]
    if email.forwarded:
        out.append(("forwarded", email.forwarded.get("text", "")))
    if email.html_text:
        body_norm = normalize_ar(email.body)
        hidden = [line for line in email.html_text.splitlines()
                  if normalize_ar(line) and normalize_ar(line) not in body_norm]
        if hidden:
            out.append(("hidden_html", "\n".join(hidden)))
    for a in email.attachments:
        out.append((f"attachment:{a.filename}", a.text))
    return [(s, t) for s, t in out if t]


def _lookalike(domain: str, company_domains: list[str]) -> bool:
    """sadaf-example.co, sadaf.examp1e ... look like ours but aren't."""
    def squash(d):
        return re.sub(r"[^a-z0-9]", "", d.translate(str.maketrans("01l", "oil")))
    for ours in company_domains:
        if domain == ours:
            return False
        base = ours.split(".")[0]
        if base in domain or squash(domain).startswith(squash(ours)[:len(base) + 3]):
            return True
    return False


def scan(email: Email, directory=None) -> GuardResult:
    result = GuardResult()
    for surface, text in _surfaces(email):
        norm = normalize_ar(text)
        for rule, rx in COMPILED:
            m = rx.search(norm)
            if m:
                result.signals.append(Signal(rule, surface, m.group(0)[:120]))
        for m in SEND_TO_ADDRESS.finditer(norm):
            domain = m.group(3).rsplit("@", 1)[-1]
            if directory is None or domain not in directory.allowed_domains:
                result.signals.append(Signal("send_data_to_outside_address", surface, m.group(0)[:120]))
                break
    if directory is not None:
        domain = email.from_addr.rsplit("@", 1)[-1]
        if _lookalike(domain, directory.company_domains):
            result.signals.append(Signal("lookalike_domain", "sender", email.from_addr))
        elif not directory.is_internal(email.from_addr):
            # an outsider using the exact name of one of our staff (CEO fraud)
            # full names, plus multi-word aliases like "أبو فهد" (a single first name is too common)
            named = [p for p in directory.people.values()
                     if email.from_name and normalize_ar(email.from_name) in
                     {normalize_ar(n) for n in [p.name_en, p.name_ar, *p.aliases] if len(n.split()) > 1}]
            if named:
                result.signals.append(Signal("staff_name_from_outside", "sender",
                                             f"{email.from_name} <{email.from_addr}>"))
    # one signal per (rule, surface) is enough
    seen, unique = set(), []
    for s in result.signals:
        if (s.rule, s.surface) not in seen:
            seen.add((s.rule, s.surface))
            unique.append(s)
    result.signals = unique
    return result


# ---------------------------------------------------------------- spotlighting
def new_marker() -> str:
    """A random tag suffix per request. The sender can't close a tag they can't predict."""
    return secrets.token_hex(4)


def spotlight(label: str, text: str, marker: str) -> str:
    tag = f"untrusted_{label}_{marker}"
    # Defence in depth: remove anything that looks like our own tags from the data.
    cleaned = re.sub(r"</?\s*untrusted_[^>]*>", "[removed tag]", text or "", flags=re.IGNORECASE)
    return f"<{tag}>\n{cleaned}\n</{tag}>"
