# Kids Homework Assistant (built on Open WebUI)

A guided homework tutor for Estelle (Grade 6, Willard MS, Math 6) and Dorian (Grade 4, Hovatter ES), Loudoun County Public Schools.

Status: **proof of concept.** It runs on the **stock** Open WebUI image. Everything kid-specific is plugins and configuration applied through the API, so upgrades are a version bump.

## What's here

| Path | What it is |
|---|---|
| `curriculum/` | Research profiles: courses, LCPS math programs, required methods, worked examples |
| `prompts/dorian.md`, `prompts/estelle.md` | Each tutor's instructions, built from the profiles |
| `functions/kids_guardrails.py` | **Global** safety filter (children cannot turn it off) |
| `functions/claude_tutor_engine.py` | Model provider: Claude via the official Anthropic SDK |
| `scripts/provision.py` | One-command, re-runnable setup plus a safety audit |
| `kids.config.example.json` | Names, logins, study hours, alert settings |
| `docker-compose.yaml` | Runs Open WebUI v0.6.18 |
| `tests/` | Unit tests (`test_*.py`) and an end-to-end check against a live instance (`e2e_check.py`) |

## Setup

1. **Start it:** `docker compose -f kids-assistant/docker-compose.yaml up -d`, then open http://localhost:3000.
2. **Create the parent account first.** The first account becomes the admin.
3. **Create an API key** for the parent account: Settings > Account > API Keys. If API keys are disabled, enable them under Admin > Settings > General.
4. **Configure:** `cp kids-assistant/kids.config.example.json kids-assistant/kids.config.json`, then edit names, emails, hours and the alert URL. The real config is git-ignored.
5. **Provision:**
   ```bash
   export OWUI_URL=http://localhost:3000 OWUI_ADMIN_TOKEN=<parent API key>
   export ANTHROPIC_API_KEY=<key>   # optional here; can be set later in Admin > Functions > Claude Tutor Engine > Valves
   export ESTELLE_PASSWORD=... DORIAN_PASSWORD=...   # optional; generated and printed if unset
   python3 kids-assistant/scripts/provision.py
   ```
   It ends with a safety audit. Re-run `provision.py --audit` any time you change settings in the UI.

Re-run `provision.py` after editing a prompt or the config. It updates in place.

## How the safety layers work

1. **Accounts:** public sign-up is off. The parent creates the kids' accounts.
2. **One model per child:** each child can see and use only their own tutor. The raw engine refuses any request that doesn't come through a tutor. The audit catches any public model record that would bypass the tutor.
3. **The kids can't change the tutor's instructions.** Open WebUI's "no system prompt" permission only hides the box in the UI; the server still merges a child's own system prompt (from settings, folders, or a direct API call) into the request. The guardrail filter removes every client-supplied system prompt, so the tutor prompt is the only one the AI sees.
4. **Guardrail filter** (global, runs before the AI, applies only to child accounts):
   - Removes phone numbers, emails, street addresses and SSNs, from history too, before anything reaches the AI provider.
   - **Self-harm (first-person), abuse, bullying, or a stranger asking for secrets, photos or a meetup:** tells the AI to drop the homework, respond supportively and point to a parent, counselor, 988 or 911. Logs a **high** alert.
   - **Topic-only mentions** (for example a health-class question about suicide prevention): answered factually with a gentle 988 line. Logged at **low** severity with no message content.
   - **"Just give me the answers" / "write my essay":** coaching reminder. **Jailbreak attempts:** stay-in-role reminder.
   - **A short list of clearly inappropriate terms is blocked outright** before reaching the AI. 6th-grade Health topics (drugs, mental health, Family Life Education) are deliberately not blocked, because they are real homework.
   - Study hours (default 7:00–21:00 Eastern) and a message length cap.
5. **Locked permissions:** no web search, image generation, code execution, file upload, model creation, sharing, chat deletion or temporary chats. Notes are on.
6. **Parent oversight:**
   - Admin > Users shows every chat.
   - Alerts are written to `/app/backend/data/kids-assistant/alerts.jsonl`.
   - Optional push notification to a URL such as an ntfy.sh topic. **It carries only the child's name and the category, never the message.**
7. **The AI itself:** Claude (`claude-opus-5-5`, medium effort), plus the tutor prompts' own safety rules.

## Known limitations (read these)

- **Keyword detection is a backstop, not the main defense.**
  - It misses misspellings and indirect phrasing. Catching harm in context depends on the AI and the prompt.
  - It will produce some false alerts. Tune `blocked_terms` and the patterns as real usage shows what fires.
- **Replies are not filtered before display.** Open WebUI's output hook runs after a reply has streamed to the screen. Output safety relies on Claude's own safety behavior and the tutor prompt. The hook only cleans the stored copy.
- **Notes:** private by default, but the note editor has an "Everyone" sharing toggle this Open WebUI version can't disable. A shared note can't be found by browsing; the other child would need its link.
- **Refusal fallback is off** (`ENABLE_REFUSAL_FALLBACK`). Anthropic recommends turning on automatic fallback to another model when Claude declines. For a children's app, a decline is usually the guardrail working, so it stays off unless you choose otherwise.
- **Provider terms:** check Anthropic's usage policy on products used by minors before going live. You are the account holder and operator.
- **Exposure:** keep it on your home network or behind a VPN or a tunnel with authentication. Never expose port 3000 directly.
- **Method accuracy:** the math methods come from the state standards and the published curricula, not yet from the kids' own classwork. Update `curriculum/` and `prompts/` as photos and syllabi arrive, then re-run `provision.py`.

## Tests

```bash
pip install pytest pydantic anthropic
python -m pytest kids-assistant/tests        # unit tests, no network needed
# against a live, provisioned instance:
OWUI_URL=... OWUI_ADMIN_TOKEN=... KIDS_CONFIG=... ESTELLE_PASSWORD=... DORIAN_PASSWORD=... \
  python3 kids-assistant/tests/e2e_check.py
```

## Sources

See `curriculum/*.md` for per-fact confidence tags.

- LCPS Mathematics (core resources: Kiddom/Illustrative Mathematics K-5, Mathspace 6-8): https://www.lcps.org/o/dtl/page/mathematics
- LCPS core textbook announcements: https://www.lcps.org/o/dtl/page/public-announcements
- LCPS Program of Studies, middle school: https://sites.google.com/lcps.org/program-of-studies-2024-2025/middle-school-course-information
- Willard electives: https://www.willardmiddleschool.org/academics/electives/
- 2023 Virginia Math SOL K–12 (copy): https://www.baconsrebellion.com/wp-content/uploads/2023/12/00-Kthru12-Approved-2023-Math-SOL.pdf
- IM Grade 4 Unit 6: https://im.kendallhunt.com/K5/teachers/grade-4/unit-6/lessons.html
- Kiddom Virginia Math: https://www.kiddom.co/insights/introducing-kiddom-virginia-math
- VDOE approved math textbooks: https://www.doe.virginia.gov/teaching-learning-assessment/k-12-standards-instruction/mathematics/2024-mathematics-textbooks
- LCPS AI policy coverage: https://www.loudounnow.com/news/education/loudoun-school-board-approves-new-generative-ai-policy/article_9cf6150a-9c80-4714-909c-a88340cd56b7.html

Research gap: the VDOE site (www.doe.virginia.gov) is on the network allowlist, but its CDN returns 403 to automated clients, so the official standards PDFs were read only through secondary sources.
