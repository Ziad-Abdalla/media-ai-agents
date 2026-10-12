"""Step 1b: clean text so it can be compared, and split new text from quoted history.

Two different jobs:
  normalize_ar(text)  makes Arabic text comparable: "إجتماع" and "اجتماع" become the same,
                      diacritics and the stretching character (ـ) are removed, Arabic digits
                      become 0-9. Used for matching (subjects, names, quotes), never for display.
  split_body(email)   separates what the sender wrote THIS time (classified) from the earlier
                      messages quoted underneath (kept only as context), and pulls out the
                      original message inside a forward.
"""

import re
import unicodedata

from .models import Email

TASHKEEL = re.compile(r"[ؐ-ًؚ-ٰٟۖ-ۭ]")
TATWEEL = "ـ"
ZERO_WIDTH = re.compile(r"[​-‏‪-‮⁠-⁤﻿]")
ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
LETTER_MAP = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ى": "ي", "ة": "ه",
                            "ؤ": "و", "ئ": "ي", "گ": "ك", "ڤ": "ف", "ی": "ي", "ک": "ك"})


def normalize_ar(text: str) -> str:
    """Lower-case, strip diacritics/tatweel/zero-width chars, unify letter forms and digits."""
    text = unicodedata.normalize("NFKC", text or "")
    text = ZERO_WIDTH.sub("", text)
    text = TASHKEEL.sub("", text).replace(TATWEEL, "")
    text = text.translate(LETTER_MAP).translate(ARABIC_DIGITS)
    return re.sub(r"\s+", " ", text).strip().lower()


SUBJECT_PREFIX = re.compile(
    r"^\s*((re|fw|fwd|aw|tr|رد|ر|إعادة توجيه|اعادة توجيه|توجيه|تحويل)\s*(\[\d+\])?\s*[:：]\s*)+",
    re.IGNORECASE)


def normalize_subject(subject: str) -> str:
    """'RE: Fwd: رد: موعد التصوير' -> 'موعد التصوير' (normalized)."""
    s = subject or ""
    while True:
        stripped = SUBJECT_PREFIX.sub("", s)
        if stripped == s:
            break
        s = stripped
    s = re.sub(r"[\[\]()【】«»\"'!?.,،؛:-]+", " ", s)
    return normalize_ar(s)


# Lines that start the quoted history of a reply.
REPLY_HEADER = re.compile(
    r"^\s*(On .{4,200}wrote:\s*$"                     # Gmail / Apple Mail (English)
    r"|في .{4,200}كتب.{0,60}:\s*$"                     # Gmail (Arabic)
    r"|-{2,}\s*Original Message\s*-{2,}"               # Outlook
    r"|-{2,}\s*الرسالة الأصلية\s*-{2,}"
    r"|From:\s.+\s*$(?=[\s\S]{0,300}^(Sent|Date):)"    # Outlook header block
    r"|من:\s.+\s*$(?=[\s\S]{0,300}^(أرسلت|أُرسلت|التاريخ):))",
    re.IGNORECASE | re.MULTILINE)
FORWARD_HEADER = re.compile(
    r"^\s*-{2,}\s*(Forwarded message|Begin forwarded message|رسالة (معاد|مُعاد|معادة|مُعادة) توجيهها|"
    r"الرسالة (المعاد|المُعاد|المعادة|المُعادة) توجيهها)\s*-{2,}\s*$|^\s*Begin forwarded message:\s*$",
    re.IGNORECASE | re.MULTILINE)
FIELD = re.compile(r"^\s*(From|Date|Subject|To|Cc|Sent|من|التاريخ|الموضوع|إلى|الى|نسخة)\s*:\s*(.*)$",
                   re.IGNORECASE)
FIELD_NAMES = {"from": "from", "من": "from", "date": "date", "sent": "date", "التاريخ": "date",
               "subject": "subject", "الموضوع": "subject"}
SIGNATURE_NOISE = re.compile(r"^\s*(Sent from my \w+|أرسلت من .+|Get Outlook for \w+)\s*$",
                             re.IGNORECASE | re.MULTILINE)


def _parse_forward(block: str) -> dict:
    """The original email inside a forward: its From/Date/Subject lines and its text."""
    info = {"from": "", "subject": "", "date": "", "text": ""}
    lines = block.splitlines()
    i = 0
    while i < len(lines) and (not lines[i].strip() or FIELD.match(lines[i])):
        m = FIELD.match(lines[i])
        if m:
            key = FIELD_NAMES.get(m.group(1).lower())
            if key and not info[key]:
                info[key] = m.group(2).strip()
        i += 1
    info["text"] = "\n".join(lines[i:]).strip()
    return info


def split_body(email: Email) -> Email:
    """Fill email.new_text, email.quoted_text and email.forwarded. Returns the same email."""
    body = (email.body or "").replace("\r\n", "\n")
    fwd = FORWARD_HEADER.search(body)
    reply = REPLY_HEADER.search(body)

    if fwd and (not reply or fwd.start() <= reply.start()):
        email.new_text = body[:fwd.start()].strip()
        email.forwarded = _parse_forward(body[fwd.end():])
        email.quoted_text = ""
    elif reply:
        email.new_text = body[:reply.start()].strip()
        email.quoted_text = body[reply.start():].strip()
    else:
        # No header line, but maybe "> " quoted lines at the bottom.
        lines = body.split("\n")
        first_quote = next((i for i, l in enumerate(lines) if l.startswith(">")), None)
        if first_quote is not None:
            email.new_text = "\n".join(lines[:first_quote]).strip()
            email.quoted_text = "\n".join(lines[first_quote:]).strip()
        else:
            email.new_text = body.strip()

    # Some clients put "> " quotes without a header and without a blank line; drop stray ones.
    email.new_text = SIGNATURE_NOISE.sub("", "\n".join(
        l for l in email.new_text.split("\n") if not l.startswith(">"))).strip()
    return email


def text_for_classification(email: Email, max_chars: int = 4000) -> str:
    """What the model reads: the new text, plus the forwarded original if this is a forward
    (in a forward, the forwarded message IS the substance). Quoted reply history is left out."""
    parts = [email.new_text]
    if email.forwarded:
        f = email.forwarded
        parts.append(f"[Forwarded message] From: {f['from']} | Date: {f['date']} | "
                     f"Subject: {f['subject']}\n{f['text']}")
    return "\n\n".join(p for p in parts if p).strip()[:max_chars]
