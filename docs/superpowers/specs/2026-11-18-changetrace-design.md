# ChangeTrace — Design

Date: 2026-11-18 · Status: draft for approval · Source proposal: *Engineering Context Management — Technical Proposal v0.2* (`changetrace_proposal (2).html`)

---

## 1. Intent and why

AI coding assistants build up the reasoning behind a change — why a value changed, what was tried, what might break — but that reasoning stays in one developer's local session. In the proposal's example, Dev A changes `RETRY_DELAY_SECONDS` from 2 to 0 to speed up failed-job recovery; later Dev B, seeing request bursts, sets it back to 2 and silently reintroduces the original problem.

ChangeTrace makes that reasoning a reviewed, versioned record committed with the code, retrievable by any developer and any assistant from the place the problem shows up (file, setting, PR, deployment), and checked before an edit undoes it.

**Why now:** the proposal is going to the team at a meeting. The owner wants two things:

1. **For the meeting:** a working system the team can watch run end to end, with real GitHub, real Slack and a real Obsidian vault — not a mock-up.
2. **For this project:** the full analysis of all four proposal phases, so nothing about the eventual system is hidden.

## 2. Goals, non-goals, anti-goals

### Goals

| # | Goal | Proposal phase |
|---|------|----------------|
| G1 | Evaluate Trail-Code and Agent Mem Vault and record a reuse-vs-build decision | 1 |
| G2 | Context record format in the repository (`.context/`), with stable IDs, status and supersession | 2 |
| G3 | `ct` CLI: init, capture, why, explain, check, history, validate, supersede, observe | 2 |
| G4 | One shared Agent Skill that Claude Code, GitHub Copilot and Codex all load | 2 |
| G5 | A deterministic pre-edit conflict check that catches Dev B restoring 2, regardless of how the record is worded | 2 |
| G6 | GitHub: PR check + PR comment; real `dev` environment deployment via GitHub Actions, linked to records | 3 |
| G7 | Slack: PR and dev-deployment notifications; a bot that answers "why is this 0?" and "what changed in dev since yesterday?" | 3 |
| G8 | Obsidian: a cross-repository vault built from the records, with backlinks, graph and dashboard | 4 |
| G9 | The proposal's acceptance test passes live: Dev A → Dev B on separate clones, with two different assistants, without Dev A present | 2 |

### Non-goals

- Production hosting, multi-tenant auth, or a hosted service. The Slack bot runs on the presenter's laptop during the demo.
- Integrating a real incident tool (PagerDuty etc.). Observations are recorded with `ct observe`.
- An AI model in the conflict check path. The check is deterministic.
- Storing assistant transcripts. Ever, by default.
- Editing records from Obsidian or Slack. Both are read-only views; the repository is the only place records change.
- Replacing the team's real deployment pipeline. The demo's deploy step is a stand-in (see §6.6).

### Anti-goals (failure even if it "works")

- **A wrong all-clear.** The check saying Dev B's revert is fine. (Trail-Code did exactly this in testing — see §3.) A missed warning is worse than no tool.
- **Touching anyone's global configuration.** No writes to `~/.claude/settings.json`, `~/.codex`, or similar. Everything `ct init` writes is inside the repo and reviewable.
- **Silently blocking developers.** The check warns and explains; it never edits code or refuses on the developer's behalf. CI marks a failing check but merging stays the team's call.
- **Context that disappears when an integration is down.** If Slack, GitHub's API or Obsidian is unavailable, `ct why`/`explain`/`check` still work from the local clone.
- **Telemetry or promotional text injected into assistant output.**

## 3. Phase 1 — evaluation of existing projects (done)

Both projects named in the proposal were reviewed on 2026-11-18; Trail-Code was also run hands-on.

### Trail-Code (`@trailhq/trail-code` 0.30.5, TypeScript, MIT, ~11k stars)

Installed into an isolated folder and run on Windows against a two-clone sample repo reproducing the retry scenario.

