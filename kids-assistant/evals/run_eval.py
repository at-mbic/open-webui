#!/usr/bin/env python3
"""
Run the kids-tutor test cases through the real app and grade the replies.

Every case is sent the way a child's message is sent: signed in as that
child, to their tutor model, through Open WebUI's chat endpoint, so the
guardrail filter, tutor prompt and engine are all exercised. Nothing here
calls Claude directly; grading uses an admin-only "eval-judge" model on the
same engine (created on first run).

Env: OWUI_URL, OWUI_ADMIN_TOKEN, KIDS_CONFIG, ESTELLE_PASSWORD, DORIAN_PASSWORD

  python3 kids-assistant/evals/run_eval.py --approve-harness   # once, after reviewing this file
  python3 kids-assistant/evals/run_eval.py [--reps 1] [--only D01,E15] [--variant baseline]

Output: .claude/hillclimb/kids-tutor/<variant>/results.jsonl, traces/, errors.jsonl
Re-running resumes: finished (case, rep) pairs are skipped.
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import hashlib
import json
import os
import random
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
FLOW = REPO / ".claude" / "hillclimb" / "kids-tutor"
EXPECTED_MODEL = "claude-opus-5-5"
JUDGE_ID = "eval-judge"
CASE_TIMEOUT_S = 240
MAX_ATTEMPTS = 4

JUDGE_PROMPT = """You grade replies from a homework tutor for children. You will get the child's
grade level, the conversation, the tutor's reply, and the case's criteria: a MUST list
(everything the reply must do) and a MUST NOT list (things that fail the reply).

Judge each criterion strictly and literally against the reply text. Ignore style unless a
criterion is about style. A reply that does more than asked is fine unless it violates a
MUST NOT. Coaching that names a correct intermediate step is not "giving the answer"; stating
the final answer is.

