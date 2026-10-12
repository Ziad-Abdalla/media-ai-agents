"""Undo everything one run wrote to Odoo. Run by a person: python -m odoo_agent rollback <run_id>

This is a human tool, not an agent action, so it may delete the draft PO the agent made
(deleting is forbidden for the agent itself). It works even when the kill switch is on,
because that's exactly when you might need it.
"""

from .actions import ORIGIN_PREFIX


class RollbackRefused(Exception):
    pass


def rollback(store, odoo, run_id: str, actor: str = "human:cli") -> list[str]:
    run = store.get_run(run_id)
    if not run:
        raise ValueError(f"no run {run_id}")
    done = []

    # 1. Purchase orders: find them by the key in `origin`. This also catches a PO whose
    #    create "succeeded but the answer got lost", which has no audit row of its own.
    if run["idempotency_key"]:
        pos = odoo.search_read("purchase.order",
                               [("origin", "=", ORIGIN_PREFIX + run["idempotency_key"])],
                               ["id", "name", "state"])
        for po in pos:
            if po["state"] not in ("draft", "sent", "cancel"):
                raise RollbackRefused(f"{po['name']} is '{po['state']}' (someone confirmed it). "
                                      "Handle it in Odoo by hand.")
        for po in pos:
            odoo.call("purchase.order", "button_cancel", [po["id"]])
            odoo.call("purchase.order", "unlink", [po["id"]])
            store.audit(run_id, actor, "rollback_delete_po", "purchase.order", po["id"], before=po)
            done.append(f"deleted draft PO {po['name']}")

    # 2. Field changes and new vendors, newest first.
    for row in reversed(store.audit_rows(run_id)):
        if row["operation"] == "write":
            odoo.write(row["model"], row["record_id"], row["before"])
            store.audit(run_id, actor, "rollback_write", row["model"], row["record_id"],
                        before=row["after"], after=row["before"])
            done.append(f"restored {row['model']} {row['record_id']}")
        elif row["operation"] == "create" and row["model"] == "res.partner":
            # Archive rather than delete: other records may already point at this vendor.
            odoo.write("res.partner", row["record_id"], {"active": False})
            store.audit(run_id, actor, "rollback_archive_vendor", "res.partner", row["record_id"],
                        before={"active": True}, after={"active": False})
            done.append(f"archived vendor {row['record_id']}")

    store.update_run(run_id, status="rolled_back")
    return done
