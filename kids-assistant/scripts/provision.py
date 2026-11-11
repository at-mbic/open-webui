#!/usr/bin/env python3
"""
Provision the Kids Homework Assistant on a running Open WebUI instance.

Idempotent: safe to re-run after editing prompts, valves or config.

Environment:
  OWUI_URL            Base URL, e.g. http://localhost:3000
  OWUI_ADMIN_TOKEN    Admin API key or JWT (Settings > Account)
  ANTHROPIC_API_KEY   Optional; stored in the Claude Tutor Engine valves
  KIDS_CONFIG         Path to config JSON (default: kids-assistant/kids.config.json)

Each child's password is read from the env var named in the config
(e.g. ESTELLE_PASSWORD). If unset, a random one is generated and printed once.

Usage:
  python3 kids-assistant/scripts/provision.py            # apply
  python3 kids-assistant/scripts/provision.py --audit    # safety audit only
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # kids-assistant/

GUARDRAILS_ID = "kids_guardrails"
ENGINE_ID = "claude_tutor_engine"
GROUP_NAME = "Kids"

# Locked-down permissions for child accounts. Open WebUI merges default and
# group permissions with OR ("most permissive wins"), so BOTH the defaults
# and the Kids group are set to this.
LOCKED_PERMISSIONS = {
    "workspace": {"models": False, "knowledge": False, "prompts": False, "tools": False},
    "sharing": {"public_models": False, "public_knowledge": False, "public_prompts": False, "public_tools": False},
    "chat": {
        "controls": False,        # hides advanced params UI
        "system_prompt": False,   # UI only - server-side stripping is done by the guardrail filter
        "file_upload": False,
        "delete": False,          # parent can always review history
        "edit": True,
        "share": False,
        "export": False,
        "stt": True,
        "tts": True,
        "call": False,
        "multiple_models": False,
        "temporary": False,       # no unsaved/unreviewable chats
        "temporary_enforced": False,
    },
    "features": {
        "direct_tool_servers": False,
        "web_search": False,
        "image_generation": False,
        "code_interpreter": False,
        "notes": True,            # the kids' self-notes area
    },
}


class Api:
    def __init__(self, base: str, token: str):
        self.base = base.rstrip("/")
        self.token = token

    def call(self, method: str, path: str, body=None, query: dict | None = None, ok404=False):
        url = f"{self.base}{path}"
        if query:
            url += "?" + urllib.parse.urlencode(query)
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", f"Bearer {self.token}")
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                raw = r.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            if ok404 and e.code in (400, 401, 404):
                return None
            detail = e.read().decode(errors="replace")[:500]
            raise SystemExit(f"API error {e.code} on {method} {path}: {detail}")

    def get(self, path, **kw):
        return self.call("GET", path, **kw)

    def post(self, path, body=None, **kw):
        return self.call("POST", path, body=body if body is not None else {}, **kw)


def log(msg: str):
    print(f"  - {msg}")


# --------------------------------------------------------------------------


def configure_admin(api: Api):
    cfg = api.get("/api/v1/auths/admin/config")
    cfg.update({
        "ENABLE_SIGNUP": False,
        "DEFAULT_USER_ROLE": "pending",
        "ENABLE_COMMUNITY_SHARING": False,
        "ENABLE_NOTES": True,
        "ENABLE_CHANNELS": False,
        "ENABLE_USER_WEBHOOKS": False,
    })
    api.post("/api/v1/auths/admin/config", cfg)
    log("signup off, community sharing off, channels off, notes on")
    api.post("/api/v1/users/default/permissions", LOCKED_PERMISSIONS)
    log("default user permissions locked down")


def upsert_function(api: Api, fid: str, name: str, path: Path, description: str):
    content = path.read_text()
    form = {"id": fid, "name": name, "content": content, "meta": {"description": description}}
    existing = api.get(f"/api/v1/functions/id/{fid}", ok404=True)
    if existing:
        api.post(f"/api/v1/functions/id/{fid}/update", form)
        log(f"updated function {fid}")
    else:
        api.post("/api/v1/functions/create", form)
        existing = {"is_active": False, "is_global": False}
        log(f"created function {fid}")
    return api.get(f"/api/v1/functions/id/{fid}")


def ensure_flag(api: Api, fid: str, current: bool, endpoint: str, label: str):
    if not current:
        api.post(f"/api/v1/functions/id/{fid}/{endpoint}")
        log(f"{fid}: {label} on")


def set_valves(api: Api, fid: str, updates: dict):
    valves = api.get(f"/api/v1/functions/id/{fid}/valves", ok404=True) or {}
    valves.update({k: v for k, v in updates.items() if v is not None})
    api.post(f"/api/v1/functions/id/{fid}/valves/update", valves)


def install_functions(api: Api, cfg: dict):
    g = upsert_function(
        api, GUARDRAILS_ID, "Kids Guardrails",
        ROOT / "functions" / "kids_guardrails.py",
        "Global safety filter for child accounts",
    )
    ensure_flag(api, GUARDRAILS_ID, g.get("is_active"), "toggle", "active")
    ensure_flag(api, GUARDRAILS_ID, g.get("is_global"), "toggle/global", "global")
    gv = cfg.get("guardrails", {})
    set_valves(api, GUARDRAILS_ID, {
        "timezone": gv.get("timezone"),
        "study_hours_start": gv.get("study_hours_start"),
        "study_hours_end": gv.get("study_hours_end"),
        "alert_webhook_url": gv.get("alert_webhook_url"),
        "alert_min_severity": gv.get("alert_min_severity"),
        "allow_images": gv.get("allow_images"),
    })
    log("guardrail valves set")

    e = upsert_function(
        api, ENGINE_ID, "Claude Tutor Engine",
        ROOT / "functions" / "claude_tutor_engine.py",
        "Claude via the Anthropic SDK; only usable through a tutor model",
    )
    ensure_flag(api, ENGINE_ID, e.get("is_active"), "toggle", "active")
    ev = cfg.get("engine", {})
    set_valves(api, ENGINE_ID, {
        "ANTHROPIC_API_KEY": os.environ.get("ANTHROPIC_API_KEY") or None,
        "MODEL": ev.get("model"),
        "EFFORT": ev.get("effort"),
    })
    log("engine valves set" + (" (API key from env)" if os.environ.get("ANTHROPIC_API_KEY") else " (no API key in env; set it in the admin UI)"))


def find_user(api: Api, email: str):
    res = api.get("/api/v1/users/", query={"query": email})
    users = res.get("users", res) if isinstance(res, dict) else res
    for u in users or []:
        if u.get("email", "").lower() == email.lower():
            return u
    return None


def ensure_kid(api: Api, kid: dict) -> str:
    user = find_user(api, kid["email"])
    if user:
        log(f"user {kid['email']} exists")
        return user["id"]
    pw = os.environ.get(kid.get("password_env", ""), "")
    generated = not pw
    if generated:
        pw = secrets.token_urlsafe(9)
    res = api.post("/api/v1/auths/add", {
        "name": kid["name"], "email": kid["email"], "password": pw, "role": "user",
    })
    log(f"created user {kid['email']}" + (f" with generated password: {pw}  <- write this down" if generated else ""))
    return res["id"]


def ensure_group(api: Api, user_ids: list[str]) -> str:
    groups = api.get("/api/v1/groups/") or []
    group = next((g for g in groups if g.get("name") == GROUP_NAME), None)
    if not group:
        group = api.post("/api/v1/groups/create", {
            "name": GROUP_NAME, "description": "Child accounts", "permissions": LOCKED_PERMISSIONS,
        })
        log("created Kids group")
    api.post(f"/api/v1/groups/id/{group['id']}/update", {
        "name": GROUP_NAME, "description": "Child accounts",
        "permissions": LOCKED_PERMISSIONS, "user_ids": user_ids,
    })
    log("Kids group permissions locked, members set")
    return group["id"]


def upsert_tutor(api: Api, kid: dict, user_id: str):
    tutor = kid["tutor"]
    form = {
        "id": tutor["id"],
        "base_model_id": ENGINE_ID,
        "name": tutor["name"],
        "meta": {
            "description": tutor.get("description", ""),
            "profile_image_url": "/static/favicon.png",
            "capabilities": {"vision": False, "file_upload": False, "web_search": False,
                             "image_generation": False, "code_interpreter": False, "citations": False},
            "suggestion_prompts": [{"content": s} for s in tutor.get("suggestions", [])],
        },
        "params": {"system": (ROOT / tutor["prompt_file"]).read_text()},
        # Private to this one child: no group, just her/his user id.
        "access_control": {"read": {"group_ids": [], "user_ids": [user_id]},
                           "write": {"group_ids": [], "user_ids": []}},
        "is_active": True,
    }
    if api.get("/api/v1/models/model", query={"id": tutor["id"]}, ok404=True):
        api.post("/api/v1/models/model/update", form, query={"id": tutor["id"]})
        log(f"updated tutor {tutor['id']}")
    else:
        api.post("/api/v1/models/create", form)
        log(f"created tutor {tutor['id']}")
    # Make it the child's default model.
    # (Open WebUI has no admin API for another user's default model; the
    # tutor is the only model they can see, so it is selected automatically.)


def audit(api: Api, kid_ids: set[str]) -> int:
    """Report anything that would let a child reach an unfiltered or unintended model."""
    problems = 0
    print("\nSafety audit")
    for m in api.get("/api/v1/models/base") or []:
        if m.get("access_control") is None and m.get("is_active", True):
            problems += 1
            print(f"  ! base model record '{m['id']}' is PUBLIC (access_control=None). "
                  f"Children can select it, bypassing the tutor prompt. Fix: Admin > Models > "
                  f"'{m['id']}' > set to Private, or delete the record.")
    for m in api.get("/api/v1/models/") or []:
        ac = m.get("access_control")
        if ac is None:
            problems += 1
            print(f"  ! custom model '{m['id']}' is PUBLIC.")
            continue
        readers = set(ac.get("read", {}).get("user_ids", []))
        if ac.get("read", {}).get("group_ids") and m.get("base_model_id") != ENGINE_ID:
            print(f"  ? custom model '{m['id']}' is shared with groups; check it is intended.")
        if (readers & kid_ids) and m.get("base_model_id") != ENGINE_ID:
            problems += 1
            print(f"  ! child can read '{m['id']}', which does not use the tutor engine.")
    fns = {f["id"]: f for f in api.get("/api/v1/functions/") or []}
    g = fns.get(GUARDRAILS_ID)
    if not g or not g.get("is_active") or not g.get("is_global"):
        problems += 1
        print("  ! Kids Guardrails filter is not installed, active AND global.")
    perms = api.get("/api/v1/users/default/permissions")
    for section, values in LOCKED_PERMISSIONS.items():
        for k, v in values.items():
            if perms.get(section, {}).get(k) != v:
                problems += 1
                print(f"  ! default permission {section}.{k} is {perms.get(section, {}).get(k)}, expected {v}")
    cfg = api.get("/api/v1/auths/admin/config")
    if cfg.get("ENABLE_SIGNUP"):
        problems += 1
        print("  ! public signup is enabled")
    print("  OK - no problems found" if problems == 0 else f"  {problems} problem(s) found")
    return problems


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--audit", action="store_true", help="Run the safety audit only")
    args = ap.parse_args()

    url = os.environ.get("OWUI_URL")
    token = os.environ.get("OWUI_ADMIN_TOKEN")
    if not url or not token:
        sys.exit("Set OWUI_URL and OWUI_ADMIN_TOKEN")
    cfg_path = Path(os.environ.get("KIDS_CONFIG", ROOT / "kids.config.json"))
    if not cfg_path.exists():
        sys.exit(f"Missing {cfg_path}. Copy kids.config.example.json and edit it.")
    cfg = json.loads(cfg_path.read_text())
    api = Api(url, token)

    if args.audit:
        ids = {u["id"] for k in cfg["kids"] if (u := find_user(api, k["email"]))}
        sys.exit(1 if audit(api, ids) else 0)

    print("Instance settings"); configure_admin(api)
    print("Functions"); install_functions(api, cfg)
    print("Accounts")
    kid_ids = {k["email"]: ensure_kid(api, k) for k in cfg["kids"]}
    ensure_group(api, list(kid_ids.values()))
    print("Tutors")
    for k in cfg["kids"]:
        upsert_tutor(api, k, kid_ids[k["email"]])
    sys.exit(1 if audit(api, set(kid_ids.values())) else 0)


if __name__ == "__main__":
    main()