| What we tested | Result |
|---|---|
| Runs on Windows, Node 22 | Yes |
| `trail note` saves a Markdown learning in `.trail/learnings/` with `touches: worker/config.py#RETRY_DELAY_SECONDS` | Yes — clean format, `status: active`, stable `id` |
| `trail check` sees uncommitted changes | Yes |
| `trail check` flags Dev B restoring 2 — learning says *"Set default from 2 to 0 …"* | **Missed. Reported the revert as "follows DevA's learning".** |
| — learning says *"must be 0, not 2"* | **Missed** ("follows") |
| — *"Keep … at 0"*, *"to 0 (was 2)"*, *"Do not set it back to 2"* | Caught: `changes RETRY_DELAY_SECONDS from 0 to 2` |
| Editing an existing learning | Flagged; suggests `trail note --replaces <id>` |

Other findings: `trail init` installs hooks into the user's global `~/.claude/settings.json`; anonymous telemetry is on by default; tool output contains instructions aimed at the assistant ("Close your reply with one line, word for word … 3x faster").

**Worth borrowing:** the learning body sections (Decided / Tried and ruled out / Watch out), `file#Symbol` touches, `--replaces` supersession, and "records are append-only — supersede, don't edit".

### Agent Mem Vault (Python, MIT, 6 stars)

Not run: it does not support Windows (uses `fcntl`). Records are not linked to code files. **Worth borrowing:** typed records, `status` / `supersedes` / `superseded_by`, an Obsidian hub note and a Bases dashboard.

### Decision

Build our own `ct` (Approach A, below). The value the team will judge the system on — the warning before Dev B's edit — must not depend on how a sentence was phrased.

## 4. Approaches considered

| | Approach | Trade-offs | Outcome |
|---|---|---|---|
| **A** | **Own `ct` tool.** Records store the protected value as a structured *guard* (`key`, `expect`, `previous`), so the check is an exact comparison. Borrows Trail-Code's body layout and Agent Mem Vault's lifecycle fields. Integrations built on top. | More code to write. Full control of format, check, and lifecycle; nothing global installed; no wording sensitivity. | **Chosen by the owner.** |
| B | Trail-Code as the core (notes + check), `ct` as an add-on for lifecycle links, GitHub, Slack, Obsidian. | Least code; shows reuse. Check missed the demo case in 2 of 5 phrasings; global hook install; telemetry; injected promo text. | Rejected. |
| C | Agent Mem Vault as the store. | Windows unsupported; no file links. | Ruled out. |

## 5. Constraints

- **Presenter's machine:** Windows 11, Python 3.13, Node 22, Git 2.50, `gh` 2.100 logged in, Obsidian installed. Everything must run on Windows (paths, line endings — the spike showed Git converting LF→CRLF; parsers must handle both).
- **Live demo reliability** beats breadth. Every step must be rehearsable and resettable.
- **Real external services:** a GitHub account for the demo repositories and a Slack workspace where the owner can create an app. Tokens and webhook URLs are entered by the owner into local `.env` files and GitHub repository secrets — never typed by the assistant.
- **No secrets in records.** Capture scans and refuses likely secrets.
- **Records are plain Markdown + YAML front matter**, readable without the tool.

## 6. Design

### 6.1 Repositories

| Repo | Purpose |
|---|---|
| `changetrace` | The tool: Python package `changetrace`, CLI `ct` (alias `changetrace`), skill template, workflow templates, Slack bot, vault builder, tests. |
| `changetrace-demo-worker` | The demo service from the proposal: `worker/config.py` with `RETRY_DELAY_SECONDS`, a tiny worker module, tests. Has `.context/`, the skill, and both workflows. |
| `changetrace-demo-api` | A second, small demo service with 1–2 records, so the Obsidian vault shows a cross-repository view. |

All three live under the owner's GitHub account. Demo Dev A and Dev B are two separate clones of `changetrace-demo-worker` in two folders.

