# ChangeTrace demo: meeting script

Two developers, one setting (`RETRY_DELAY_SECONDS`), one decision that gets challenged. Run from the tool repo root unless a step says otherwise. Dev A uses Claude Code in `demo-run\devA`. Dev B uses Copilot CLI in `demo-run\devB`.

## Before the meeting

- [ ] Reset the demo. This force-pushes `main` of the two demo repos and recreates the clones:

```powershell
.venv\Scripts\python scripts\demo_reset.py
```

- [ ] In both terminals (Dev A and Dev B), load the environment and check that `ct` resolves to the repo's `.venv`:

```powershell
. .\scripts\demo-env.ps1
```

- [ ] GitHub login works:

```powershell
gh auth status
```

- [ ] Open Slack with `#engineering-prs` and `#engineering-dev` side by side. Both should be empty of new demo messages.
- [ ] Open the demo worker repo on GitHub in a browser tab (Pull requests, Actions).
- [ ] Open the rehearsal recording in a player, paused, in case the network fails.

## Steps

### 1. Dev A changes the delay (Claude Code)

```powershell
cd demo-run\devA
claude
```

Prompt, word for word:

> Failed jobs take too long to recover. Find why and fix it.

Screen: the assistant runs `ct explain worker/config.py` and `ct why RETRY_DELAY_SECONDS` (no records yet), changes the default from 2 to 0, drafts CTX-001 and shows it. Approve the draft. The assistant runs `ct capture --from-diff --input -` and commits the code and the record together.

Then open the pull request:

```powershell
git push -u origin HEAD
```

```powershell
gh pr create --fill --base main
```

### 2. Pull request and Slack

Screen: the PR on GitHub has the ChangeTrace comment naming CTX-001, its Decided and Watch out lines. `#engineering-prs` has the PR summary.

### 3. Merge and deploy to dev

```powershell
gh pr merge --merge --delete-branch
```

```powershell
gh run watch
```

Screen: the `deploy-dev` run finishes. GitHub shows a `dev` deployment. `#engineering-dev` has the digest naming the deployment number, the PR and CTX-001.

### 4. Record what happened on dev

Use the deployment number from the Slack digest (shown here as 1; replace it).

```powershell
@'
---
title: Request burst on dev
---

## Observed
After deployment 1, failed jobs retried immediately and payments API requests arrived in bursts.
'@ | ct observe --about CTX-001 --env dev --deployment 1 --input -
```

Screen: `Saved OBS-001 → .context/observations/OBS-001-…`. Commit and push it so Dev B sees it:

```powershell
git switch main
git pull
git add .context
git commit -m "Record request burst on dev (OBS-001)"
git push
```

### 5. Dev B asks for the old value (Copilot CLI)

In the Dev B terminal:

```powershell
cd demo-run\devB
git pull
copilot
```

Prompt, word for word:

> Retries are hammering the payments API. Set RETRY_DELAY_SECONDS back to 2.

Screen: the assistant runs `ct why RETRY_DELAY_SECONDS` and `ct check`, then stops and names CTX-001 with its Watch out and evidence (PR, dev deployment, OBS-001) before editing. It offers bounded exponential backoff instead. Approve that. The assistant drafts CTX-002 and, after a yes, runs `ct supersede CTX-001 --input -`.

If the assistant skips the check, run it by hand:

```powershell
ct check --file worker/config.py
```

Screen: exit code 1 and a conflict with CTX-001.

### 6. Query from the terminal and from Slack

In `demo-run\devB`:

```powershell
ct why RETRY_DELAY_SECONDS
```

```powershell
ct history --key RETRY_DELAY_SECONDS
```

```powershell
ct dev-since yesterday
```

Screen: CTX-002 current, CTX-001 superseded, with the PR and the dev deployment linked.

Slack bot (skip if not built). Start it in a third terminal from the repo root, after loading `demo-env.ps1`:

```powershell
ct slack-bot
```

In Slack, type `/ct why RETRY_DELAY_SECONDS`, then `/ct dev-since yesterday`.

Screen: same content as the CLI, formatted for Slack.

### 7. Obsidian vault (skip if not built)

```powershell
ct vault build --hub demo\hub.yml --out vault-out
```

Open `vault-out` as a vault in Obsidian.

Screen: CTX-001 to CTX-002 chain, OBS-001, the `RETRY_DELAY_SECONDS` key note, the Decisions dashboard, and the API service next to the worker service.

## If something fails

- **Network or GitHub is down:** stop, say so, play the rehearsal recording.
- **A step's result looks wrong:** do not debug live. Run the CLI equivalent shown in that step; if that fails too, play the recording from that step.
- **Need to start over:** run the reset command from "Before the meeting" and restart at step 1.

## Cut rule

Skip any step whose feature is not built (marked "skip if not built" above: `ct slack-bot` and `ct vault build`). Do not announce it; go to the next step. Everything in steps 1 to 5 must work end to end; if one of them fails in rehearsal, fix it before the meeting rather than cutting it.
