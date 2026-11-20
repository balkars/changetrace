# ChangeTrace — presenter script (25–30 minutes)

What to say, what to do, and what the room should see, minute by minute. Use it live and as the shot list for the recording.

- **Say** lines are a guide. Put them in your own words; keep the facts.
- **Do** lines are exact actions. Commands match `docs/demo/meeting-script.md`, which is the step-by-step runbook behind this script.
- **Screen** lines say what should be visible. If the screen doesn't match, use the fallback at the end.

## Before you start (10 minutes before)

Run the checklist in `docs/demo/meeting-script.md` → *Before the meeting*: reset the demo, load `demo-env.ps1` in all three terminals, `gh auth status`, open the demo repo's Pull requests and Actions tabs, cue the backup recording.

Also, found in the dry run:

- **Dev A's assistant:** the plan is Claude Code. If `claude` can't log in, use Copilot for Dev A too — the rehearsal ran both developers on Copilot and every step worked; just say "Dev A and Dev B both use Copilot here, but the skill works the same in Claude Code and Codex."
- **Log in to both assistants the day before.** Run `claude` once and complete login (the CLI on this laptop reported "OAuth session expired"). Run `copilot` once and complete login.
- **Trust the demo folders in Copilot** so it loads them without a warning: start `copilot` in `demo-run\devB` once and choose to trust the folder.
- **Copilot asks before each shell command.** When it asks to run `ct …`, choose "approve for this session" so later `ct` calls don't interrupt the story. Approve `python -m pytest` the same way.
- **Claude Code asks before edits and commands.** Approve `ct` for the session on the first prompt.

Windows to arrange, left to right:

| Window | Shows |
|---|---|
| Proposal page (`changetrace_proposal.html`) | Problem and design |
| Dev A terminal | `demo-run\devA`, Claude Code |
| Dev B terminal | `demo-run\devB`, Copilot CLI |
| Browser | GitHub demo repo: PR, Actions, Environments |

Font size: terminals at 16pt or larger. Close notifications.

## Timeline

| Time | Section | Minutes |
|---|---|---|
| 0:00 | 1. Opening | 1 |
| 0:01 | 2. The problem | 4 |
| 0:05 | 3. What already exists, and what we found | 3 |
| 0:08 | 4. How ChangeTrace works | 2 |
| 0:10 | 5. Live demo | 13 |
| 0:23 | 6. What's built, what's next | 3 |
| 0:26 | 7. The ask, then questions | 2 + Q&A |

If you are running long, shorten section 3 to one sentence and skip demo step 5f (history).

---

## 1. Opening — 0:00 (1 min)

**Screen:** proposal page, top diagram ("How context moves with code").

**Say:**
> "Our assistants now write a lot of our code. They also work out *why* — what was tried, what was ruled out, what might break. Today that reasoning stays on one laptop. I want to show you a small tool that makes it travel with the code, and then I'll ask for one decision."

---

## 2. The problem — 0:01 (4 min)

**Do:** scroll the proposal to *01 · Problem*.

**Say:**
> "Here's a story that happens all the time. Dev A finds failed jobs recover slowly. With the assistant, they trace it to a two-second retry delay and change it from 2 to 0. Tests pass, it merges, it deploys to dev."
>
> "Two weeks later Dev B sees bursts of retries hammering the payments API. The obvious fix: put the delay back to 2. Their assistant does it in seconds. And the original slow-recovery bug is back — nobody remembers why it was 0."
>
> "The code moved. The reasoning stayed in Dev A's local session. The commit message says 'retry immediately'. It doesn't say what breaks if you undo it."

**Do:** point at the four boxes: *Local AI session → Code + short commit → Shared dev environment → Reasoning missing*.

**Say:**
> "What we lose: the original problem, the alternatives that didn't work, the assumptions, and the warning for the next person. What it costs: repeated investigations, regressions, pinging people who are busy or gone."
>
> "So the design rule is simple: the reasoning is written when the change is made, it lives in the repo next to the code, and it's checked at the moment someone is about to undo it."

---

## 3. What already exists, and what we found — 0:05 (3 min)

**Do:** scroll to *02 · Existing projects*.

