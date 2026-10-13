"""Take the README screenshots with headless Edge (Playwright, channel="msedge").

Needs: the agent database filled (python -m inbox_agent run), the approval page running
(python -m inbox_agent serve), and Mailpit for the last shot.
  .venv\\Scripts\\python scripts\\screenshots.py
"""

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

from inbox_agent.store import Store

BASE = "http://127.0.0.1:8010"
OUT = Path(__file__).resolve().parent.parent / "docs" / "screenshots"


def email_id(store, dataset_id):
    row = store.one("SELECT id FROM emails WHERE source_id = ? OR id = ?", (dataset_id, dataset_id))
    if row:
        return row["id"]
    # Mailpit ids aren't dataset ids: find by the dataset's Message-ID
    from inbox_agent.inbox import load_dataset
    mid = next(i["message_id"] for i in load_dataset() if i["id"] == dataset_id)
    return store.email_by_message_id(mid)["id"]


def main():
    store = Store()
    shots = [("inbox.png", "/", None),
             ("task-evidence.png", f"/email/{email_id(store, sys.argv[1] if len(sys.argv) > 1 else 'e19')}", None),
             ("quarantine.png", f"/email/{email_id(store, 'e06')}", None),
             ("kpi.png", "/kpi", None),
             ("briefing.png", "/briefing?as_of=2026-10-13", 760)]
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        ctx = browser.new_context(viewport={"width": 1440, "height": 1000}, device_scale_factor=1,
                                  locale="ar-SA")
        ctx.add_cookies([{"name": "user", "value": "sara", "url": BASE}])
        page = ctx.new_page()
        for name, path, width in shots:
            if width:
                page.set_viewport_size({"width": width, "height": 1000})
            page.goto(BASE + path, wait_until="networkidle")
            page.screenshot(path=str(OUT / name), full_page=name in ("task-evidence.png", "briefing.png"))
            print("saved", OUT / name)
        page.set_viewport_size({"width": 1440, "height": 900})
        try:
            page.goto("http://localhost:8027/", wait_until="networkidle")
            page.screenshot(path=str(OUT / "mailpit.png"))
            print("saved", OUT / "mailpit.png")
        except Exception as e:  # Mailpit not running: skip that one
            print("mailpit screenshot skipped:", e)
        browser.close()


if __name__ == "__main__":
    main()
