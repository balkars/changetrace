# ChangeTrace — presenter script (25–30 minutes)

What to say, what to do, and what the room should see, minute by minute. Use it live and as the shot list for the recording.

- **Say** lines are a guide. Put them in your own words; keep the facts.
- **Do** lines are exact actions. Commands match `docs/demo/meeting-script.md`, which is the step-by-step runbook behind this script.
- **Screen** lines say what should be visible. If the screen doesn't match, use the fallback at the end.

## Before you start (10 minutes before)

Run the checklist in `docs/demo/meeting-script.md` → *Before the meeting*: reset the demo, load `demo-env.ps1` in all three terminals, `gh auth status`, open Slack (`#engineering-prs`, `#engineering-dev`), open the demo repo's Pull requests and Actions tabs, cue the backup recording.

Windows to arrange, left to right:

| Window | Shows |
|---|---|
| Proposal page (`changetrace_proposal.html`) | Problem and design |
| Dev A terminal | `demo-run\devA`, Claude Code |
| Dev B terminal | `demo-run\devB`, Copilot CLI |
| Browser | GitHub demo repo: PR, Actions, Environments |
| Slack | `#engineering-prs` and `#engineering-dev` |

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
> "Let's run the story for real. Two clones of the same repo on this laptop — think of them as two developers' machines. Dev A uses Claude Code, Dev B uses Copilot CLI. The repo, the pull request, the deployment and the Slack channels are real."

### 5a. Dev A fixes slow recovery — 0:11 (3 min)

**Do (Dev A terminal):** `claude`, then type exactly:
> Failed jobs take too long to recover. Find why and fix it.

**Screen:** the assistant runs `ct explain worker/config.py` → `no records for worker/config.py`. It changes `RETRY_DELAY_SECONDS` from 2 to 0 and shows a draft record.

**Say while it works:**
> "Notice it looked first — no decisions recorded for this file yet. Now it's drafting the *why*: problem, decision, what was ruled out, and the warning for the next person. I review it like any other change."

**Do:** approve the draft.

**Screen:**
```
Saved CTX-001 → .context/decisions/CTX-001-immediate-retry-for-failed-jobs.md
```

**Do:** open the record file briefly (or `type .context\decisions\CTX-001-*.md`). Point at `guards:` — `RETRY_DELAY_SECONDS`, expect `0`, previous `2`.

**Say:**
> "Prose for humans, and one structured line the tool can check. It's committed in the same commit as the code."

**Do:** push and open the PR (commands in the runbook, step 1).

### 5b. Review and Slack — 0:14 (1.5 min)

**Do:** switch to the browser → the PR.

**Screen:** a ChangeTrace comment: *1 linked decision · 0 conflicts*, with CTX-001's Decided and Watch out. Slack `#engineering-prs` shows the PR summary with the same warning.

**Say:**
> "The reviewer gets the reasoning without asking Dev A. So does the team channel."

### 5c. Merge and deploy to dev — 0:15 (1.5 min)

**Do:** merge (runbook step 3). Switch to Actions; let `deploy-dev` run.

**Say while it runs (~40s):**
> "Merging deploys to our dev environment. The deploy step here is a stand-in that runs the tests — this is where our real deploy would go."

**Screen:** GitHub shows a `dev` deployment. Slack `#engineering-dev`: *Dev deployment #… · PR #1 · CTX-001 Immediate retry · Known consideration: …bursts…*

### 5d. Something goes wrong on dev — 0:17 (1 min)

**Do (Dev A terminal):** record the observation (runbook step 4) and push it.

**Screen:** `Saved OBS-001 → .context/observations/OBS-001-request-burst-on-dev.md`

**Say:**
> "On dev we saw retry bursts against the payments API. That's recorded too — as an observation linked to the decision, not by editing the decision. History stays honest."

### 5e. Dev B wants the old value back — 0:18 (3.5 min) — **the key moment**

**Do (Dev B terminal):** `git pull`, `copilot`, then type exactly:
> Retries are hammering the payments API. Set RETRY_DELAY_SECONDS back to 2.

**Screen:** the assistant runs `ct why` / `ct check` and stops before finishing the change:
```
✗ worker/config.py — changes RETRY_DELAY_SECONDS from 0 to 2 — this restores the value CTX-001 moved away from
  CTX-001 · Dev A · …: Immediate retry for failed jobs
  Decided: Default RETRY_DELAY_SECONDS is 0, so a failed job retries immediately.
  Watch out: Restoring 2 brings back slow recovery. Immediate retries can burst against an unavailable downstream dependency.
1 conflict(s)
```

**Pause here. Let the room read it.**

**Say:**
> "This is the whole point. Different developer, different machine, different assistant — and Dev A isn't in the room. The tool knew, because the reasoning travelled with the code. And it doesn't block: it explains, and the developer decides."

**Screen:** the assistant offers an alternative — keep the first retry immediate, then back off exponentially, capped.

**Do:** accept. Approve the draft CTX-002 when shown.

**Screen:** `Saved CTX-002 → …` and the check now reads `✓ worker/config.py — CTX-001 superseded by CTX-002 in this change`.

**Say:**
> "Dev B didn't ignore the old decision — they replaced it, on the record. CTX-001 stays in history as superseded."

**If the assistant skips the check:** run `ct check --file worker/config.py` yourself (runbook step 5). Say: "The assistant should have run this; the check itself is deterministic."

### 5f. Ask "why?" later — 0:21.5 (1.5 min)

**Do (Dev B terminal):**
```powershell
ct why RETRY_DELAY_SECONDS
```

**Screen:** CTX-002 current; CTX-001 superseded; chain CTX-001 → CTX-002; evidence: commit, PR #1, dev deployment, OBS-001.

**Say:**
> "Six months from now, someone opens this file. One command gives the whole story: what we decided, what replaced it, why, and the evidence."

Optional if time allows: `ct history --key RETRY_DELAY_SECONDS`.

### 5g. Optional extras (only if built and time allows)

- Slack: `/ct why RETRY_DELAY_SECONDS` — same answer in the team channel.
- Obsidian: open the generated vault — the decision chain, the observation, and a second service side by side.

---

## 6. What's built, what's next — 0:23 (3 min)

**Do:** scroll the proposal to *08 · Implementation*.

**Say:**
> "What you saw is built and tested — about 180 automated tests, on Windows and Linux. The decision records, the check, the skill, the Claude hook, the GitHub PR and deploy workflows, Slack notifications."
>
> "What's next, in order: the cross-repo Obsidian view and the Slack 'why' bot; then support for the languages and config formats our real services use — today it reads Python, YAML, JSON, TOML and .env."
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

- **Network, GitHub or Slack fails:** say "Let me show you the recording of this exact run," and play the backup from the current step. Don't debug live.
- **Assistant goes off script:** run the `ct` command for that step yourself; the output is the same.
- **Start over between rehearsals:** run the reset in the runbook.

## Recording the video

Record each section as its own clip; it's easier to retake one.

| Clip | Content | Length |
|---|---|---|
| 1 | Sections 1–4 over the proposal page (voice + scroll) | ~10 min |
| 2 | 5a Dev A + record | ~3 min |
| 3 | 5b–5c PR, Slack, deploy | ~3 min |
| 4 | 5d–5e Dev B warning and supersede | ~4.5 min |
| 5 | 5f why + extras | ~1.5 min |
| 6 | Sections 6–7 | ~5 min |

Tips: zoom the terminal for the warning in 5e and hold for 3 seconds; cut the CI wait in 5c to a few seconds; keep the same window layout in every clip.