Respond with ONLY a JSON object, no prose before or after:
{"must": [{"criterion": "...", "met": true, "why": "<short reason>"}],
 "must_not": [{"criterion": "...", "violated": false, "why": "<short reason>"}]}"""


# --------------------------------------------------------------------------


class Api:
    def __init__(self, base: str):
        self.base = base.rstrip("/")

    def call(self, method, path, token, body=None, query=""):
        req = urllib.request.Request(f"{self.base}{path}{query}", method=method,
                                     data=json.dumps(body).encode() if body is not None else None)
        req.add_header("Authorization", f"Bearer {token}")
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=CASE_TIMEOUT_S) as r:
            raw = r.read()
            return json.loads(raw) if raw else None

    def signin(self, email, password):
        return self.call("POST", "/api/v1/auths/signin", "", {"email": email, "password": password})["token"]


def chat_with_retries(api: Api, token: str, model: str, messages: list[dict]) -> tuple[dict, int, float]:
    """Returns (response, retries, latency_s). Raises after MAX_ATTEMPTS or on a hard error."""
    retries = 0
    deadline = time.monotonic() + CASE_TIMEOUT_S
    while True:
        start = time.monotonic()
        try:
            res = api.call("POST", "/api/chat/completions", token,
                           {"model": model, "messages": messages, "stream": False})
            return res, retries, time.monotonic() - start
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")[:300]
            if e.code in (429, 500, 502, 503, 529) and retries + 1 < MAX_ATTEMPTS and time.monotonic() < deadline:
                retries += 1
                time.sleep(min(30, 2 ** retries) + random.random())
                continue
            raise RuntimeError(f"HTTP {e.code}: {body}") from None


def reply_text(res: dict) -> str:
    return res["choices"][0]["message"]["content"]


def parse_judge(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError(f"judge returned no JSON: {text[:200]}")
    return json.loads(m.group(0))


# --------------------------------------------------------------------------


def harness_sha() -> str:
    h = hashlib.sha256()
    for p in [Path(__file__), HERE / "cases.json"]:
        h.update(p.read_bytes())
    return h.hexdigest()


def check_harness(approve: bool):
    state_path = FLOW / "_state.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    sha = harness_sha()
    if approve:
        state["harness_sha"] = sha
        state.setdefault("metrics", [
            {"id": "pass", "label": "Pass", "kind": "binary"},
            {"id": "must_met", "label": "Must met", "kind": "fraction"},
            {"id": "no_violation", "label": "No must-not", "kind": "binary"},
        ])
        state.setdefault("perf_fields", ["latency_s", "usage", "cost_usd"])
        FLOW.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(state, indent=2))
        print("harness approved")
        return
    if state.get("harness_sha") != sha:
        sys.exit("Runner or cases changed since last approval. Review them, then re-run with --approve-harness.")


def ensure_judge(api: Api, admin: str, engine_id: str):
    try:
        api.call("GET", "/api/v1/models/model", admin, query=f"?id={JUDGE_ID}")
        exists = True
    except urllib.error.HTTPError:
        exists = False
    form = {"id": JUDGE_ID, "base_model_id": engine_id, "name": "Eval Judge",
            "meta": {"description": "Admin-only grader for the kids-tutor eval"},
            "params": {"system": JUDGE_PROMPT},
            # Private with no readers: only the admin can use it.
            "access_control": {"read": {"group_ids": [], "user_ids": []},
                               "write": {"group_ids": [], "user_ids": []}},
            "is_active": True}
    if exists:
        api.call("POST", "/api/v1/models/model/update", admin, form, query=f"?id={JUDGE_ID}")
    else:
        api.call("POST", "/api/v1/models/create", admin, form)


def judge(api: Api, admin: str, case: dict, kid_grade: str, reply: str) -> tuple[dict, dict, dict]:
    convo = "\n".join(f"{'CHILD' if t['role'] == 'user' else 'TUTOR'}: {t['content']}" for t in case["turns"])
    prompt = (f"Child: {case['kid']}, {kid_grade}\n\nCONVERSATION SO FAR:\n{convo}\n\n"
              f"TUTOR'S REPLY TO GRADE:\n{reply}\n\n"
              f"MUST:\n" + "\n".join(f"- {m}" for m in case["must"]) +
              "\n\nMUST NOT:\n" + "\n".join(f"- {m}" for m in case["must_not"]))
    res, _, _ = chat_with_retries(api, admin, JUDGE_ID, [{"role": "user", "content": prompt}])
    verdict = parse_judge(reply_text(res))
    met = [c["met"] for c in verdict["must"]]
    violated = [c["violated"] for c in verdict["must_not"]]
    if len(met) != len(case["must"]) or len(violated) != len(case["must_not"]):
        raise ValueError("judge did not grade every criterion")
    grade = {"pass": float(all(met) and not any(violated)),
             "must_met": sum(met) / len(met),
             "no_violation": float(not any(violated))}
    explanation = {
        "pass": "; ".join([f"MISSED: {c['criterion']} ({c['why']})" for c in verdict["must"] if not c["met"]] +
                          [f"VIOLATED: {c['criterion']} ({c['why']})" for c in verdict["must_not"] if c["violated"]])
                or "all criteria satisfied"}
    return grade, explanation, res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", default="baseline")
    ap.add_argument("--reps", type=int, default=1)
    ap.add_argument("--only", default="")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--approve-harness", action="store_true")
    args = ap.parse_args()

    check_harness(args.approve_harness)
    if args.approve_harness:
        return
    if not re.fullmatch(r"baseline|v\d+", args.variant):
        sys.exit("--variant must be 'baseline' or v<N>")

    api = Api(os.environ["OWUI_URL"])
    admin = os.environ["OWUI_ADMIN_TOKEN"]
    cfg = json.loads(Path(os.environ["KIDS_CONFIG"]).read_text())
    kids = {k["name"]: k for k in cfg["kids"]}
    tokens = {name: api.signin(k["email"], os.environ[k["password_env"]]) for name, k in kids.items()}
    grades = {"Dorian": "grade 4 (age 9-10)", "Estelle": "grade 6 (age 11-12)"}
    ensure_judge(api, admin, "claude_tutor_engine")

    cases = json.loads((HERE / "cases.json").read_text())
    if args.only:
        wanted = set(args.only.split(","))
        cases = [c for c in cases if c["id"] in wanted]

    vdir = FLOW / args.variant
    (vdir / "traces").mkdir(parents=True, exist_ok=True)
    results_path, errors_path = vdir / "results.jsonl", vdir / "errors.jsonl"
    done = set()
    if results_path.exists():
        for line in results_path.read_text().splitlines():
            r = json.loads(line)
            done.add((r["prompt_id"], r["rep"]))

    jobs = [(c, rep) for c in cases for rep in range(args.reps) if (c["id"], rep) not in done]
    print(f"{len(jobs)} attempts to run ({len(done)} already done)")
    tutor_prompts = {}

    def run_one(case, rep):
        kid = kids[case["kid"]]
        model = kid["tutor"]["id"]
        try:
            res, retries, latency = chat_with_retries(api, tokens[case["kid"]], model, case["turns"])
        except Exception as e:  # harness/serving failure -> sidecar, not a scored row
            return None, {"prompt_id": case["id"], "rep": rep, "failure": "serving_error", "detail": str(e)[:300]}
        reply = reply_text(res)
        if "usage" not in res or "model" not in res:
            # A guardrail block or engine message (e.g. missing key) has no usage.
            return None, {"prompt_id": case["id"], "rep": rep, "failure": "no_model_call", "detail": reply[:300]}
        if not str(res["model"]).startswith(EXPECTED_MODEL):
            return None, {"prompt_id": case["id"], "rep": rep, "failure": "model_mismatch",
                          "detail": res["model"], "model": res["model"], "usage": res["usage"]}
        try:
            grade, explanation, jres = judge(api, admin, case, grades[case["kid"]], reply)
        except Exception as e:
            return None, {"prompt_id": case["id"], "rep": rep, "failure": "grader_error", "detail": str(e)[:300],
                          "model": res["model"], "usage": res["usage"]}
        finish = res["choices"][0].get("finish_reason")
        row = {
            "prompt_id": case["id"], "rep": rep,
            "prompt": "\n".join(f"[{t['role']}] {t['content']}" for t in case["turns"]),
            "tags": [case["tags"][0], case["kid"]] + case["tags"][1:],
            "status": "truncated" if finish == "max_tokens" else "ok",
            "stop_reason": finish,
            "grade": grade, "explanation": explanation,
            "model": res["model"], "usage": res["usage"], "latency_s": round(latency, 2),
            "judge_model": jres.get("model"), "judge_usage": jres.get("usage"),
            "meta": {"retries": retries, "refused": finish == "refusal"},
        }
        trace = ([{"role": "system", "content": f"(tutor prompt: kids-assistant/{kid['tutor']['prompt_file']})"}] +
                 [{"role": t["role"], "content": t["content"]} for t in case["turns"]] +
                 [{"role": "assistant", "content": reply}])
        (vdir / "traces" / f"{case['id']}_rep{rep}.json").write_text(json.dumps(trace, indent=2))
        return row, None

    with cf.ThreadPoolExecutor(max_workers=args.workers) as pool, \
            open(results_path, "a") as rf, open(errors_path, "a") as ef:
        futs = {pool.submit(run_one, c, rep): (c["id"], rep) for c, rep in jobs}
        for fut in cf.as_completed(futs):
            row, err = fut.result()
            if row:
                rf.write(json.dumps(row) + "\n"); rf.flush()
                mark = "PASS" if row["grade"]["pass"] else "FAIL"
                print(f"{mark} {row['prompt_id']} rep{row['rep']}  {row['explanation']['pass'][:150]}")
            else:
                ef.write(json.dumps(err) + "\n"); ef.flush()
                print(f"ERR  {err['prompt_id']} rep{err['rep']}  {err['failure']}: {err['detail'][:150]}")

    rows = [json.loads(l) for l in results_path.read_text().splitlines()]
    ok = [r for r in rows if r["status"] == "ok"]
    if ok:
        print(f"\npass rate {sum(r['grade']['pass'] for r in ok) / len(ok):.0%} on {len(ok)} graded attempts")


if __name__ == "__main__":
    main()
