"""Cancel an approved booking, for example one the manager approved by mistake.

    python scripts/cancel_booking.py 3 "approved by mistake"

What it does:
  - sets bookings.cancelled_at and cancel_reason, so the booking stops counting in the clash check;
  - if the booking reached Odoo, removes its To-Do activity there (same as odoo_link.py undo);
  - keeps the row and the email's 'approved' status, so the audit trail shows both the approval
    and the cancellation. The weekly summary counts cancellations on their own line.

It does not email the requester; the bookings desk tells them. Standard library only.
"""
import sys

from odoo_link import psql, remove_activity


def cancel(booking_id, reason):
    rows = psql(f"SELECT cancelled_at IS NOT NULL FROM bookings WHERE id = {int(booking_id)}")
    if not rows:
        sys.exit(f"there is no booking {booking_id}")
    if rows[0][0] == "t":
        sys.exit(f"booking {booking_id} is already cancelled")
    # The reason is typed by a person; pass it as a dollar-quoted literal so quotes in it can't break the SQL.
    tag = "$reason$"
    if tag in reason:
        sys.exit("the reason can't contain $reason$")
    psql(f"UPDATE bookings SET cancelled_at = now(), cancel_reason = {tag}{reason}{tag} WHERE id = {int(booking_id)}")
    try:
        activity = remove_activity(booking_id)
        odoo_note = f"; Odoo activity {activity} removed" if activity else ""
    except (OSError, SystemExit) as e:   # Odoo down or login refused: the cancellation still stands
        odoo_note = f"; Odoo could not be reached ({e}), run `odoo_link.py undo {booking_id}` later"
    print(f"booking {booking_id} cancelled{odoo_note}. Tell the requester; the system doesn't email them.")


if __name__ == "__main__":
    args = sys.argv[1:]
    if len(args) == 2 and args[0].isdigit() and args[1].strip():
        cancel(args[0], args[1].strip())
    else:
        sys.exit(__doc__)
