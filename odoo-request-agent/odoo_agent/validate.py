"""Step 3: check the extracted request in plain code. No AI here.

Returns a list of problems. An empty list means the request is complete.
Each problem is English text (shown to staff on the approval page) that also carries an
Arabic version, so a request written in Arabic gets its "please send X" reply in Arabic.
"""

import re
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime

from . import config
from .models import Email, PurchaseRequest


class Problem(str):
    """A problem in English (it is a normal string) with its Arabic wording in .ar."""

    def __new__(cls, en: str, ar: str):
        problem = super().__new__(cls, en)
        problem.ar = ar
        return problem


def sender_allowed(email: Email) -> bool:
    """Only internal senders, by the From header (never by what the body claims).
    The From header can be forged, so this stops casual outside mail, not a determined
    attacker. Production would also require Gmail's Authentication-Results header to say
    dmarc=pass. The human approval is the backstop either way."""
    domain = email.sender.rsplit("@", 1)[-1]
    return domain in config.COMPANY_DOMAINS


def validate(request: PurchaseRequest, email: Email) -> list[str]:
    problems = []
    if not request.vendor_name:
        problems.append(Problem("vendor name", "اسم المورد"))
    if not request.production:
        problems.append(Problem("the production (series or programme) this is for",
                                "اسم الإنتاج (المسلسل أو البرنامج) اللي الطلب له"))
    if not request.approval_reference:
        problems.append(Problem("approval reference (the internal approval number)",
                                "رقم الموافقة الداخلية"))
    if not request.items:
        problems.append(Problem("at least one item to order", "بند واحد على الأقل للطلب"))

    allowed = ", ".join(config.ALLOWED_CURRENCIES)
    for i, item in enumerate(request.items, start=1):
        if item.quantity is None or item.quantity <= 0:
            problems.append(Problem(f"quantity for item {i} ({item.name})",
                                    f"الكمية للبند {i} ({item.name})"))
        if item.unit_price is None or item.unit_price <= 0:
            problems.append(Problem(f"unit price for item {i} ({item.name})",
                                    f"سعر الوحدة للبند {i} ({item.name})"))
        if not item.currency or item.currency.upper() not in config.ALLOWED_CURRENCIES:
            problems.append(Problem(f"currency for item {i} (must be one of {allowed})",
                                    f"العملة للبند {i} (لازم تكون {allowed})"))

    currencies = {i.currency.upper() for i in request.items if i.currency}
    if len(currencies) > 1:
        found = ", ".join(sorted(currencies))
        problems.append(Problem(f"one currency for the whole order (found {found})",
                                f"عملة واحدة للطلب كله (الموجود: {found})"))

    problems += _check_date(request.needed_by, _received_date(email))
    return problems


def _check_date(needed_by: str | None, today: date) -> list[str]:
    if not needed_by:
        return [Problem("the date it is needed by", "التاريخ اللي تحتاجونه فيه")]
    try:
        needed = date.fromisoformat(needed_by)
    except ValueError:
        return [Problem(f"a valid needed-by date (got '{needed_by}')",
                        f"تاريخ صحيح للاحتياج (وصلنا '{needed_by}')")]
    if needed < today:
        return [Problem(f"a needed-by date in the future ({needed_by} has passed)",
                        f"تاريخ احتياج في المستقبل ({needed_by} فات)")]
    if needed > today + timedelta(days=365):
        return [Problem(f"a needed-by date within a year ({needed_by} looks wrong)",
                        f"تاريخ احتياج خلال سنة ({needed_by} يبدو غلط)")]
    return []


def _received_date(email: Email) -> date:
    for parse in (datetime.fromisoformat, parsedate_to_datetime):
        try:
            return parse(email.received_at).date()
        except (TypeError, ValueError):
            pass
    return date.today()


ARABIC_LETTER = re.compile(r"[؀-ۿ]")


def is_mostly_arabic(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    return bool(letters) and sum(bool(ARABIC_LETTER.match(c)) for c in letters) / len(letters) > 0.5


def draft_needs_info_reply(email: Email, problems: list[str]) -> str:
    """A reply asking for exactly what is missing, in the language the request was written in.
    Stored as a draft, never sent automatically."""
    if is_mostly_arabic(email.body):
        lines = "\n".join(f"- {getattr(p, 'ar', p)}" for p in problems)
        return (
            f"السلام عليكم،\n\nشكرًا على طلبك \"{email.subject}\". قبل ما نرفع أمر الشراء "
            f"نحتاج منك المعلومات التالية:\n\n{lines}\n\n"
            "رد على هذا الإيميل بالتفاصيل الناقصة، ويعطيك العافية.\n\nفريق المشتريات"
        )
    lines = "\n".join(f"- {p}" for p in problems)
    return (
        f"Hello,\n\nThanks for your request \"{email.subject}\". Before we can raise a "
        f"purchase order we need the following:\n\n{lines}\n\n"
        "Please reply to this email with the missing details.\n\nProcurement"
    )
