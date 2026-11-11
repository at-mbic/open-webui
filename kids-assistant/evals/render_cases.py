#!/usr/bin/env python3
"""Render cases.json to CASES.md for human review."""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
cases = json.loads((HERE / "cases.json").read_text())


def fence(text: str) -> str:
    longest = max((len(r) for r in text.split("\n") for r in [r] if set(r) == {"`"}), default=0)
    ticks = "`" * max(3, longest + 1)
    return f"{ticks}\n{text}\n{ticks}"


out = ["# Kids tutor test questions", "",
       f"{len(cases)} cases: {sum(c['kid'] == 'Dorian' for c in cases)} for Dorian (grade 4), "
       f"{sum(c['kid'] == 'Estelle' for c in cases)} for Estelle (grade 6). "
       "Each case lists what a good reply MUST do and MUST NOT do.", "",
       "| id | kid | tags |", "|---|---|---|"]
out += [f"| {c['id']} | {c['kid']} | {', '.join(c['tags'])} |" for c in cases]
for c in cases:
    out += ["", f"## {c['id']} · {c['kid']} · {', '.join(c['tags'])}", ""]
    for t in c["turns"]:
        out += [f"**{'Kid' if t['role'] == 'user' else 'Tutor (earlier turn)'}:**", "", fence(t["content"]), ""]
    out += ["**Must:**"] + [f"- {m}" for m in c["must"]]
    out += ["", "**Must not:**"] + [f"- {m}" for m in c["must_not"]]
    if c.get("note"):
        out += ["", f"_Note: {c['note']}_"]
(HERE / "CASES.md").write_text("\n".join(out) + "\n")
print(f"wrote CASES.md ({len(cases)} cases)")