**Say:**
> "We didn't want to build this if it exists. Two open-source projects are close."
>
> "Trail-Code stores 'learnings' as Markdown in the repo and has a `trail check` command. I installed it and ran exactly our retry story. It caught Dev B's revert for some wordings of the note — but when the note said 'set the default **from 2 to 0**', it reported the revert as *following* the note. Same with 'must be 0, not 2'. It pulls numbers out of sentences, so the result depends on how someone happened to phrase it. It also writes into your global Claude settings and sends usage stats by default."
>
> "Agent Mem Vault keeps decisions in Obsidian with good lifecycle fields — active, superseded — but it doesn't run on Windows and isn't linked to code files."
>
> "So we took the good ideas — the note layout from one, the lifecycle from the other — and built a small tool where the check doesn't depend on wording at all."

---

## 4. How ChangeTrace works — 0:08 (2 min)

**Do:** scroll to *05 · Agent Skill and CLI*, the repository layout.

**Say:**
> "Three pieces."
>
> "One: a decision record. A Markdown file in `.context/decisions/`, reviewed and committed with the code. Besides the prose, it stores a *guard*: this setting, in this file, should be this value."
>
> "Two: a command-line tool, `ct`. `ct why` explains a setting. `ct check` compares your change with every active guard. It's an exact comparison — no AI in the check — so it gives the same answer every time."
>
> "Three: one shared skill file that tells any assistant — Claude Code, Copilot, Codex — when to look things up, when to check, and when to draft a record. For Claude Code there's also a project hook, so the check runs after every edit even if the assistant forgets."
>
> "GitHub, Slack and Obsidian are views on top. If they're down, everything still works from the clone."

---

## 5. Live demo — 0:10 (13 min)

**Say:**
> "Let's run the story for real. Two clones of the same repo on this laptop — think of them as two developers' machines. Dev A uses Claude Code, Dev B uses Copilot CLI. The repo, the pull request and the deployment are real."

### 5a. Dev A fixes slow recovery — 0:11 (3 min)

**Do (Dev A terminal):** `claude`, then type exactly:
> Failed jobs take too long to recover. Find why and fix it.

**Screen:** the assistant reads the skill, runs `ct why RETRY_DELAY_SECONDS` → no records, changes `RETRY_DELAY_SECONDS` from 2 to 0, runs the tests and `ct check`, and says *"No decision records covered this setting … If you want one, I'll show you a draft first."*

**Say while it works:**
> "Notice it looked first — nothing recorded for this setting yet, so nothing to protect."

**Do:** type exactly:
> Yes, draft the decision record. Mention that immediate retries could burst against a downstream service that is down.

**Screen:** a draft with Problem, Decided, Tried and ruled out, Assumptions, **Watch out** ("Immediate retries can burst against a downstream service that is down…"), Evidence — and the question "Should I run `ct capture --from-diff` with this draft and commit it?"

**Say:**
> "This is the *why*, written while the knowledge is fresh. I review it like any other change."

**Do:** answer `yes`. Approve the `ct capture` and `git commit` commands when asked.

**Screen:**
```
Saved CTX-001 → .context/decisions/CTX-001-immediate-retry-for-failed-jobs.md
```

**Do:** open the record file briefly (or `type .context\decisions\CTX-001-*.md`). Point at `guards:` — `RETRY_DELAY_SECONDS`, expect `0`, previous `2`.

**Say:**
> "Prose for humans, and one structured line the tool can check. It's committed in the same commit as the code."

**Do:** push and open the PR (commands in the runbook, step 1).

### 5b. Review — 0:14 (1.5 min)

**Do:** switch to the browser → the PR.

**Screen:** a ChangeTrace comment (this is the dry-run output):
```
### ChangeTrace
1 linked decision · 0 conflicts
- i CTX-001 Immediate retry for failed jobs — new decision
  - Decided: Default RETRY_DELAY_SECONDS is 0, so a failed job retries immediately.
  - Watch out: Restoring 2 brings back slow recovery. Immediate retries can burst against an unavailable downstream dependency.
```

**Say:**
> "The reviewer gets the reasoning without asking Dev A. So does the team channel."

### 5c. Merge and deploy to dev — 0:15 (1.5 min)

**Do:** merge (runbook step 3). Switch to Actions; let `deploy-dev` run.

**Say while it runs (~40s):**
> "Merging deploys to our dev environment. The deploy step here is a stand-in that runs the tests — this is where our real deploy would go."