### 6.2 Record format

One Markdown file per record. Directory layout in a service repo:

```
.context/
  config.yml                 # repo settings (see 6.3)
  decisions/CTX-001-immediate-retry.md
  observations/OBS-001-request-burst.md
```

Example decision:

```markdown
---
id: CTX-001
kind: decision
title: Immediate retry for failed jobs
status: active                # proposed | active | superseded | rejected
author: Dev A
created: 2026-11-18
touches:
  - worker/config.py#RETRY_DELAY_SECONDS
guards:
  - file: worker/config.py
    key: RETRY_DELAY_SECONDS
    expect: "0"
    previous: "2"
supersedes: []
superseded_by: null
tags: [worker, retry]
---

## Problem
The two-second wait before retrying delayed failed-job recovery.

## Decided
Default retry delay is 0 (immediate retry).

## Tried and ruled out
Keeping the delay and changing retry handling in the queue consumer — more code, same effect.

## Assumptions
Immediate retry is safe under current downstream behaviour.

## Watch out
Restoring 2 reintroduces slow recovery. Immediate retries can burst against an unavailable downstream dependency.

## Evidence
Tests: `tests/test_retry.py::test_recovers_without_delay`
```

Observation example (`OBS-001`): `kind: observation`, `about: [CTX-001]`, `environment: dev`, `deployment: <run number>`, body *What happened / Impact / Follow-up*.

**Rules**

