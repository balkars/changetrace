# ChangeTrace demo: meeting script

Two developers, one setting (`RETRY_DELAY_SECONDS`), one decision that gets challenged. Each step names its terminal. Open three PowerShell windows: **Presenter terminal (repo root)**, **Dev A terminal** and **Dev B terminal**. Dev A uses Claude Code in `demo-run\devA`. Dev B uses Copilot CLI in `demo-run\devB`.

## Before the meeting

- [ ] Presenter terminal (repo root): reset the demo. This force-pushes `main` of the two demo repos and recreates the clones:

```powershell
.venv\Scripts\python scripts\demo_reset.py
```

- [ ] In every terminal, start at the repo root, load the environment and check that `ct` resolves to the repo's `.venv`:

```powershell
. .\scripts\demo-env.ps1
```

- [ ] Presenter terminal: GitHub login works:

```powershell
gh auth status
```

- [ ] Open Slack with `#engineering-prs` and `#engineering-dev` side by side. Both should be empty of new demo messages.
- [ ] Open the demo worker repo on GitHub in a browser tab (Pull requests, Actions).
- [ ] Open the rehearsal recording in a player, paused, in case the network fails.

## Steps

### 1. Dev A changes the delay (Claude Code)

Dev A terminal:

```powershell
cd demo-run\devA
claude
```

Prompt, word for word:

> Failed jobs take too long to recover. Find why and fix it.

Screen: the assistant runs `ct why RETRY_DELAY_SECONDS` (no records yet), changes the default from 2 to 0, runs the tests and `ct check`, and offers to draft a decision record.

Answer, word for word:

> Yes, draft the decision record. Mention that immediate retries could burst against a downstream service that is down.

Screen: the draft (Problem, Decided, Tried and ruled out, Assumptions, Watch out, Evidence) and a question. Answer `yes`, and approve the `ct capture` and `git commit` commands when asked. The assistant saves CTX-001 and commits it with the code.

Then open the pull request (Dev A terminal, still in `demo-run\devA`):

```powershell
git push -u origin HEAD
```

```powershell
gh pr create --fill --base main
```

### 2. Pull request and Slack

Screen: the PR on GitHub has the ChangeTrace comment naming CTX-001, its Decided and Watch out lines. `#engineering-prs` has the PR summary.

### 3. Merge and deploy to dev

Dev A terminal, in `demo-run\devA`:

```powershell
gh pr merge --merge --delete-branch
```

Watch the newest run (it may take a few seconds to appear):

```powershell
gh run watch (gh run list -L 1 --json databaseId -q '.[0].databaseId')
```

Screen: the `deploy-dev` run finishes. GitHub shows a `dev` deployment. `#engineering-dev` has the digest naming the deployment number, the PR and CTX-001.

### 4. Record what happened on dev

Dev A terminal, in `demo-run\devA`. Use the deployment number from the Slack digest (shown here as 1; replace it).

```powershell
@'
---
title: Request burst on dev
---

## Observed
After deployment 1, failed jobs retried immediately and payments API requests arrived in bursts.
'@ | ct observe --about CTX-001 --env dev --deployment 1 --input -
```

Screen: `Saved OBS-001 → .context/observations/OBS-001-…`. Commit and push it so Dev B sees it (same terminal):

```powershell
git switch main
git pull
git add .context
git commit -m "Record request burst on dev (OBS-001)"
git push
```

### 5. Dev B asks for the old value (Copilot CLI)

Dev B terminal:

```powershell
cd demo-run\devB
git pull
copilot
```

Prompt, word for word:

> Retries are hammering the payments API. Set RETRY_DELAY_SECONDS back to 2.

Screen: the assistant runs `ct why RETRY_DELAY_SECONDS`, then stops without editing and names CTX-001 with its Watch out, evidence and OBS-001. It offers alternatives and asks: "try one of these alternatives, or override CTX-001 anyway?"

Answer, word for word:

> Keep CTX-001. Add bounded exponential backoff after the first immediate retry instead.

Screen: it adds `RETRY_BACKOFF_BASE_SECONDS` / `RETRY_BACKOFF_MAX_SECONDS` (leaving `RETRY_DELAY_SECONDS` at 0), shows a draft record and asks for a yes. Answer `yes`. It runs `ct capture --from-diff --input -` → `Saved CTX-002 → …`. (To show the override path instead, answer "override CTX-001 anyway"; it then drafts a superseding record and runs `ct supersede CTX-001 --input -` after your yes.)

If the assistant skips the check, run it by hand (Dev B terminal, in `demo-run\devB`):

```powershell
ct check --file worker/config.py
```

Screen: exit code 1 and a conflict with CTX-001.

### 6. Query from the terminal and from Slack

Dev B terminal, in `demo-run\devB`:

```powershell
ct explain worker/config.py
```

```powershell
ct history --key RETRY_DELAY_SECONDS
```

```powershell
ct dev-since yesterday
```

Screen: the decisions for the setting with the PR and dev deployment linked and `Observed: OBS-001 · dev · deployment 1 — Request burst on dev`. After the override path: CTX-002 current, CTX-001 superseded, chain CTX-001 → CTX-002.

Slack bot (skip if not built). Presenter terminal (repo root):

```powershell
ct slack-bot
```

In Slack, type `/ct why RETRY_DELAY_SECONDS`, then `/ct dev-since yesterday`.

Screen: same content as the CLI, formatted for Slack.

### 7. Obsidian vault (skip if not built)

Presenter terminal (repo root):

```powershell
ct vault build --hub demo\hub.yml --out vault-out
```

Open `vault-out` as a vault in Obsidian.

Screen: CTX-001 to CTX-002 chain, OBS-001, the `RETRY_DELAY_SECONDS` key note, the Decisions dashboard, and the API service next to the worker service.

## If something fails

- **Network or GitHub is down:** stop, say so, play the rehearsal recording.
- **A step's result looks wrong:** do not debug live. Run the CLI equivalent shown in that step; if that fails too, play the recording from that step.
- **Need to start over:** in the Presenter terminal (repo root) run the reset command from "Before the meeting" and restart at step 1.

## Cut rule

Skip any step whose feature is not built (marked "skip if not built" above: `ct slack-bot` and `ct vault build`). Do not announce it; go to the next step. Everything in steps 1 to 5 must work end to end; if one of them fails in rehearsal, fix it before the meeting rather than cutting it.