**Screen:** GitHub shows a `dev` deployment. Open the run's summary (or the `ct deploy report` step log): *Deployed … to dev (run N) · PRs: #1 … · Decision records: CTX-001 …*. Note the run number N — you need it in 5d.

### 5d. Something goes wrong on dev — 0:17 (1 min)

**Do (Dev A terminal):** record the observation (runbook step 4) and push it.

**Screen:** `Saved OBS-001 → .context/observations/OBS-001-request-burst-on-dev.md`

**Say:**
> "On dev we saw retry bursts against the payments API. That's recorded too — as an observation linked to the decision, not by editing the decision. History stays honest."

### 5e. Dev B wants the old value back — 0:18 (3.5 min) — **the key moment**

**Do (Dev B terminal):** `git pull`, `copilot`, then type exactly:
> Retries are hammering the payments API. Set RETRY_DELAY_SECONDS back to 2.

**Screen:** the assistant reads the skill, runs `ct why RETRY_DELAY_SECONDS`, and stops **without editing anything**. In the dry run Copilot replied (abridged):
```
I haven't edited anything. Setting RETRY_DELAY_SECONDS back to 2 conflicts with an active decision record.

This edit conflicts with CTX-001, "Immediate retry for failed jobs".
- Decided: default RETRY_DELAY_SECONDS is 0, so a failed job retries immediately.
- Why: failed jobs waited 2 seconds before the first retry, slowing recovery.
- Watch out: Restoring 2 brings back slow recovery. It also warns that immediate retries
  can burst against an unavailable downstream dependency — which matches the payments
  API problem you're seeing (`ct why` shows OBS-001, a request burst on dev).
- Evidence: commit …, tests/test_retry.py::test_recovers_without_delay
- Alternatives that keep CTX-001 intact:
  - set RETRY_DELAY_SECONDS=2 via the environment for the payments path only
  - add backoff or a retry cap for payments calls

Do you want me to try one of these alternatives, or override CTX-001 anyway?
```

**Pause here. Let the room read it.** Point at three things: *"I haven't edited anything"*, the Watch out, and OBS-001 — the assistant connected Dev B's symptom to the warning Dev A wrote.

**Say:**
> "This is the whole point. Different developer, different machine, different assistant — and Dev A isn't in the room. The tool knew, because the reasoning travelled with the code. And it doesn't block: it explains, and the developer decides."

**Do:** type exactly:
> Keep CTX-001. Add bounded exponential backoff after the first immediate retry instead.

**Screen:** the assistant edits `worker/config.py` (adds `RETRY_BACKOFF_BASE_SECONDS` and `RETRY_BACKOFF_MAX_SECONDS`, leaves `RETRY_DELAY_SECONDS` at 0), `worker/retry.py` and a test, then shows a draft record *"Bounded exponential backoff after first immediate retry"* and asks for a yes before saving it.

**Do:** answer `yes`.

**Screen:** `Saved CTX-002 → .context/decisions/CTX-002-…` and `ct check` → `no conflicts`.

**Say:**
> "Dev B kept Dev A's fix and solved their own problem on top of it — and wrote down why, for the next person."

**If you want to show the override path instead** (optional, adds a minute): answer "override CTX-001 anyway". The assistant drafts CTX-002 that supersedes CTX-001; after your yes it runs `ct supersede`, and `ct why` then shows CTX-002 current and CTX-001 superseded.

**If the assistant edits without asking:** run `ct check --file worker/config.py` yourself (runbook step 5) — it exits 1 and names CTX-001. Say: "The assistant should have stopped; the check itself is deterministic and catches it either way." With Claude Code the project hook shows this automatically after the edit.

### 5f. Ask "why?" later — 0:21.5 (1.5 min)

**Do (Dev B terminal):**
```powershell
ct explain worker/config.py
```
(Use `explain` on the file, not `why` on the one setting: CTX-002 is about the new backoff settings, so `ct why RETRY_DELAY_SECONDS` shows only CTX-001.)