- **IDs** are `CTX-NNN` (decisions) and `OBS-NNN` (observations), allocated as next-highest number in the clone at capture time. Two branches can allocate the same number; `ct validate` in CI fails on duplicates and `ct renumber` fixes the branch. *(Builder's call — readable IDs over collision-proof ones; collisions are rare in a small team.)*
- **Bodies are immutable once merged.** Only front matter `status` and `superseded_by` may change after merge, and only via `ct supersede`. `ct check` flags any other edit to a merged record.
- **Commit SHAs and PR numbers are not stored in records.** They are resolved on demand (§6.4), so rebases and squash merges never leave stale links. This replaces the proposal's `index.yml`; any cache lives in `.git/changetrace/`, outside the source tree.
- **Guards are optional.** A decision without guards is still found by `touches` and shown as relevant context, but cannot raise a conflict.

### 6.3 `ct` CLI

| Command | What it does |
|---|---|
| `ct init [--claude-hooks] [--github]` | Creates `.context/` and `config.yml`; writes the skill to `.agents/skills/changetrace/SKILL.md` **and** `.claude/skills/changetrace/SKILL.md`; adds one pointer line to `AGENTS.md`, `CLAUDE.md`, `.github/copilot-instructions.md`. `--claude-hooks` adds a **project-level** `.claude/settings.json` hook (§6.5). `--github` copies the two workflows (§6.6). Never writes outside the repo. |
| `ct capture --input - [--from-diff]` | Reads a draft record (YAML front matter + Markdown body) from stdin. `--from-diff` detects changed keys in the working diff and pre-fills `guards` (`previous` → `expect`). Allocates the ID, scans for secrets (refuses with the matching line), validates, writes the file. Prints the path and ID. |
| `ct why <KEY \| file#Symbol>` | Records that guard or touch the target, newest first, following supersession to the current decision. For each: status, author, *Decided*, *Watch out*, and evidence links (commit, PR, dev deployments) when resolvable. |
| `ct explain <path>` | All records touching a file, grouped by current / historical. |
| `ct check [--base REF] [--staged] [--file PATH] [--format text\|json\|markdown]` | The conflict check (§6.4). Exit 1 on conflict, 0 otherwise. |
| `ct history --key KEY` | Timeline of a key: value changes from Git history, records, and dev deployments, interleaved. |
| `ct supersede CTX-001 --input -` | Creates a new decision with `supersedes: [CTX-001]`; sets CTX-001 `status: superseded`, `superseded_by: CTX-00N`. |
| `ct observe --about CTX-001 --env dev [--deployment N] --input -` | Creates an observation record. |
| `ct validate` | Schema, duplicate IDs, broken supersession links, guards resolve (active guards' keys exist and values match), secret scan, immutability of merged bodies. For CI. |
| `ct renumber` | Fixes a duplicate ID on the current branch. |
| `ct dev-since <when> [--env dev]` | Dev deployments since `<when>` (`yesterday`, `2d`, ISO date) → commits → PRs → records. |
| `ct deploy report --env dev --sha SHA` | Used by the deploy workflow: computes what this deployment added since the previous successful one, writes the deployment status description, posts the Slack digest. |
| `ct notify slack pr --pr N` | Used by the PR workflow: posts the PR summary with linked records. |
| `ct vault build --hub hub.yml --out DIR` | Builds the Obsidian vault (§6.8). |
| `ct slack-bot` | Runs the Slack bot (§6.7). |
| `ct mcp` | *(Stretch.)* MCP stdio server exposing `why`, `explain`, `check` with the same output. |

`.context/config.yml`:

```yaml
project: Worker service
base_branch: main
github: <owner>/changetrace-demo-worker   # for PR / deployment lookups
environments: [dev]
slack:
  pr_channel: "#engineering-prs"
  dev_channel: "#engineering-dev"
```

**Implementation:** Python ≥ 3.11, `click` CLI, `PyYAML`; optional extras `[slack]` (`slack_bolt`) and `[mcp]` (`mcp`). GitHub calls go through the `gh` CLI (`gh api …`) so the same code uses the developer's login locally and `GITHUB_TOKEN` in Actions. Installed with `pipx install git+https://github.com/<owner>/changetrace` (or `pip install -e .` while developing).

### 6.4 The conflict check and link resolution

**Diff set.** Union of (a) working tree + index vs `HEAD` and (b) `HEAD` vs merge-base with `origin/<base_branch>`. `--staged` restricts to the index; `--file` restricts to one path (used by the hook).

**Value extraction** — the core of G5. For each active guard whose `file` is in the diff set, read the key's current value with an extractor chosen by file type:

| File type | Extractor |
|---|---|
| `.py` | `ast`: finds a module-level assignment to `KEY`; returns a literal, or the default argument of `os.getenv("KEY", d)` / `os.environ.get("KEY", d)`, unwrapping `int()`, `float()`, `str()`, `bool()`. |
| `.yml` / `.yaml`, `.json`, `.toml` | Parse, look up `key` as a dotted path. |
| `.env` | `KEY=value` lines. |
| anything else | Regex `KEY\s*[:=]\s*<literal>` on the first match. |

Values are compared as normalised strings (`"0" == "0"`, `0 == "0"`, quotes stripped).

**Outcomes per guard**

| Situation | Result |
|---|---|
| Current value ≠ `expect`, and no new record in the diff supersedes this one | **Conflict** (exit 1): record ID, author, `previous → expect`, current value, *Watch out*, evidence links. If the current value equals `previous`, say so explicitly: "this restores the value CTX-001 moved away from". |
| Current value ≠ `expect`, and the diff adds a record that `supersedes` it | **Resolved** — shown as "superseded by CTX-00N in this change". |
| Key not found any more | **Conflict**: "guarded key removed". |
| Extractor cannot read the value (complex expression) | **Warning** (exit 0): "cannot verify — read CTX-001". |
| File in `touches` but no guard on it | **Info**: relevant records to read. |
| Merged record body edited | **Conflict**: "records are append-only — use `ct supersede`". |

**Link resolution (no stored SHAs).**

- *Implementing commit:* the commit that added the record file — `git log --diff-filter=A --format=%H -- <record path>` (survives rebase and squash because it is recomputed).
- *PR:* `gh api repos/{repo}/commits/{sha}/pulls`.
- *Dev deployments:* `gh api repos/{repo}/deployments?environment=dev` plus statuses; a deployment includes a record if the implementing commit is an ancestor of the deployed SHA.
- All network lookups are optional: offline, `ct` prints the local commit and says links are unavailable.

### 6.5 The Agent Skill

`SKILL.md` (Agent Skills format: front matter `name`, `description`) is the workflow contract. One file, copied to both `.agents/skills/` (Codex, Copilot) and `.claude/skills/` (Claude Code); `ct validate` checks the two copies are identical. *(The exact folders each assistant reads are from secondary sources and will be confirmed against each assistant during the build.)*

The skill tells the assistant:

1. **Task start / before exploring a file or setting:** run `ct explain <path>` or `ct why <KEY>`; read active decisions before proposing changes.
2. **Before and after editing a file that has records:** run `ct check --file <path>`. On a conflict: stop, tell the developer what the decision was, why, what it warned about, and link the evidence. Offer alternatives. Do not proceed with the conflicting edit unless the developer says so.
3. **If the developer decides to override a decision:** draft a superseding record and, on their yes, `ct supersede`.
4. **Before committing a meaningful change** (a changed default or config value, a behaviour change, an approach chosen over a rejected alternative): draft a record from the developer-approved reasoning, the diff and the tests; show it; on their yes run `ct capture --from-diff`. Commit it in the same commit as the code.
5. **Never** save transcripts, edit a merged record's body, or invent a decision the developer did not make.

**Claude Code hook (optional, `ct init --claude-hooks`).** A project-level `PostToolUse` hook on `Edit|Write|MultiEdit` runs `ct check --file <edited path> --format text`; on exit 1 it returns the message to Claude. This makes the Dev B warning deterministic for Claude Code even if the skill isn't followed. Copilot and Codex rely on the skill. It lives in the repo's `.claude/settings.json`, not the user's.

### 6.6 GitHub

**PR workflow** (`.github/workflows/changetrace-pr.yml`, on `pull_request`):

1. Checkout with full history; install `ct` from the `changetrace` repo.
2. `ct validate`.
3. `ct check --base origin/main --format markdown` → a single sticky PR comment ("ChangeTrace: 1 linked decision · 0 conflicts", with each record's *Decided* and *Watch out*), updated on every push. The job fails on conflict; branch protection is **not** made required — merging remains the team's call.
4. On `opened` / `ready_for_review`: `ct notify slack pr` → `#engineering-prs`.

**Deploy workflow** (`.github/workflows/deploy-dev.yml`, on push to `main`):

1. A job with `environment: dev` — GitHub records a real Deployment for the `dev` environment.
2. Deploy step: **stand-in** — runs the worker's tests and a smoke run, then marks success. It is clearly labelled as the place the team's real deploy goes. *(Builder's call; the team's real infrastructure is out of scope.)*
3. `ct deploy report --env dev --sha $GITHUB_SHA` → deployment status description lists the PRs and records included, and posts the digest to `#engineering-dev` ("Dev deployment #86 · PR #142 · CTX-001 Immediate retry · Watch out: retry bursts").

Secrets in the demo repo: `SLACK_WEBHOOK_PRS`, `SLACK_WEBHOOK_DEV` (entered by the owner).

### 6.7 Slack

**Notifications:** two Incoming Webhooks (one per channel), Block Kit messages, posted from Actions.

**Query bot:** one Slack app in **Socket Mode** (no public URL needed), Bolt for Python, started with `ct slack-bot` on the presenter's laptop. It reads from local clones listed in `hub.yml` and uses the local `gh` login for deployments.

- `/ct why RETRY_DELAY_SECONDS` → same content as the CLI, formatted for Slack, with links to the record on GitHub, the PR and the deployment.
- `/ct dev-since yesterday` → deployment digest.
- `@ChangeTrace why is RETRY_DELAY_SECONDS 0?` → extracts the key (uppercase-identifier or `file#Symbol` token) and answers as above. No language model.

Tokens (`SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN`) live in a local `.env` the owner fills in.

**Slack → canonical promotion** *(stretch)*: a message shortcut "Promote to ChangeTrace" opens a modal (title, decided, watch out, key), then opens a PR in the target repo containing a `status: proposed` record. Slack threads are never canonical until that PR merges.

### 6.8 Obsidian team vault

`ct vault build --hub hub.yml --out <vault dir>`, where `hub.yml` lists repositories (local path or `owner/repo`, shallow-cloned into a cache).

Generated vault:

```
ChangeTrace Vault/
  Engineering overview.md           # hub: projects, counts, recent decisions
  Worker service/
    Decisions/CTX-001 Immediate retry.md
    Decisions/CTX-002 Controlled backoff.md
    Observations/OBS-001 Request burst.md
    Deployments/dev #86.md
  API service/ …
  Keys/RETRY_DELAY_SECONDS.md        # hub per guarded key
  Files/worker-config.py.md          # hub per touched file
  Dashboards/Decisions.base          # Obsidian Bases: active vs superseded, by project
  Dashboards/Decisions.md            # same data as plain Markdown tables (no plugin needed)
```

- Each decision note keeps the record's front matter (so Bases can query it) and body, plus wikilinks: `[[CTX-002 Controlled backoff]]` for supersession, `[[RETRY_DELAY_SECONDS]]`, `[[worker-config.py]]`, deployments, and a "Source" line linking to the file on GitHub at the implementing commit.
- Every generated note starts with a banner: *Generated from `<repo>@<sha>` — edit in the repository, not here.*
- The builder only deletes files inside directories it created (marker file `.changetrace-vault`), so a user's own notes in the vault are never removed.

### 6.9 Demo run (meeting script)

1. **Dev A** (clone 1, Claude Code): "Failed jobs take too long to recover — fix it." Assistant changes 2 → 0, drafts CTX-001, Dev A approves, commit, `gh pr create`.
2. **GitHub**: PR shows the ChangeTrace comment. **Slack** `#engineering-prs` gets the PR summary.
3. Merge → **Actions** runs `deploy-dev` → GitHub `dev` deployment → **Slack** `#engineering-dev` digest naming CTX-001.
4. `ct observe` records the request burst (OBS-001) against that deployment.
5. **Dev B** (clone 2, Copilot CLI): "Retries are hammering the payments API — set the delay back to 2." Assistant runs `ct why` / `ct check`, warns with CTX-001's reasoning and evidence, offers bounded exponential backoff instead → CTX-002 supersedes CTX-001.
6. **Slack**: `/ct why RETRY_DELAY_SECONDS` → shows CTX-002 current, CTX-001 historical. `/ct dev-since yesterday`.
7. **Obsidian**: `ct vault build` → open the vault: CTX-001 → CTX-002 chain, OBS-001, the key hub, the dashboard, and the API service alongside.

**Resettable:** `scripts/demo-reset` restores both demo repos and clones to the starting state, so the run can be rehearsed. Resetting the GitHub repos force-pushes `main` of the demo repos only — it never touches the tool repo.

**Fallback:** a rehearsal recording of the full run, in case the network fails during the meeting.

## 7. Build order

The meeting is **within 2 days**. Cut from the bottom; everything above a cut must work end to end. Rehearsal is moved up because a demo that hasn't been run is not ready.

**Must have for the meeting**

1. Record format, extractors, `ct capture / why / explain / check / validate / supersede` + tests (the acceptance test runs locally).
2. Skill + `ct init` + Claude Code hook; verified with Claude Code (Dev A) and Copilot CLI (Dev B).
3. GitHub PR workflow + deploy workflow + `ct deploy report` + link resolution.
4. Slack notifications (`#engineering-prs`, `#engineering-dev`).
5. Demo reset script + one full rehearsal against the real services, recorded as the fallback.

**Should have** (built in this order if time allows; the meeting script skips any step not built)

6. Obsidian vault builder + second demo repo.
7. Slack query bot (`/ct why`, `/ct dev-since`).
8. `ct observe`, `ct history`, `ct dev-since` in the CLI.

**After the meeting:** Slack promotion shortcut, MCP server, extractors for the team's real languages.

## 8. Testing

- Unit tests (pytest) for each extractor, including `int(os.getenv("RETRY_DELAY_SECONDS", 2))`, CRLF files, and unreadable expressions.
- Check tests driven by temporary Git repos: the acceptance scenario, supersession, removed key, edited record body, the five Trail-Code wordings (all must conflict — wording is irrelevant now), uncommitted and committed changes.
- Vault builder snapshot test.
- Slack and GitHub calls behind thin wrappers with fakes in tests; one manual end-to-end run against the real services before the meeting.
- Runs on Windows; CI for the tool repo runs on `ubuntu-latest` and `windows-latest`.

## 9. Risks

| Risk | Mitigation |
|---|---|
| Assistant doesn't follow the skill live | Claude Code hook makes the warning deterministic; Dev B's prompt names the setting; rehearse with the exact prompts. |
| Network / Slack / GitHub hiccup in the meeting | Core works offline; recording as fallback; run the GitHub part a few minutes before presenting. |
| Extractor can't read a value in real code | Falls back to a "cannot verify" warning, never a false all-clear. |
| Duplicate IDs across branches | `ct validate` in CI + `ct renumber`. |
| Secrets in records | Capture-time scan; `ct validate` in CI. |
| Skill folder locations differ per assistant version | Confirm each assistant during step 2; `ct init` writes all needed copies. |

## 10. Decided by the owner

- Scope C: all four phases, with **real** GitHub, Slack and Obsidian in the demo.
- Approach A: own `ct` tool; Trail-Code and Agent Mem Vault are evaluated and borrowed from, not depended on.
- Meeting is within 2 days → build order and cut line in §7.
- Slack: the **team workspace**; the owner can create and install the app themselves.
- Dev B uses **Copilot CLI** (Dev A uses Claude Code). Copilot CLI reads repository skills from `.github/skills`, `.claude/skills` or `.agents/skills` per secondary sources; the `.agents/skills/` copy covers it, confirmed during build step 2.
- Demo repositories are **public** on the owner's GitHub account: `changetrace`, `changetrace-demo-worker`, `changetrace-demo-api`.

## 11. Calls made by the designer (owner to check)

- **Python** for `ct` — the demo service is Python and Python is installed; GitHub calls go through `gh`.
- **Readable sequential IDs** (`CTX-001`) with CI duplicate detection, not random IDs.
- **No commit/PR numbers stored in records** — resolved from Git and GitHub on demand.
- **GitHub Deployments are the deployment record** — nothing is committed back to the repo from CI.
- **Deploy step is a stand-in** (tests + smoke run) in a real GitHub `dev` environment.
- **Dev A and Dev B are two clones on one laptop**, not two physical machines, for the meeting.
- **Claude Code hook is project-level** and optional, for a deterministic live warning.
- **Extractors** cover Python, YAML, JSON, TOML, `.env`, plus a regex fallback; other languages come later, driven by the team's real repos.
- **Slack bot runs locally** in Socket Mode; no hosting.
- **Stretch only:** Slack promotion shortcut, MCP server.

## 12. Left to the builder

Internal module layout; CLI flag spellings beyond those above; Block Kit layout; PR comment formatting; vault note styling; secret-scan patterns; test fixture design; how `demo-reset` is scripted.

## 13. Open questions for the owner

None outstanding — answers are recorded in §10. Owner actions needed during the build: create the Slack app and paste its tokens and webhook URLs into the local `.env` and the demo repo's secrets; approve creating the three public GitHub repositories.
