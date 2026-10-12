"""Step 3: check the extracted request in plain code. No AI here.

Returns a list of problems. An empty list means the request is complete.
"""

from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime

from . import config
from .models import Email, PurchaseRequest


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
        problems.append("vendor name")
    if not request.approval_reference:
        problems.append("approval reference (the internal approval number)")
    if not request.items:
        problems.append("at least one item to order")

    for i, item in enumerate(request.items, start=1):
        if item.quantity is None or item.quantity <= 0:
            problems.append(f"quantity for item {i} ({item.name})")
        if item.unit_price is None or item.unit_price <= 0:
            problems.append(f"unit price for item {i} ({item.name})")
        if not item.currency or item.currency.upper() not in config.ALLOWED_CURRENCIES:
            problems.append(f"currency for item {i} (must be one of {', '.join(config.ALLOWED_CURRENCIES)})")

    currencies = {i.currency.upper() for i in request.items if i.currency}
    if len(currencies) > 1:
        problems.append("one currency for the whole order (found " + ", ".join(sorted(currencies)) + ")")

    problems += _check_date(request.needed_by, _received_date(email))
    return problems


def _check_date(needed_by: str | None, today: date) -> list[str]:
    if not needed_by:
        return ["the date it is needed by"]
    try:
        needed = date.fromisoformat(needed_by)
    except ValueError:
        return [f"a valid needed-by date (got '{needed_by}')"]
    if needed < today:
        return [f"a needed-by date in the future ({needed_by} has passed)"]
    if needed > today + timedelta(days=365):
        return [f"a needed-by date within a year ({needed_by} looks wrong)"]
    return []


def _received_date(email: Email) -> date:
    for parse in (datetime.fromisoformat, parsedate_to_datetime):
        try:
            return parse(email.received_at).date()
        except (TypeError, ValueError):
            pass
    return date.today()


def draft_needs_info_reply(email: Email, problems: list[str]) -> str:
    """A reply asking for exactly what is missing. Stored as a draft, never sent automatically."""
    lines = "\n".join(f"- {p}" for p in problems)
    return (
        f"Hello,\n\nThanks for your request \"{email.subject}\". Before we can raise a "
        f"purchase order we need the following:\n\n{lines}\n\n"
        "Please reply to this email with the missing details.\n\nProcurement"
    )
