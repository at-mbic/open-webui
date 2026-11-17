"""Runs inside the container on every start, after Open WebUI is up.

First start (no accounts yet): creates the parent (admin) account, generates
passwords for the parent and each child, prints them once to the container
log, and saves them to the data volume.

Every start: re-applies the kids' setup with provision.py (functions, tutors,
locked permissions, signup off) and runs the safety audit. Re-applying on
every start means an image upgrade picks up new prompts and guardrails, and
settings changed by hand in the admin UI are put back.

The admin token is minted locally from the instance's own signing key, so no
admin password is ever stored.
"""

from __future__ import annotations

import json
import os
import secrets
import sqlite3
import subprocess
import sys
import time
import urllib.request
import uuid
from pathlib import Path

import jwt  # PyJWT ships with Open WebUI

DATA = Path(os.environ.get("DATA_DIR", "/app/backend/data"))
DB = DATA / "webui.db"
KEY_FILE = Path(os.environ.get("WEBUI_SECRET_KEY_FILE", "/app/backend/.webui_secret_key"))
URL = f"http://127.0.0.1:{os.environ.get('PORT', '8080')}"
CONFIG = Path(os.environ.get("KIDS_CONFIG", "/app/kids-assistant/kids.config.json"))
PROVISION = Path("/app/kids-assistant/scripts/provision.py")
CREDS = DATA / "kids-assistant" / "first-boot-passwords.txt"


def say(msg: str):
    print(f"[study-buddy] {msg}", flush=True)


def user_count() -> int:
    with sqlite3.connect(DB) as db:
        return db.execute('select count(*) from "user"').fetchone()[0]


def admin_id() -> str:
    with sqlite3.connect(DB) as db:
        row = db.execute(
            "select id from \"user\" where role = 'admin' order by created_at limit 1"
        ).fetchone()
    if not row:
        raise SystemExit("no admin account found")
    return row[0]


def signup_parent(email: str, password: str):
    req = urllib.request.Request(
        f"{URL}/api/v1/auths/signup",
        data=json.dumps({"name": "Parent", "email": email, "password": password}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        role = json.load(r).get("role")
    if role != "admin":
        raise SystemExit(f"parent account was created with role {role!r}, expected admin")


def mint_token(uid: str) -> str:
    secret = os.environ.get("WEBUI_SECRET_KEY") or KEY_FILE.read_text().strip()
    payload = {"id": uid, "exp": int(time.time()) + 600, "jti": str(uuid.uuid4())}
    return jwt.encode(payload, secret, algorithm="HS256")


def show_logins(passwords: dict):
    CREDS.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{who:<8} {email:<26} {pw}" for who, (email, pw) in passwords.items()]
    CREDS.write_text("Study Buddy first-start logins. Change these, then delete this file.\n\n"
                     + "\n".join(lines) + "\n")
    CREDS.chmod(0o600)
    bar = "=" * 64
    print(f"\n{bar}\n STUDY BUDDY LOGINS (shown once - write them down)\n{bar}", flush=True)
    for line in lines:
        print(" " + line, flush=True)
    print(f"{bar}\n Also saved in the container at {CREDS}\n{bar}\n", flush=True)


def main():
    cfg = json.loads(CONFIG.read_text())
    env = dict(os.environ, OWUI_URL=URL, KIDS_CONFIG=str(CONFIG))

    fresh = user_count() == 0
    if fresh:
        say("first start: creating accounts")
        parent_email = os.environ.get("PARENT_EMAIL", "parent@family.local")
        passwords = {"Parent": (parent_email, os.environ.get("PARENT_PASSWORD") or secrets.token_urlsafe(12))}
        for kid in cfg["kids"]:
            var = kid.get("password_env", "")
            pw = os.environ.get(var) or secrets.token_urlsafe(9)
            env[var] = pw
            passwords[kid["name"]] = (kid["email"], pw)
        signup_parent(*passwords["Parent"])
        show_logins(passwords)

    env["OWUI_ADMIN_TOKEN"] = mint_token(admin_id())
    result = subprocess.run([sys.executable, str(PROVISION)], env=env)

    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
