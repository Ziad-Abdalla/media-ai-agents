"""One-command setup for the local n8n stack.

Run after `docker compose up -d`:
    python scripts/setup.py

It does four things:
  1. creates the three credentials (Postgres, Mailpit SMTP, Anthropic key) from
     credentials/credentials.template.json, filling in values from .env
  2. imports both workflows from workflows/
  3. publishes (activates) them and restarts n8n so the webhooks go live
  4. creates the n8n owner login (from N8N_OWNER_EMAIL / N8N_OWNER_PASSWORD in .env)

Only the Python standard library is used. The API key is never printed.
"""
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from string import Template

ROOT = pathlib.Path(__file__).resolve().parent.parent
N8N = "http://localhost:5678"
WORKFLOW_IDS = ["BookingErrors001", "BookingIntake001"]  # error workflow first


def load_env():
    env = {}
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    env.update({k: v for k, v in os.environ.items() if k in env or k == "ANTHROPIC_API_KEY"})
    env.setdefault("POSTGRES_PASSWORD", "localdev")
    env.setdefault("N8N_OWNER_EMAIL", "admin@sadafprod.test")
    env.setdefault("N8N_OWNER_PASSWORD", "ChangeMe123")
    if not env.get("ANTHROPIC_API_KEY", "").startswith("sk-"):
        sys.exit("ANTHROPIC_API_KEY missing from .env")
    return env


def compose(*args, check=True):
    cmd = ["docker", "compose", *args]
    result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    if check and result.returncode != 0:
        sys.exit(f"failed: {' '.join(args[:3])}...\n{result.stderr}")
    return result.stdout


def wait_for_n8n():
    for _ in range(60):
        try:
            with urllib.request.urlopen(f"{N8N}/healthz", timeout=2) as r:
                if r.status == 200:
                    return
        except Exception:
            pass
        time.sleep(2)
    sys.exit("n8n did not come up on :5678")


def owner_missing():
    with urllib.request.urlopen(f"{N8N}/rest/settings", timeout=10) as r:
        return json.loads(r.read())["data"]["userManagement"]["showSetupOnFirstLoad"]


def create_owner(env):
    body = json.dumps({
        "email": env["N8N_OWNER_EMAIL"], "password": env["N8N_OWNER_PASSWORD"],
        "firstName": "Bookings", "lastName": "Admin",
    }).encode()
    req = urllib.request.Request(f"{N8N}/rest/owner/setup", data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
    for _ in range(15):  # n8n can answer /healthz a few seconds before this endpoint is ready
        try:
            urllib.request.urlopen(req, timeout=10)
            if not owner_missing():
                print(f"owner login created: {env['N8N_OWNER_EMAIL']}")
                return
        except urllib.error.HTTPError as e:
            if e.code == 400:  # "Instance owner already setup"
                print("owner login already exists")
                return
        time.sleep(2)
    sys.exit("could not create the n8n owner login")


def import_credentials(env):
    template = (ROOT / "credentials" / "credentials.template.json").read_text(encoding="utf8")
    filled = Template(template).substitute(env)
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf8") as f:
        f.write(filled)
        tmp = f.name
    try:
        compose("cp", tmp, "n8n:/tmp/credentials.json")
        compose("exec", "-T", "n8n", "n8n", "import:credentials", "--input=/tmp/credentials.json")
        print("credentials imported (Postgres, Mailpit SMTP, Anthropic key)")
    finally:
        compose("exec", "-T", "n8n", "rm", "-f", "/tmp/credentials.json", check=False)
        os.remove(tmp)


def import_workflows():
    compose("exec", "-T", "n8n", "n8n", "import:workflow", "--separate", "--input=/workflows")
    print("workflows imported from workflows/")
    for wid in WORKFLOW_IDS:
        compose("exec", "-T", "n8n", "n8n", "publish:workflow", f"--id={wid}")
    print("workflows published; restarting n8n so the webhooks register")
    compose("restart", "n8n")
    wait_for_n8n()
    wait_for_webhook()


def wait_for_webhook():
    """The editor answers before the webhooks are registered. Mailpit does not retry,
    so wait until the intake webhook answers. The test call is not addressed to the
    bookings inbox, so the workflow ignores it."""
    body = json.dumps({"ID": "setup-check", "To": [], "From": {}}).encode()
    for _ in range(30):
        req = urllib.request.Request(f"{N8N}/webhook/new-mail", data=body, method="POST",
                                     headers={"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req, timeout=5)
            print("intake webhook is live")
            return
        except Exception:
            time.sleep(2)
    sys.exit("intake webhook never came up")


if __name__ == "__main__":
    env = load_env()
    wait_for_n8n()
    import_credentials(env)
    import_workflows()
    # Owner login last: on the very first boot n8n can forget an owner created too early.
    create_owner(env)
    print(f"done. Editor: {N8N}  (login {env['N8N_OWNER_EMAIL']})   Inbox: http://localhost:8026")