**Screen:** both decisions for the file, current, with live evidence (rehearsal output):
```
CTX-002 · active · Dev B · … — Bounded exponential backoff after first immediate retry
  Decided: Keep the first retry immediate. From the second retry, back off exponentially …
CTX-001 · active · Dev A · … — Retry failed jobs immediately by default
  Evidence: commit 8aa6865 · PR #1 · dev deploy 067194e · …
  Observed: OBS-001 · dev · deployment 3 — Request burst on dev
``` If Dev B overrode, it shows (dry-run output):
```
CTX-002 · active · Dev B · … — Bounded exponential backoff for retries
  Chain: CTX-001 → CTX-002
  Decided: Keep the first retry immediate, then back off exponentially …
CTX-001 · superseded · Dev A · … — Immediate retry for failed jobs
  Chain: CTX-001 → CTX-002
  Evidence: commit … · PR #1 · dev deploy …
  Observed: OBS-001 · dev · deployment 1 — Request burst on dev
```
Then `ct explain worker/config.py` lists both CTX-001 and CTX-002 for the file.

**Say:**
> "Six months from now, someone opens this file. One command gives the whole story: what we decided, what replaced it, why, and the evidence."

Optional if time allows: `ct history --key RETRY_DELAY_SECONDS`.

### 5g. Optional extras (only if built and time allows)

- Obsidian: open the generated vault — the decision chain, the observation, and a second service side by side.

---

## 6. What's built, what's next — 0:23 (3 min)

**Do:** scroll the proposal to *08 · Implementation*.

**Say:**
> "What you saw is built and tested — about 195 automated tests. The decision records, the check, the skill, the Claude hook, the GitHub PR and deploy workflows. Slack notifications for PRs and deployments are built too; we'll connect them during the pilot."
>
> "What's next, in order: connecting Slack, the cross-repo Obsidian view, and a Slack 'why' bot; then support for the languages and config formats our real services use — today it reads Python, YAML, JSON, TOML and .env."
>
> "Risks we designed for: wrong AI summaries — every record is reviewed by the developer; secrets — capture refuses anything that looks like a key or token; stale context — records are never edited, only superseded; and integrations failing — the check works offline."

---

## 7. The ask — 0:26 (2 min, then Q&A)

**Do:** scroll to *10 · Next steps*.

**Say:**
> "The ask: a four-week pilot on one real repository. We'd measure three things — how many meaningful PRs carry a record, whether the right record shows up before an edit, and how many warnings were useful versus noise. At the end, we decide to roll out, adjust, or stop."
>
> "Questions?"

### Likely questions

| Question | Short answer |
|---|---|
| "Isn't this just a good commit message?" | A commit message isn't found when you open the file months later, isn't checked before an edit, and gets lost in squashes and rebases. The record is a file with a stable ID that the check reads. |
| "What if the assistant writes a bad record?" | It's a draft. The developer approves it, and it's reviewed in the PR like code. |
| "Does it block merges?" | No. The PR check goes red on a conflict, but merging is still the team's call. Locally it only warns. |
| "Do we have to record every change?" | No — only meaningful ones: changed defaults, behaviour changes, choices between alternatives. The skill says so. |
| "What about secrets?" | Capture refuses likely secrets, including values pulled from the diff. No transcripts are stored. |
| "Why not just use Trail-Code?" | Its check missed this exact revert for two of five wordings, and it changes global settings. We kept its good ideas. |
| "Which languages?" | Python, YAML, JSON, TOML, .env today, plus a simple fallback. Others come with the pilot repo. |

---

## Fallback

- **Network or GitHub fails:** say "Let me show you the recording of this exact run," and play the backup from the current step. Don't debug live.
- **Assistant goes off script:** run the `ct` command for that step yourself; the output is the same.
- **Start over between rehearsals:** run the reset in the runbook.

## Recording the video

Record each section as its own clip; it's easier to retake one.

| Clip | Content | Length |
|---|---|---|
| 1 | Sections 1–4 over the proposal page (voice + scroll) | ~10 min |
| 2 | 5a Dev A + record | ~3 min |
| 3 | 5b–5c PR and deploy | ~3 min |
| 4 | 5d–5e Dev B warning and supersede | ~4.5 min |
| 5 | 5f why + extras | ~1.5 min |
| 6 | Sections 6–7 | ~5 min |

Tips: zoom the terminal for the warning in 5e and hold for 3 seconds; cut the CI wait in 5c to a few seconds; keep the same window layout in every clip.
