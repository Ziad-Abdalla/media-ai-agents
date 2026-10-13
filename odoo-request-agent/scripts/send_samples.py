"""Drop the sample request emails into Mailpit (the local test mail server).
  python scripts/send_samples.py            all of them
  python scripts/send_samples.py crane      only the ones whose id is given

The emails are in samples/requests.json. They are synthetic: made-up people, vendors,
productions and numbers, written in English, Arabic and Saudi dialect mixed with English.
"""

import json
import smtplib
import sys
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from odoo_agent import config  # noqa: E402

SAMPLES = json.loads((ROOT / "samples" / "requests.json").read_text(encoding="utf-8"))["samples"]


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # so Arabic subjects print on Windows
    wanted = set(sys.argv[1:])
    with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT) as smtp:
        for sample in SAMPLES:
            if wanted and sample["id"] not in wanted:
                continue
            msg = EmailMessage()
            msg["From"], msg["To"], msg["Subject"] = sample["sender"], config.AGENT_EMAIL, sample["subject"]
            msg["Message-ID"] = make_msgid(domain="sadaf.example")
            msg["Date"] = formatdate(localtime=True)
            msg.set_content(sample["body"])
            smtp.send_message(msg)
            print("sent:", sample["subject"])


if __name__ == "__main__":
    main()
