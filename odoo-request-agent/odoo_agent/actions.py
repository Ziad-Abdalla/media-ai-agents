"""The actions themselves. Never call these directly: go through permissions.execute().

Each write records an audit row with the values before and after.
"""

import smtplib
from email.message import EmailMessage

from . import config

ORIGIN_PREFIX = "email-agent:"


class ForbiddenAction(Exception):
    """The action isn't allowed, or (raised inside an action) its own safety rule is broken."""


def draft_reply(*, store, run_id, text, **_):
    store.update_run(run_id, reply_draft=text)
    return text


def create_vendor(*, odoo, store, run_id, actor, values):
    """Idempotent like the PO: values["ref"] holds the run's key, and is searched first.
    The same key lets rollback find the vendor even if the create answer was lost."""
    existing = odoo.search_read("res.partner", [("ref", "=", values["ref"])], ["id", "name"])
    if existing:
        store.audit(run_id, actor, "found_existing", "res.partner", existing[0]["id"],
                    after=existing[0])
        return existing[0]["id"]
    partner_id = odoo.create("res.partner", values)
    store.audit(run_id, actor, "create", "res.partner", partner_id, before=None, after=values)
    return partner_id


def create_purchase_order(*, odoo, store, run_id, actor, values):
    """Idempotent: the key in values["origin"] is searched first, so a retry never makes a 2nd PO."""
    existing = odoo.search_read("purchase.order", [("origin", "=", values["origin"])], ["id", "name"])
    if existing:
        store.audit(run_id, actor, "found_existing", "purchase.order", existing[0]["id"],
                    after=existing[0])
        return existing[0]["id"]
    po_id = odoo.create("purchase.order", values)
    # If the connection drops right here, Odoo has the PO but we never got po_id.
    # That's fine: the retry finds it by origin above.
    store.audit(run_id, actor, "create", "purchase.order", po_id, before=None, after=values)
    return po_id


# Not used by build_plan today: no plan edits an existing PO. It's here so the
# "only draft POs can be changed" rule and the rollback restore are real and tested,
# ready for a later "amend this order" email.
def update_purchase_order(*, odoo, store, run_id, actor, po_id, values):
    current = odoo.search_read("purchase.order", [("id", "=", po_id)], ["state", *values])[0]
    if current["state"] != "draft":
        raise ForbiddenAction(f"PO {po_id} is '{current['state']}', only draft POs can be changed")
    before = {field: current[field] for field in values}
    odoo.write("purchase.order", po_id, values)
    store.audit(run_id, actor, "write", "purchase.order", po_id, before=before, after=values)
    return po_id


def send_email(*, store, run_id, actor, to, subject, body, attachments=None, **_):
    """The only way the agent can send email: internal addresses only, never attachments."""
    if attachments:
        raise ForbiddenAction("emails with attachments are never sent by the agent")
    domain = to.rsplit("@", 1)[-1].lower()
    if domain not in config.COMPANY_DOMAINS:
        raise ForbiddenAction(f"'{to}' is outside the company; the agent only emails internal addresses")

    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = config.AGENT_EMAIL, to, subject
    msg.set_content(body)
    with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=10) as smtp:
        smtp.send_message(msg)
    store.audit(run_id, actor, "send_email", after={"to": to, "subject": subject})
    return True
