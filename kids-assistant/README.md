# Study Buddy (built on Open WebUI)

A guided homework tutor for Estelle (Grade 6, Willard MS, Math 6) and Dorian (Grade 4, Hovatter ES), Loudoun County Public Schools.

Status: **proof of concept.** It ships as one container: the stock Open WebUI image plus the kids' tutors, guardrails and settings, applied automatically every time it starts. Nothing is installed on your computer except Docker Desktop.

## What's here

| Path | What it is |
|---|---|
| `curriculum/` | Research profiles: courses, LCPS math programs, required methods, worked examples |
| `prompts/dorian.md`, `prompts/estelle.md` | Each tutor's instructions, built from the profiles |
| `functions/kids_guardrails.py` | **Global** safety filter (children cannot turn it off) |
| `functions/claude_tutor_engine.py` | Model provider: Claude via the official Anthropic SDK |
| `scripts/provision.py` | One-command, re-runnable setup plus a safety audit |
| `kids.config.example.json` | Names, logins, study hours, alert settings |
| `docker/` | The Study Buddy image: `Dockerfile`, start script, first-start setup |
| `.github/workflows/study-buddy-image.yml` | Builds the image and stores it as a private GitHub package |
| `docker-compose.yaml` | Developer setup: stock Open WebUI, provisioned from your own machine |
| `tests/` | Unit tests (`test_*.py`) and an end-to-end check against a live instance (`e2e_check.py`) |

## Setup in Docker Desktop

You need only Docker Desktop. No code, Python or files go on your computer; everything lives in the container and its storage volume. Deleting both in Docker Desktop removes every trace.

1. **Sign in to GitHub's registry once.** The image is a private package. Create a GitHub token with only the `read:packages` scope (GitHub > Settings > Developer settings > Personal access tokens (classic)). In Docker Desktop, open the terminal (bottom bar, **Terminal**) and run:
   ```
   docker login ghcr.io -u <your GitHub username>
   ```
   Paste the token when asked for a password.
2. **Start Study Buddy:**
   ```
   docker run -d --name study-buddy --restart unless-stopped -p 127.0.0.1:3000:8080 -v study-buddy-data:/app/backend/data ghcr.io/<owner>/study-buddy:latest
   ```
   It now shows under **Containers** in Docker Desktop. Stop, start and delete it from there.
3. **Get the logins.** Click the container, open **Logs**, and find the `STUDY BUDDY LOGINS` box (about a minute after the first start). It is printed once. A copy is saved in the container at `/app/backend/data/kids-assistant/first-boot-passwords.txt` (**Files** tab). Change the passwords, then delete that file.
4. **Add the Anthropic API key.** Open http://localhost:3000, log in as Parent, then Admin Panel > Functions > Claude Tutor Engine > gear icon > `ANTHROPIC_API_KEY`. It is stored in the container's volume.
5. **Check it.** The log ends with `Safety audit ... OK` and `ready`. If setup or the audit ever fails, the container **stops itself** rather than run unprotected. The log says why.

**Every start** re-applies the tutors, guardrails and locked-down permissions, then re-runs the safety audit. Changes made by hand in the admin UI that loosen the lockdown are put back.

**Updating:** pull the new image, delete the container (not the volume), and run step 2 again. Accounts, chats, notes and the API key are kept in the `study-buddy-data` volume.

**Only reachable from this computer.** `127.0.0.1:3000` means other devices on your network can't open it. Letting the kids use their own devices needs a deliberate change. Don't just switch to `-p 3000:8080`, which opens it to everyone on your network.

## Developer setup (provision from your own machine)

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
- **First start, Docker Desktop:** sign-up is open for the few seconds between the server starting and the parent account being created. Port 3000 is bound to this computer only, so nothing else can reach it in that window.
- **First-start passwords** are printed in the container log and saved in a file in the volume. Anyone with access to Docker Desktop on that computer can read both. Change the passwords and delete the file.
- **The image contains the kids' names, schools, grades and tutor prompts.** Keep the repository and its package **private**.
- **Method accuracy:** the math methods come from the state standards and the published curricula, not yet from the kids' own classwork. Update `curriculum/` and `prompts/` as photos and syllabi arrive, then rebuild the image (or re-run `provision.py` in the developer setup).

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
