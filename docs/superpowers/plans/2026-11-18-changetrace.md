# ChangeTrace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `ct`, a Git-native decision-record tool with a deterministic pre-edit conflict check, a shared Agent Skill, GitHub PR/deploy workflows, Slack notifications, and (should-have) an Obsidian vault and Slack bot — demo-ready for a team meeting within 2 days.

**Architecture:** A Python package `changetrace` (CLI `ct`) reads and writes Markdown records in a service repo's `.context/`. Pure modules (records, extractors, check, query) sit on a thin Git wrapper; GitHub and Slack are optional adapters behind injectable runners so every network call is fakeable. Demo service repos are generated from templates in this repo by a reset script.

**Tech Stack:** Python ≥ 3.11 (dev on 3.13 / Windows), click, PyYAML, tomllib (stdlib), urllib (stdlib) for Slack webhooks, `gh` CLI for GitHub, slack_bolt (extra `[slack]`), pytest.

**Spec:** `docs/superpowers/specs/2026-11-18-changetrace-design.md` — read it first; this plan argues from it.

**Not in this plan (spec §7 "after the meeting"):** `ct mcp`, the Slack "Promote to ChangeTrace" shortcut, extractors for the team's real languages.

**Plan scope note:** the spec spans several subsystems; they share one package and one demo, and the meeting needs them together, so this is one plan in four parts. Part A alone is working software (local acceptance test passes). Parts A–C are the **must-have** cut (spec §7 steps 1–5). Part D is **should-have**, built only after Task 12's rehearsal passes.

## Global Constraints

- Python `>=3.11`; must run on Windows 11 and `ubuntu-latest`. Paths printed or stored are repo-relative POSIX (`worker/config.py`).
- `ct init` and `ct hook` never write outside the repository. No writes to `~`, `~/.claude`, `~/.codex`, `~/.copilot`.
- The conflict check is deterministic — no language model, no network.
- `why`, `explain`, `check`, `capture`, `validate`, `supersede`, `observe` work offline; GitHub lookups degrade to the line `links unavailable (offline or gh not logged in)`.
- Missing Slack config (`SLACK_WEBHOOK_URL` unset) → print `Slack not configured — skipped` and exit 0. Integrations never fail a command.
- Record files are written UTF-8 with LF; parsing accepts CRLF and a UTF-8 BOM.
- IDs: `CTX-NNN` for decisions, `OBS-NNN` for observations, 3-digit zero-padded, next-highest in the clone.
- Statuses: `proposed | active | superseded | rejected`. Kinds: `decision | observation`.
- Exit codes: `ct check` 1 on any conflict else 0; `ct validate` 1 on any problem else 0; usage errors 2 (click default).
- Capture refuses text matching the secret scan; nothing is stored from assistant transcripts.
- No telemetry, no promotional text in any output.
- GitHub: `balkars/changetrace`, `balkars/changetrace-demo-worker`, `balkars/changetrace-demo-api`, all public. Creating each repo needs the owner's explicit yes at the time.
- Slack channels: `#engineering-prs`, `#engineering-dev`. Tokens and webhook URLs are entered by the owner only.

## Review Focus

1. **Numeric formatting differences** — `0` vs `0.0` vs `"0"` for the same guard must compare equal (no false conflict). Test in Task 2.
2. **CRLF / BOM files** (Windows editors, `core.autocrlf=true`) — both config files and record files must parse. Tests in Tasks 1 and 2.
3. **Repo with no `origin` or no fetched base branch** (fresh `git init`, detached HEAD) — `ct check` compares working tree to `HEAD` and must not crash. Test in Task 3.
4. **`gh` missing, not logged in, or offline** — `ct why` still prints the record and the offline line. Test in Task 6.
5. **Absolute Windows paths with backslashes/spaces from the Claude hook** (`C:\Users\x\My Repo\worker\config.py`) — must map to `worker/config.py`. Test in Task 8.

## File Structure

```
pyproject.toml                       # package, entry points ct + changetrace, extras
.gitignore                           # .venv/, demo-run/, __pycache__/, vault-out/
src/changetrace/
  __init__.py
  records.py      # Record/Guard model, parse/render/load, IDs, paths
  extractors.py   # read a key's value from .py/.yaml/.json/.toml/.env/other
  gitops.py       # git subprocess wrapper, diff set, base ref, path mapping
  config.py       # .context/config.yml
  check.py        # conflict check + text/json/markdown formatters
  capture.py      # capture, supersede, observe, secret scan, guards from diff
  validate.py     # repo validation
  github.py       # gh-backed GitHub client (injectable runner)
  query.py        # why/explain/history, supersession chain, evidence
  deploy.py       # deploy report, dev-since, since parsing
  slack/__init__.py
  slack/notify.py # Block Kit payloads + webhook post
  slack/bot.py    # (Part D) Bolt Socket Mode app
  vault.py        # (Part D) Obsidian vault builder
  init.py         # ct init
  hook.py         # Claude Code PostToolUse hook
  cli.py          # click commands
  templates/      # SKILL.md, config.yml, claude-settings.json, pointer.md,
                  # workflows/changetrace-pr.yml, workflows/deploy-dev.yml
tests/
  conftest.py     # temp git repo builders + `scenario` fixture
  fakes.py        # FakeGh runner, captured webhook opener
  test_*.py       # one per module
demo/
  worker/         # template for balkars/changetrace-demo-worker
  api/            # (Part D) template for balkars/changetrace-demo-api
  hub.yml         # vault/bot hub config for the demo clones
slack/manifest.yml                   # Slack app manifest (Socket Mode, /ct, webhooks)
scripts/demo_reset.py                # rebuild demo repos + clones
scripts/demo-env.ps1                 # puts .venv\Scripts on PATH for demo terminals
docs/demo/meeting-script.md          # exact prompts and order for the meeting
.github/workflows/ci.yml             # tool CI: ubuntu + windows, pytest
```

---

## Part A — Core (must-have)

### Task 1: Package scaffold and record model

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `src/changetrace/__init__.py`, `src/changetrace/records.py`
- Test: `tests/test_records.py`

**Interfaces:**
- Produces (in `records.py`):
  - `CONTEXT_DIR = ".context"`; `KINDS = {"decision": ("CTX", "decisions"), "observation": ("OBS", "observations")}`; `STATUSES = ("proposed", "active", "superseded", "rejected")`
  - `class RecordError(ValueError)`
  - `@dataclass Guard(file: str, key: str, expect: str, previous: str | None = None)`
  - `@dataclass Record(id: str, kind: str, title: str, status: str, author: str, created: str, touches: list[str], guards: list[Guard], supersedes: list[str], superseded_by: str | None, tags: list[str], about: list[str], environment: str | None, deployment: str | None, body: str, path: Path | None)` with method `section(name: str) -> str` (text under `## name`, stripped; `""` if absent)
  - `parse_record(text: str, path: Path | None = None) -> Record`
  - `render_record(rec: Record) -> str` — front matter keys in this fixed order: `id, kind, title, status, author, created, touches, guards, supersedes, superseded_by, tags, about, environment, deployment`; omit `about/environment/deployment` when empty/None.
  - `load_records(repo: Path) -> list[Record]` — all `*.md` under `.context/decisions` and `.context/observations`, sorted by id; raises `RecordError` naming the file on a bad record.
  - `next_id(repo: Path, kind: str) -> str`
  - `slugify(title: str) -> str` — lowercase, non-alphanumerics → `-`, max 40 chars, no trailing `-`.
  - `record_path(repo: Path, rec: Record) -> Path` → `repo/.context/<dir>/<ID>-<slug>.md`

- [ ] **Step 1: Write `pyproject.toml`** — name `changetrace`, `requires-python = ">=3.11"`, deps `click>=8.1`, `PyYAML>=6.0`; extras `slack = ["slack_bolt>=1.18"]`, `dev = ["pytest>=8"]`; scripts `ct = "changetrace.cli:main"`, `changetrace = "changetrace.cli:main"`; src layout; package data `templates/**`. `git init -b main`, create `.venv`, `pip install -e .[dev,slack]`.

- [ ] **Step 2: Write the failing tests**

```python
SAMPLE = """---
id: CTX-001
kind: decision
title: Immediate retry for failed jobs
status: active
author: Dev A
created: 2026-11-18
touches: [worker/config.py#RETRY_DELAY_SECONDS]
guards:
  - {file: worker/config.py, key: RETRY_DELAY_SECONDS, expect: "0", previous: "2"}
supersedes: []
superseded_by: null
tags: [worker, retry]
---

## Decided
Default retry delay is 0.

## Watch out
Restoring 2 reintroduces slow recovery.
"""

def test_parse_roundtrip():
    r = parse_record(SAMPLE)
    assert r.id == "CTX-001" and r.guards[0] == Guard("worker/config.py", "RETRY_DELAY_SECONDS", "0", "2")
    assert r.section("Watch out") == "Restoring 2 reintroduces slow recovery."
    assert parse_record(render_record(r)) == r

def test_parse_accepts_crlf_and_bom():
    r = parse_record("\ufeff" + SAMPLE.replace("\n", "\r\n"))
    assert r.title == "Immediate retry for failed jobs" and r.section("Decided") == "Default retry delay is 0."

def test_guard_values_are_strings():
    r = parse_record(SAMPLE.replace('expect: "0"', "expect: 0"))
    assert r.guards[0].expect == "0"

def test_bad_status_raises():
    with pytest.raises(RecordError):
        parse_record(SAMPLE.replace("status: active", "status: maybe"))

def test_next_id_and_path(tmp_path):
    d = tmp_path / ".context/decisions"; d.mkdir(parents=True)
    (d / "CTX-001-a.md").write_text(SAMPLE, encoding="utf-8")
    (d / "CTX-007-b.md").write_text(SAMPLE.replace("CTX-001", "CTX-007"), encoding="utf-8")
    assert next_id(tmp_path, "decision") == "CTX-008"
    assert next_id(tmp_path, "observation") == "OBS-001"
    r = parse_record(SAMPLE)
    assert record_path(tmp_path, r) == d / "CTX-001-immediate-retry-for-failed-jobs.md"
```

- [ ] **Step 3: Run** `pytest tests/test_records.py -v` — Expected: FAIL (import error).
- [ ] **Step 4: Implement `records.py`** — split front matter on the first two `---` lines after stripping BOM and normalising `\r\n`; `yaml.safe_load`; coerce guard `expect`/`previous` with `str()` (keep `None`); validate `kind`, `status`, and `id` prefix matches kind.
- [ ] **Step 5: Run** `pytest tests/test_records.py -v` — Expected: PASS.
- [ ] **Step 6: Commit** — `git add -A && git commit -m "feat: record model with parse/render/load and IDs"`

### Task 2: Value extractors

**Files:**
- Create: `src/changetrace/extractors.py`
- Test: `tests/test_extractors.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) Extracted(status: Literal["found", "missing", "unreadable"], value: str | None = None)`
  - `extract_value(filename: str, text: str, key: str) -> Extracted` — dispatch on suffix: `.py`, `.yml/.yaml`, `.json`, `.toml`, `.env` (also basename `.env*`), else regex.
  - `read_keys(filename: str, text: str) -> dict[str, str]` — every readable key: Python module-level assignments to UPPER_CASE names; YAML/JSON/TOML scalar leaves as dotted paths; `.env` lines.
  - `normalize_value(v: object) -> str` — strip surrounding quotes and whitespace; `True/False` → `true/false`.
  - `values_equal(a: str, b: str) -> bool` — equal after normalising, or both parse as `float` and are equal.
  - `changed_keys(filename: str, old_text: str | None, new_text: str) -> list[tuple[str, str | None, str]]` — `(key, old, new)` for keys in `read_keys(new)` whose value differs from `read_keys(old)` (old `None` → every key is new with old `None`), sorted by key.

Python rule (the only non-obvious algorithm): find the last module-level `Assign`/`AnnAssign` to `Name(key)`. Value node → unwrap `int|float|str|bool(x)` calls (one argument); if `os.getenv(name, d)` / `os.environ.get(name, d)` / `getenv(name, d)` → use `d`; if the result is an `ast.Constant` → `found`; anything else → `unreadable`. Parse error → `unreadable`. Not assigned → `missing`.

- [ ] **Step 1: Write the failing tests**

```python
PY = 'import os\n\nRETRY_DELAY_SECONDS = int(os.getenv("RETRY_DELAY_SECONDS", 2))\nMAX_RETRIES = 5\nNAME = compute()\n'

@pytest.mark.parametrize("key,expected", [
    ("RETRY_DELAY_SECONDS", Extracted("found", "2")),
    ("MAX_RETRIES", Extracted("found", "5")),
    ("NAME", Extracted("unreadable")),
    ("ABSENT", Extracted("missing")),
])
def test_python(key, expected):
    assert extract_value("worker/config.py", PY, key) == expected

def test_python_crlf():
    assert extract_value("c.py", PY.replace("\n", "\r\n"), "MAX_RETRIES").value == "5"

def test_environ_get_and_float():
    src = 'import os\nX = float(os.environ.get("X", 0.5))\n'
    assert extract_value("c.py", src, "X").value == "0.5"

def test_yaml_json_toml_env_other():
    assert extract_value("s.yaml", "rate:\n  limit: 60\n", "rate.limit").value == "60"
    assert extract_value("s.json", '{"rate": {"limit": 60}}', "rate.limit").value == "60"
    assert extract_value("s.toml", "[rate]\nlimit = 60\n", "rate.limit").value == "60"
    assert extract_value(".env", "RATE=60\n", "RATE").value == "60"
    assert extract_value("app.ini", "RATE = 60\n", "RATE").value == "60"

def test_values_equal_numeric():
    assert values_equal("0", "0.0") and values_equal('"0"', "0") and not values_equal("0", "2")

def test_changed_keys():
    new = PY.replace('"RETRY_DELAY_SECONDS", 2', '"RETRY_DELAY_SECONDS", 0')
    assert changed_keys("worker/config.py", PY, new) == [("RETRY_DELAY_SECONDS", "2", "0")]
```

- [ ] **Step 2: Run** `pytest tests/test_extractors.py -v` — Expected: FAIL.
- [ ] **Step 3: Implement `extractors.py`** per the interface and the Python rule above (normalise `\r\n` before parsing; regex fallback `^\s*KEY\s*[:=]\s*(.+?)\s*$`, first match, multiline).
- [ ] **Step 4: Run** `pytest tests/test_extractors.py -v` — Expected: PASS.
- [ ] **Step 5: Commit** — `git commit -am "feat: value extractors for py/yaml/json/toml/env"` (add new files first).

### Task 3: Git wrapper, config, and test scenario fixture

**Files:**
- Create: `src/changetrace/gitops.py`, `src/changetrace/config.py`, `tests/conftest.py`
- Test: `tests/test_gitops.py`

**Interfaces:**
- Produces (`gitops.py`):
  - `class GitError(RuntimeError)`
  - `git(repo: Path, *args: str, check: bool = True) -> str` (stdout, stripped; `GitError` with stderr on failure when `check`)
  - `repo_root(start: Path) -> Path`
  - `base_ref(repo: Path, base_branch: str) -> str | None` — `merge-base HEAD origin/<base_branch>`; `None` if no origin, branch unknown, or no commits.
  - `changed_files(repo: Path, base: str | None = None, staged: bool = False) -> list[str]` — sorted unique POSIX paths: staged + unstaged vs `HEAD` + untracked (`ls-files --others --exclude-standard`) + (`base..HEAD` if `base`); `staged=True` → only `diff --cached --name-only` vs `HEAD`. Repo with no commits → all files from `ls-files` + untracked.
  - `read_at(repo: Path, ref: str, path: str) -> str | None` (`git show ref:path`, `None` if absent)
  - `added_commit(repo: Path, path: str) -> str | None` (`log --diff-filter=A --format=%H -- path`, last line = oldest)
  - `is_ancestor(repo: Path, a: str, b: str) -> bool`
  - `rev_list(repo: Path, start: str | None, end: str) -> list[str]` (`start..end`, or all of `end` if `start` is None)
  - `to_repo_path(repo: Path, p: str) -> str` — absolute or relative, `\` or `/` → POSIX path relative to `repo`; raises `ValueError` if outside.
- Produces (`config.py`): `@dataclass Config(project: str, base_branch: str = "main", github: str | None = None, environments: list[str] = ["dev"], pr_channel: str = "#engineering-prs", dev_channel: str = "#engineering-dev")`; `load_config(repo: Path) -> Config` reading `.context/config.yml` (spec §6.3 shape — `slack.pr_channel` / `slack.dev_channel` map to the flat fields; defaults if file absent).
- Produces (`tests/conftest.py`):
  - helpers `write(repo, rel, text)`, `commit_all(repo, msg) -> str` (sha), `set_retry(repo, value: str)`
  - `CONFIG_PY` = the spec's `worker/config.py` with default `2`; `CTX001_RECORD` = the full spec §6.2 record text (`CTX-001`, guard `expect "0"`, `previous "2"`); `CTX001_DECIDED = "Default retry delay is 0 (immediate retry)."`; `ctx001_draft(decided: str = CTX001_DECIDED) -> str` = front matter `title: Immediate retry for failed jobs` + body sections Problem, Decided (= `decided`), Tried and ruled out, Assumptions, Watch out (spec §6.2 text); `CTX001_DRAFT = ctx001_draft()`
  - fixture `scenario(tmp_path) -> Scenario(origin: Path, dev_a: Path, dev_b: Path)` — bare `origin.git` on `main`, `dev_a` clone with `worker/config.py`, `.context/config.yml` (`project: Worker service`), committed and pushed; `dev_b` clone; user names `DevA`/`DevB`.
  - helper `finish_and_merge(s: Scenario) -> None` — in `dev_a`: commit all on the current branch, merge `--no-ff` into `main`, push; in `dev_b`: `git pull`.
  - helper `dev_a_ships_ctx001(s: Scenario, decided: str = CTX001_DECIDED) -> None` — in `dev_a`: branch `fix/immediate-retry`, `set_retry("0")`, `capture(dev_a, ctx001_draft(decided), from_diff=True)`, then `finish_and_merge(s)`. Written in Task 4, once `capture` exists.

- [ ] **Step 1: Write the failing tests**

```python
def test_changed_files_includes_untracked_and_branch(scenario):
    a = scenario.dev_a
    git(a, "checkout", "-b", "f"); set_retry(a, "0"); commit_all(a, "c")
    write(a, ".context/decisions/CTX-001-x.md", "x")
    base = base_ref(a, "main")
    assert changed_files(a, base) == [".context/decisions/CTX-001-x.md", "worker/config.py"]

def test_no_origin_repo_works(tmp_path):
    git(tmp_path, "init", "-b", "main"); write(tmp_path, "a.py", "X = 1\n")
    assert base_ref(tmp_path, "main") is None
    assert changed_files(tmp_path) == ["a.py"]

def test_to_repo_path_windows_style(tmp_path):
    sub = tmp_path / "My Repo"; sub.mkdir()
    assert to_repo_path(sub, str(sub / "worker" / "config.py")) == "worker/config.py"
    assert to_repo_path(sub, "worker\\config.py") == "worker/config.py"

def test_added_commit(scenario):
    a = scenario.dev_a
    assert added_commit(a, "worker/config.py") == git(a, "rev-parse", "HEAD")

def test_load_config_defaults(tmp_path):
    assert load_config(tmp_path).base_branch == "main"
```

- [ ] **Step 2: Run** `pytest tests/test_gitops.py -v` — Expected: FAIL.
- [ ] **Step 3: Implement `gitops.py`, `config.py`, `conftest.py`** — `subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8")`; fixture sets `git config user.name/email` per clone and `core.autocrlf=false` in `dev_a`, `true` in `dev_b` (exercises Review Focus 2).
- [ ] **Step 4: Run** `pytest tests/test_gitops.py -v` — Expected: PASS.
- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat: git wrapper, config, test scenario"`

### Task 4: Capture, supersede, observe, secret scan

**Files:**
- Create: `src/changetrace/capture.py`
- Modify: `tests/conftest.py` (complete `dev_a_ships_ctx001`)
- Test: `tests/test_capture.py`

**Interfaces:**
- Consumes: `records.*`, `extractors.changed_keys`, `gitops.changed_files/base_ref/read_at/git`, `config.load_config`.
- Produces:
  - `class CaptureError(ValueError)`
  - `scan_secrets(text: str) -> list[str]` — returns offending lines. Patterns: `AKIA[0-9A-Z]{16}`, `gh[pousr]_[A-Za-z0-9]{20,}`, `xox[abposr]-[A-Za-z0-9-]{10,}`, `hooks\.slack\.com/services/\S+`, `-----BEGIN [A-Z ]*PRIVATE KEY-----`, `(?i)(password|passwd|secret|api[_-]?key|token)\s*[:=]\s*\S{6,}`.
  - `guards_from_diff(repo: Path) -> list[Guard]` — for each changed, readable file (base = `base_ref` or `HEAD`), `changed_keys(old_at_base, working_text)`; `Guard(file, key, expect=new, previous=old)`.
  - `capture(repo: Path, draft: str, from_diff: bool = False, author: str | None = None, today: date | None = None) -> Record` — draft = front matter (`title` required; optional `touches`, `guards`, `tags`, `status`) + body; requires `## Decided` section; fills `id=next_id`, `kind="decision"`, `status="active"` unless draft says `proposed`, `author` (default `git config user.name`), `created` (ISO date); with `from_diff`, appends `guards_from_diff` and adds `file#key` to `touches` (dedup); refuses on `scan_secrets(draft)` with `CaptureError` listing lines; writes `record_path`; returns the record.
  - `supersede(repo: Path, old_id: str, draft: str, from_diff: bool = False, author: str | None = None, today: date | None = None) -> Record` — new decision with `supersedes=[old_id]`; rewrites old record with `status="superseded"`, `superseded_by=<new id>` (only those two fields change). `CaptureError` if old is not `active`.
  - `observe(repo: Path, about: list[str], env: str, deployment: str | None, draft: str, author: str | None = None, today: date | None = None) -> Record` — `kind="observation"`, `status="active"`, `OBS-NNN`.

- [ ] **Step 1: Write the failing tests**

```python
def test_capture_from_diff_fills_guard(scenario):
    a = scenario.dev_a; set_retry(a, "0")
    rec = capture(a, CTX001_DRAFT, from_diff=True, today=date(2026, 11, 18))
    assert rec.id == "CTX-001" and rec.author == "DevA" and rec.status == "active"
    assert rec.guards == [Guard("worker/config.py", "RETRY_DELAY_SECONDS", "0", "2")]
    assert "worker/config.py#RETRY_DELAY_SECONDS" in rec.touches
    assert rec.path.name == "CTX-001-immediate-retry-for-failed-jobs.md"

def test_capture_refuses_secret(scenario):
    with pytest.raises(CaptureError, match="api_key"):
        capture(scenario.dev_a, CTX001_DRAFT + "\napi_key = abcdef123456\n")

def test_capture_requires_decided(scenario):
    with pytest.raises(CaptureError):
        capture(scenario.dev_a, "---\ntitle: X\n---\n\n## Watch out\nY\n")

def test_supersede_marks_old(scenario):
    dev_a_ships_ctx001(scenario)
    new = supersede(scenario.dev_b, "CTX-001", "---\ntitle: Controlled backoff\n---\n\n## Decided\nBackoff.\n")
    old = {r.id: r for r in load_records(scenario.dev_b)}["CTX-001"]
    assert new.id == "CTX-002" and new.supersedes == ["CTX-001"]
    assert old.status == "superseded" and old.superseded_by == "CTX-002"

def test_observe(scenario):
    rec = observe(scenario.dev_a, ["CTX-001"], "dev", "86", "---\ntitle: Request burst\n---\n\n## What happened\nBurst.\n")
    assert rec.id == "OBS-001" and rec.about == ["CTX-001"] and rec.deployment == "86"
```

- [ ] **Step 2: Run** `pytest tests/test_capture.py -v` — Expected: FAIL.
- [ ] **Step 3: Implement `capture.py`** and complete `dev_a_ships_ctx001` in `conftest.py`.
- [ ] **Step 4: Run** `pytest tests/test_capture.py -v` — Expected: PASS.
- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat: capture, supersede, observe with secret scan"`

### Task 5: Conflict check

**Files:**
- Create: `src/changetrace/check.py`
- Test: `tests/test_check.py`

**Interfaces:**
- Consumes: `records.load_records/parse_record`, `extractors.extract_value/values_equal`, `gitops.*`, `config.load_config`.
- Produces:
  - `@dataclass Finding(kind: Literal["conflict", "resolved", "warning", "info"], record_id: str, file: str, message: str, key: str | None = None, current: str | None = None)`
  - `run_check(repo: Path, base: str | None = None, staged: bool = False, file: str | None = None) -> list[Finding]` — `base` defaults to `base_ref(repo, config.base_branch)`; comparison ref for record history = `base` or `HEAD`.
  - `has_conflict(findings: list[Finding]) -> bool`
  - `format_text(findings: list[Finding], records: dict[str, Record]) -> str`
  - `format_json(findings: list[Finding]) -> str`
  - `format_markdown(findings: list[Finding], records: dict[str, Record]) -> str` — header `### ChangeTrace` + `N linked decision(s) · M conflict(s)` then one bullet per finding with *Decided* and *Watch out*.

Rules (spec §6.4), for every record R in the working tree with a guard whose `file` is in the diff set (or equals `file` when given):
- R active: read value; `missing` → conflict `guarded key removed`; `unreadable` → warning `cannot verify — read <id>`; value ≠ `expect` → resolved if any changed-set record lists R.id in `supersedes`, else conflict.
- R superseded in the working tree but `active` at the comparison ref → value ≠ `expect` → resolved `superseded by <superseded_by> in this change`.
- Conflict message: `changes <key> from <expect> to <current>`; when `values_equal(current, previous)` append `— this restores the value <id> moved away from`.
- Touched file with no guard → one `info` per record: `relevant: <id> <title>`.
- Changed record file that existed at the comparison ref: if anything other than `status`/`superseded_by` differs → conflict `records are append-only — use ct supersede`.
- `format_text` prints, per conflict: `✗ <file> — <message>`, then `  <id> · <author> · <created>: <title>`, `  Decided: …`, `  Watch out: …`; ends with `N conflict(s)` or `no conflicts`.

- [ ] **Step 1: Write the failing tests**

```python
WORDINGS = [
    "Set default from 2 to 0 because the two-second wait delayed recovery.",
    "RETRY_DELAY_SECONDS must be 0, not 2.",
    "Keep RETRY_DELAY_SECONDS at 0.",
    "Changed RETRY_DELAY_SECONDS to 0 (was 2).",
    "Do not set it back to 2.",
]

@pytest.mark.parametrize("decided", WORDINGS)
def test_revert_conflicts_whatever_the_wording(scenario, decided):
    dev_a_ships_ctx001(scenario, decided)
    set_retry(scenario.dev_b, "2")
    f = run_check(scenario.dev_b)
    assert has_conflict(f)
    c = [x for x in f if x.kind == "conflict"][0]
    assert c.record_id == "CTX-001" and c.current == "2"
    assert "restores the value CTX-001 moved away from" in c.message

def test_committed_revert_still_conflicts(scenario):
    dev_a_ships_ctx001(scenario); b = scenario.dev_b
    git(b, "checkout", "-b", "r"); set_retry(b, "2"); commit_all(b, "revert")
    assert has_conflict(run_check(b))

def test_superseded_in_same_change_is_resolved(scenario):
    dev_a_ships_ctx001(scenario); b = scenario.dev_b
    set_retry(b, "2")
    supersede(b, "CTX-001", "---\ntitle: Controlled backoff\n---\n\n## Decided\nBackoff.\n")
    f = run_check(b)
    assert not has_conflict(f) and any(x.kind == "resolved" for x in f)

def test_removed_key_conflicts(scenario):
    dev_a_ships_ctx001(scenario)
    write(scenario.dev_b, "worker/config.py", "import os\n")
    assert run_check(scenario.dev_b)[0].message.startswith("guarded key removed")

def test_editing_merged_record_body_conflicts(scenario):
    dev_a_ships_ctx001(scenario); b = scenario.dev_b
    p = next((b / ".context/decisions").glob("CTX-001-*.md"))
    p.write_text(p.read_text(encoding="utf-8").replace("Default retry", "Some retry"), encoding="utf-8")
    assert any("append-only" in x.message for x in run_check(b))

def test_unrelated_change_no_findings(scenario):
    dev_a_ships_ctx001(scenario)
    write(scenario.dev_b, "README.md", "hi\n")
    assert run_check(scenario.dev_b) == []

def test_file_filter_and_markdown(scenario):
    dev_a_ships_ctx001(scenario); set_retry(scenario.dev_b, "2")
    f = run_check(scenario.dev_b, file="worker/config.py")
    md = format_markdown(f, {r.id: r for r in load_records(scenario.dev_b)})
    assert md.startswith("### ChangeTrace") and "1 conflict" in md

def test_check_without_origin(tmp_path):
    git(tmp_path, "init", "-b", "main"); write(tmp_path, "worker/config.py", CONFIG_PY.replace(", 2)", ", 0)"))
    write(tmp_path, ".context/decisions/CTX-001-immediate-retry-for-failed-jobs.md", CTX001_RECORD)
    commit_all(tmp_path, "init")
    set_retry(tmp_path, "2")
    assert has_conflict(run_check(tmp_path))
```

(`CTX001_RECORD` in `conftest.py` = the full spec §6.2 record text with the guard `expect "0"`, `previous "2"`.)

- [ ] **Step 2: Run** `pytest tests/test_check.py -v` — Expected: FAIL.
- [ ] **Step 3: Implement `check.py`** per the rules.
- [ ] **Step 4: Run** `pytest tests/test_check.py -v` — Expected: PASS.
- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat: deterministic conflict check"`

### Task 6: GitHub client, evidence, why/explain/history, validate

**Files:**
- Create: `src/changetrace/github.py`, `src/changetrace/query.py`, `src/changetrace/validate.py`, `tests/fakes.py`
- Test: `tests/test_query.py`, `tests/test_validate.py`

**Interfaces:**
- Produces (`github.py`):
  - `class GitHubUnavailable(RuntimeError)`
  - `run_gh(args: list[str]) -> str` — `subprocess.run(["gh", *args])`; `FileNotFoundError` or non-zero → `GitHubUnavailable`. Every call is exactly `["api", "<path with query string>"]` (e.g. `["api", "repos/o/r/deployments?environment=dev"]`) so fakes can key on `" ".join(args)`.
  - `class GitHub(repo_slug: str, runner: Callable[[list[str]], str] = run_gh)` with:
    - `prs_for_commit(sha: str) -> list[dict]` → `[{"number", "title", "url", "author"}]` from `api repos/{slug}/commits/{sha}/pulls`
    - `pr(number: int) -> dict` → same keys, from `api repos/{slug}/pulls/{n}`
    - `deployments(env: str) -> list[dict]` → `[{"id", "sha", "created_at", "state"}]`, newest first; `state` = first entry of `api repos/{slug}/deployments/{id}/statuses` or `"unknown"`
    - `html_url(path: str, ref: str) -> str` → `https://github.com/{slug}/blob/{ref}/{path}`
- Produces (`tests/fakes.py`): `class FakeGh` — callable runner keyed by `" ".join(args)` → JSON string; records calls; `FakeGh.offline()` returns a runner that raises `GitHubUnavailable`.
- Produces (`query.py`):
  - `@dataclass Evidence(commit: str | None, prs: list[dict], deployments: list[dict], note: str | None)`
  - `@dataclass RecordView(record: Record, current: bool, chain: list[str], evidence: Evidence | None)` — `chain` = ids from oldest to newest along `supersedes`/`superseded_by`.
  - `resolve_evidence(repo: Path, rec: Record, gh: GitHub | None) -> Evidence` — commit = `added_commit`; PRs via `gh.prs_for_commit`; deployments = those in each `config.environments` whose `sha` has the commit as ancestor (`is_ancestor`, skip unknown shas); on `GitHubUnavailable` or `gh is None` → `note="links unavailable (offline or gh not logged in)"`.
  - `why(repo: Path, target: str, gh: GitHub | None = None) -> list[RecordView]` — `target` is `KEY` or `file#Symbol` or `file`; matches guard keys, `touches` entries, or touch file part; current (active) first, then historical, each newest first.
  - `explain(repo: Path, path: str, gh: GitHub | None = None) -> list[RecordView]` — records whose `touches` or guards reference `path`.
  - `@dataclass HistoryEntry(when: str, kind: Literal["value", "record", "deployment"], text: str)`
  - `history(repo: Path, key: str, gh: GitHub | None = None) -> list[HistoryEntry]` — value changes from `git log -L`-free approach: for each commit touching a guard file of that key (`git log --format=%H %as -- file`), extract value at that commit, emit when it changes; plus records' `created`; plus deployments; sorted by date. Text formats: value `RETRY_DELAY_SECONDS 2 → 0 (commit abc1234)`; record `CTX-001 Immediate retry for failed jobs (active)`; deployment `dev deploy abc1234 (success)`.
  - `format_views(views: list[RecordView]) -> str` — text; each view: `CTX-001 · active · DevA · 2026-11-18 — Immediate retry for failed jobs`, then Decided, Watch out, `Evidence: commit abc1234 · PR #1 · dev deploy 2026-11-18` or the note.
- Produces (`validate.py`): `@dataclass Problem(path: str, message: str)`; `validate_repo(repo: Path) -> list[Problem]` — messages: `parse error: <detail>`; `duplicate id CTX-001`; `supersedes unknown CTX-009`; `superseded_by CTX-002 does not supersede CTX-001`; `guard RETRY_DELAY_SECONDS missing in worker/config.py`; `guard RETRY_DELAY_SECONDS expects 0, found 2`; `possible secret: <line>`; `skill copies differ`. (Immutability of merged bodies is enforced by `ct check`, which runs in the same PR workflow.)

- [ ] **Step 1: Write the failing tests**

```python
def test_why_offline_still_prints(scenario):
    dev_a_ships_ctx001(scenario)
    v = why(scenario.dev_b, "RETRY_DELAY_SECONDS", GitHub("o/r", FakeGh.offline()))
    assert v[0].record.id == "CTX-001" and v[0].current
    assert "links unavailable" in format_views(v)

def test_why_with_pr_and_deploy(scenario):
    dev_a_ships_ctx001(scenario); b = scenario.dev_b
    commit = added_commit(b, next(b.glob(".context/decisions/CTX-001-*.md")).relative_to(b).as_posix())
    head = git(b, "rev-parse", "HEAD")
    gh = FakeGh({f"api repos/o/r/commits/{commit}/pulls": [{"number": 1, "title": "Immediate retry", "html_url": "u", "user": {"login": "deva"}}],
                 "api repos/o/r/deployments?environment=dev": [{"id": 9, "sha": head, "created_at": "2026-11-18T14:20:00Z"}],
                 "api repos/o/r/deployments/9/statuses": [{"state": "success"}]})
    write(b, ".context/config.yml", "project: Worker service\ngithub: o/r\nenvironments: [dev]\n")
    text = format_views(why(b, "worker/config.py#RETRY_DELAY_SECONDS", GitHub("o/r", gh)))
    assert "PR #1" in text and "dev deploy 2026-11-18" in text

def test_why_follows_supersession(scenario):
    dev_a_ships_ctx001(scenario); b = scenario.dev_b
    supersede(b, "CTX-001", "---\ntitle: Controlled backoff\nguards: []\ntouches: [worker/config.py#RETRY_DELAY_SECONDS]\n---\n\n## Decided\nBackoff.\n")
    v = why(b, "RETRY_DELAY_SECONDS")
    assert [x.record.id for x in v] == ["CTX-002", "CTX-001"] and v[0].chain == ["CTX-001", "CTX-002"]

def test_history_shows_value_changes(scenario):
    dev_a_ships_ctx001(scenario)
    texts = [h.text for h in history(scenario.dev_b, "RETRY_DELAY_SECONDS")]
    assert any("2 → 0" in t for t in texts) and any("CTX-001" in t for t in texts)

def test_validate_duplicate_and_mismatch(scenario):
    dev_a_ships_ctx001(scenario); b = scenario.dev_b
    p = next(b.glob(".context/decisions/CTX-001-*.md"))
    (p.parent / "CTX-001-dup.md").write_text(p.read_text(encoding="utf-8"), encoding="utf-8")
    set_retry(b, "2")
    msgs = [x.message for x in validate_repo(b)]
    assert any("duplicate id CTX-001" in m for m in msgs) and any("expects 0, found 2" in m for m in msgs)
```

- [ ] **Step 2: Run** `pytest tests/test_query.py tests/test_validate.py -v` — Expected: FAIL.
- [ ] **Step 3: Implement `github.py`, `query.py`, `validate.py`, `fakes.py`.**
- [ ] **Step 4: Run** `pytest tests/test_query.py tests/test_validate.py -v` — Expected: PASS.
- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat: why/explain/history, evidence links, validate"`

### Task 7: CLI and local acceptance test

**Files:**
- Create: `src/changetrace/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: everything above.
- Produces: click group `main` with commands (spec §6.3 names and flags): `capture [--input FILE|-] [--from-diff]`, `supersede ID [--input -] [--from-diff]`, `observe --about ID... --env ENV [--deployment N] [--input -]`, `why TARGET`, `explain PATH`, `check [--base REF] [--staged] [--file PATH] [--format text|json|markdown]`, `history --key KEY`, `validate`, `renumber`. All take `--repo PATH` (default: `repo_root(cwd)`). GitHub client built from `config.github` when set, else `None`. `renumber`: if the current branch adds a record whose id also exists at the base ref, move it to `next_id` (rename file, rewrite id, fix `supersedes`/`superseded_by` references on the branch).
- `capture`/`supersede`/`observe` print `Saved CTX-001 → .context/decisions/CTX-001-….md`.

- [ ] **Step 1: Write the failing tests** (CliRunner, `--repo` pointing at scenario clones)

```python
def test_acceptance_dev_a_to_dev_b(scenario):
    r = CliRunner()
    set_retry(scenario.dev_a, "0")
    out = r.invoke(main, ["capture", "--from-diff", "--repo", str(scenario.dev_a)], input=CTX001_DRAFT)
    assert out.exit_code == 0 and "Saved CTX-001" in out.output
    finish_and_merge(scenario)                      # helper: commit, merge, push, dev_b pull
    set_retry(scenario.dev_b, "2")
    res = r.invoke(main, ["check", "--repo", str(scenario.dev_b)])
    assert res.exit_code == 1
    assert "CTX-001" in res.output and "Watch out:" in res.output and "moved away from" in res.output
    why_out = r.invoke(main, ["why", "RETRY_DELAY_SECONDS", "--repo", str(scenario.dev_b)])
    assert "Immediate retry for failed jobs" in why_out.output

def test_check_json_and_markdown(scenario):
    dev_a_ships_ctx001(scenario); set_retry(scenario.dev_b, "2")
    j = CliRunner().invoke(main, ["check", "--format", "json", "--repo", str(scenario.dev_b)])
    assert json.loads(j.output)[0]["kind"] == "conflict"

def test_validate_exit_code(scenario):
    dev_a_ships_ctx001(scenario)
    assert CliRunner().invoke(main, ["validate", "--repo", str(scenario.dev_b)]).exit_code == 0

def test_renumber(scenario):
    dev_a_ships_ctx001(scenario); b = scenario.dev_b
    git(b, "checkout", "-b", "x")
    write(b, ".context/decisions/CTX-001-other.md", CTX001_RECORD.replace("Immediate retry for failed jobs", "Other"))
    CliRunner().invoke(main, ["renumber", "--repo", str(b)])
    assert parse_record((b / ".context/decisions/CTX-002-other.md").read_text(encoding="utf-8")).id == "CTX-002"
```

- [ ] **Step 2: Run** `pytest tests/test_cli.py -v` — Expected: FAIL.
- [ ] **Step 3: Implement `cli.py`.** On Windows force UTF-8 output: `sys.stdout.reconfigure(encoding="utf-8")` in `main` (the ✗/→ characters).
- [ ] **Step 4: Run** `pytest -v` (whole suite) — Expected: PASS.
- [ ] **Step 5: Manual check** — in a temp folder repeat the spike from the spec §3 with `ct` instead of `trail`: two clones, Dev A captures, Dev B restores 2, `ct check` → exit 1 naming CTX-001.
- [ ] **Step 6: Commit** — `git add -A && git commit -m "feat: ct CLI with local acceptance test"`

### Task 8: Agent Skill, `ct init`, Claude Code hook

**Files:**
- Create: `src/changetrace/init.py`, `src/changetrace/hook.py`, `src/changetrace/templates/SKILL.md`, `templates/pointer.md`, `templates/config.yml`, `templates/claude-settings.json`
- Modify: `src/changetrace/cli.py` (add `init`, `hook claude`)
- Test: `tests/test_init_hook.py`

**Interfaces:**
- Produces:
  - `init_repo(repo: Path, project: str | None = None, claude_hooks: bool = False, github: bool = False) -> list[str]` — writes (only if absent, except pointer lines which are appended once): `.context/config.yml`, `.context/decisions/.gitkeep`, `.context/observations/.gitkeep`, `.agents/skills/changetrace/SKILL.md`, `.claude/skills/changetrace/SKILL.md`, pointer line in `AGENTS.md`, `CLAUDE.md`, `.github/copilot-instructions.md`; with `claude_hooks`, merges the hook into `.claude/settings.json` (keeps existing keys); with `github`, copies the two workflow templates (Task 11) to `.github/workflows/`. Returns repo-relative paths written. Asserts every path is inside `repo`.
  - `claude_post_edit(stdin_json: str, repo: Path) -> tuple[int, str]` — reads `tool_input.file_path` (also `tool_input.edits[*]` absent → ignore); maps with `to_repo_path`; returns `(2, format_text(...))` on conflict, else `(0, "")`; path outside repo or unparsable JSON → `(0, "")`.
  - CLI: `ct init [--project NAME] [--claude-hooks] [--github]`; `ct hook claude` (reads stdin, writes message to stderr, exits with the code).
- `templates/claude-settings.json`: `{"hooks": {"PostToolUse": [{"matcher": "Edit|Write|MultiEdit", "hooks": [{"type": "command", "command": "ct hook claude"}]}]}}`
- `templates/pointer.md`: `Engineering context: before editing, follow .agents/skills/changetrace/SKILL.md (decision records live in .context/).`
- `SKILL.md`: front matter `name: changetrace`, `description: Use before exploring or editing code, before committing, and when asked why code is the way it is — checks and records engineering decisions in .context/ with the ct CLI.` Body = the five rules of spec §6.5, each with the exact command, plus: the conflict reply template (what was decided, why, watch out, evidence, alternatives, "proceed anyway?"), the capture draft template (front matter `title`, sections Problem / Decided / Tried and ruled out / Assumptions / Watch out / Evidence), and "never edit a merged record's body; never save transcripts; show every draft and wait for a yes".

- [ ] **Step 1: Write the failing tests**

```python
def test_init_writes_only_inside_repo(tmp_path, monkeypatch):
    home = tmp_path / "home"; home.mkdir(); monkeypatch.setenv("HOME", str(home)); monkeypatch.setenv("USERPROFILE", str(home))
    repo = tmp_path / "r"; repo.mkdir(); git(repo, "init", "-b", "main")
    written = init_repo(repo, project="Worker service", claude_hooks=True)
    assert ".agents/skills/changetrace/SKILL.md" in written and ".claude/settings.json" in written
    assert list(home.iterdir()) == []
    assert (repo / ".agents/skills/changetrace/SKILL.md").read_bytes() == (repo / ".claude/skills/changetrace/SKILL.md").read_bytes()

def test_init_idempotent_pointer(tmp_path):
    git(tmp_path, "init", "-b", "main"); init_repo(tmp_path); init_repo(tmp_path)
    assert (tmp_path / "AGENTS.md").read_text(encoding="utf-8").count(".agents/skills/changetrace") == 1

def test_init_merges_existing_claude_settings(tmp_path):
    git(tmp_path, "init", "-b", "main"); write(tmp_path, ".claude/settings.json", '{"model": "x"}')
    init_repo(tmp_path, claude_hooks=True)
    s = json.loads((tmp_path / ".claude/settings.json").read_text(encoding="utf-8"))
    assert s["model"] == "x" and s["hooks"]["PostToolUse"][0]["hooks"][0]["command"] == "ct hook claude"

def test_hook_absolute_windows_path(scenario):
    dev_a_ships_ctx001(scenario); set_retry(scenario.dev_b, "2")
    p = str(scenario.dev_b / "worker" / "config.py").replace("/", "\\")
    code, msg = claude_post_edit(json.dumps({"tool_input": {"file_path": p}}), scenario.dev_b)
    assert code == 2 and "CTX-001" in msg

def test_hook_ignores_bad_input(scenario):
    assert claude_post_edit("not json", scenario.dev_b) == (0, "")
```

- [ ] **Step 2: Run** `pytest tests/test_init_hook.py -v` — Expected: FAIL.
- [ ] **Step 3: Implement** `init.py`, `hook.py`, templates (read with `importlib.resources.files("changetrace") / "templates"`), CLI wiring.
- [ ] **Step 4: Run** `pytest -v` — Expected: PASS.
- [ ] **Step 5: Manual check, Claude Code** — in a scratch clone with `ct init --claude-hooks`, ask Claude Code to "set RETRY_DELAY_SECONDS back to 2"; expected: after the edit, Claude reports the CTX-001 conflict.
- [ ] **Step 6: Manual check, Copilot CLI** — same clone, same prompt in Copilot CLI; expected: it loads the skill (confirm it reads `.agents/skills/`; if not, add the folder it does read to `init_repo` and the test) and runs `ct why`/`ct check` before or after editing.
- [ ] **Step 7: Commit** — `git add -A && git commit -m "feat: ct init, shared skill, Claude Code hook"`

---

## Part B — GitHub and Slack (must-have)

### Task 9: Deploy report and dev-since

**Files:**
- Create: `src/changetrace/deploy.py`
- Modify: `src/changetrace/cli.py` (add `deploy report`, `dev-since`)
- Test: `tests/test_deploy.py`

**Interfaces:**
- Consumes: `GitHub`, `gitops.rev_list/is_ancestor/git`, `records.load_records`.
- Produces:
  - `@dataclass DeployReport(env: str, sha: str, run_number: str | None, prev_sha: str | None, commits: list[str], prs: list[dict], records: list[Record], created_at: str | None)`
  - `build_deploy_report(repo: Path, env: str, sha: str, gh: GitHub, run_number: str | None = None) -> DeployReport` — `prev_sha` = newest deployment in `env` with state `success` whose sha ≠ `sha` and `is_ancestor(prev, sha)` (non-ancestors — e.g. after a demo reset — are skipped); `commits = rev_list(prev_sha, sha)`; `prs` = unique by number over `prs_for_commit` of each commit; `records` = records whose file appears in `git diff --name-only prev..sha -- .context/` (all records if `prev_sha` is None).
  - `parse_since(text: str, now: datetime) -> datetime` — `yesterday` (start of yesterday, local), `Nd`, `Nh`, ISO date.
  - `dev_since(repo: Path, since: datetime, env: str, gh: GitHub) -> list[DeployReport]` — one report per successful deployment created after `since`, oldest first.
  - `format_report_text(r: DeployReport) -> str` / `format_report_markdown(r: DeployReport) -> str` (for `$GITHUB_STEP_SUMMARY`).
  - CLI `ct deploy report --env dev --sha SHA [--run-number N]`: builds report, appends markdown to `$GITHUB_STEP_SUMMARY` if set, posts Slack (Task 10) using `SLACK_WEBHOOK_URL`. `ct dev-since WHEN [--env dev]` prints text.
  - Plan decision: the deployment's own status is owned by Actions; the report goes to the job summary and Slack, not to the deployment status description (adjusts spec §6.6 step 3).

- [ ] **Step 1: Write the failing tests** — using `scenario` + `FakeGh`:
  - `test_report_includes_ctx001_and_pr`: after `dev_a_ships_ctx001`, previous successful deployment at the initial commit, current = `main` HEAD → `records` ids `["CTX-001"]`, `prs` numbers `[1]`.
  - `test_report_first_deployment_takes_all`: no deployments → `prev_sha is None` and all records included.
  - `test_report_skips_non_ancestor_prev`: previous deployment sha `"deadbeef…"` (unknown) → treated as none.
  - `test_parse_since`: `parse_since("yesterday", datetime(2026,11,18,15))` → `datetime(2026,11,17,0,0)`; `"2d"` → minus 48h; `"2026-11-01"` → that date.
  - `test_dev_since_orders_oldest_first`.
- [ ] **Step 2: Run** `pytest tests/test_deploy.py -v` — Expected: FAIL.
- [ ] **Step 3: Implement `deploy.py`** and CLI commands.
- [ ] **Step 4: Run** `pytest -v` — Expected: PASS.
- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat: deploy report and dev-since"`

### Task 10: Slack notifications

**Files:**
- Create: `src/changetrace/slack/__init__.py`, `src/changetrace/slack/notify.py`
- Modify: `src/changetrace/cli.py` (add `notify slack pr`; wire Slack into `deploy report`)
- Test: `tests/test_slack.py`

**Interfaces:**
- Produces:
  - `pr_payload(pr: dict, records: list[Record], findings: list[Finding], repo_url: str) -> dict` — Block Kit: header `PR #<n> · <title>`, context `<author> · <project>`, one section per record: `*<id> · <title>*\n<Decided>\n:warning: Watch out: <Watch out>`, conflicts line if any; `text` fallback = header.
  - `deploy_payload(report: DeployReport, project: str, repo_url: str) -> dict` — header `Dev deployment #<run_number or short sha>`, lines `PR #n · title`, `Linked context: CTX-001 Immediate retry`, `Known consideration: <Watch out>` per record.
  - `post_webhook(url: str | None, payload: dict, opener: Callable = urllib.request.urlopen) -> bool` — `None`/empty → print `Slack not configured — skipped`, return `False`; HTTP error → print `Slack post failed: <status>` and return `False` (never raise).
  - CLI `ct notify slack pr --pr N`: `gh` PR details, records added/changed in `base...HEAD` under `.context/`, `run_check` findings → `post_webhook(os.environ.get("SLACK_WEBHOOK_URL"), …)`.

- [ ] **Step 1: Write the failing tests** — `test_pr_payload_mentions_ctx_and_watch_out`, `test_deploy_payload_lists_pr_and_ctx`, `test_post_webhook_skips_without_url` (returns False, opener not called), `test_post_webhook_posts_json` (captured request body is the payload JSON, content-type `application/json`), `test_post_webhook_swallow_http_error`.
- [ ] **Step 2: Run** `pytest tests/test_slack.py -v` — Expected: FAIL.
- [ ] **Step 3: Implement `notify.py`** and CLI wiring.
- [ ] **Step 4: Run** `pytest -v` — Expected: PASS.
- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat: Slack PR and deploy notifications"`

### Task 11: Workflow templates, demo worker template, tool CI

**Files:**
- Create: `src/changetrace/templates/workflows/changetrace-pr.yml`, `templates/workflows/deploy-dev.yml`, `demo/worker/` (`worker/__init__.py`, `worker/config.py`, `worker/retry.py`, `tests/test_retry.py`, `README.md`, plus output of `ct init --project "Worker service" --claude-hooks --github` with `.context/config.yml` `github: balkars/changetrace-demo-worker`), `.github/workflows/ci.yml`
- Test: `tests/test_workflows.py`

**Interfaces:**
- `changetrace-pr.yml`: `on: pull_request: types [opened, synchronize, reopened, ready_for_review]`; `permissions: contents: read, pull-requests: write`; steps: checkout `fetch-depth: 0`; setup-python 3.12; `pip install "changetrace @ git+https://github.com/balkars/changetrace@main"`; `ct validate`; `ct check --base origin/${{ github.base_ref }} --format markdown > ct.md || echo conflict > ct.failed`; sticky comment via `gh pr comment ${{ github.event.pull_request.number }} --body-file ct.md --edit-last || gh pr comment … --body-file ct.md`; on `opened`/`ready_for_review` only: `ct notify slack pr --pr ${{ github.event.pull_request.number }}` with `SLACK_WEBHOOK_URL: ${{ secrets.SLACK_WEBHOOK_PRS }}`; final step `test ! -f ct.failed`. `GH_TOKEN: ${{ github.token }}` on gh steps.
- `deploy-dev.yml`: `on: push: branches [main]` + `workflow_dispatch`; job `deploy` with `environment: dev`, `permissions: contents: read, deployments: read, pull-requests: read`; steps: checkout `fetch-depth: 0`; setup-python; install ct + `pytest`; step named `Deploy (stand-in — replace with the real deploy)` runs `pytest -q` and `python -m worker.retry --smoke`; `ct deploy report --env dev --sha ${{ github.sha }} --run-number ${{ github.run_number }}` with `GH_TOKEN` and `SLACK_WEBHOOK_URL: ${{ secrets.SLACK_WEBHOOK_DEV }}`.
- `demo/worker/worker/retry.py`: `retry_delay() -> int` returns `config.RETRY_DELAY_SECONDS`; `--smoke` prints `retry delay: <n>s` and exits 0. `tests/test_retry.py::test_recovers_without_delay` asserts `retry_delay() == RETRY_DELAY_SECONDS` (stays green for either value — the demo's argument lives in the records, not a failing test).
- `ci.yml` (tool repo): matrix `ubuntu-latest`, `windows-latest`; Python 3.11 and 3.13; `pip install -e .[dev,slack]`; `pytest -q`.

- [ ] **Step 1: Write the failing tests** — `test_pr_workflow_shape` (YAML loads; job has steps running `ct validate` and `ct check --base`; Slack step uses `secrets.SLACK_WEBHOOK_PRS`), `test_deploy_workflow_shape` (`environment: dev`, step name contains `stand-in`, `ct deploy report` uses `github.run_number`), `test_demo_worker_template_initialised` (template contains both SKILL.md copies, identical, and `.context/config.yml` with `github: balkars/changetrace-demo-worker`), `test_demo_worker_tests_pass` (runs `pytest` in a copy of `demo/worker` → exit 0).
- [ ] **Step 2: Run** `pytest tests/test_workflows.py -v` — Expected: FAIL.
- [ ] **Step 3: Write the templates, demo worker, and `ci.yml`.**
- [ ] **Step 4: Run** `pytest -v` — Expected: PASS.
- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat: GitHub workflows, demo worker template, CI"`

---

## Part C — Real services and rehearsal (must-have)

### Task 12: Publish, connect Slack, reset script, rehearsal

**Files:**
- Create: `scripts/demo_reset.py`, `scripts/demo-env.ps1`, `slack/manifest.yml`, `docs/demo/meeting-script.md`, `demo/hub.yml`
- Test: `tests/test_demo_reset.py`

**Interfaces:**
- `scripts/demo_reset.py [--owner balkars] [--no-push] [--run-dir demo-run]`, entry `main(argv: list[str] | None = None, remote_for: Callable[[str], str] | None = None) -> int` (`remote_for(name)` returns the clone/push URL; default `https://github.com/<owner>/changetrace-demo-<name>.git`):
  - For each template in `demo/` (`worker`, and `api` once Task 13 exists): copy to a temp dir, `git init -b main`, single commit `Initial state` by `ChangeTrace Demo`, and unless `--no-push`: `git push --force` to `https://github.com/<owner>/changetrace-demo-<name>.git` `main`; delete other remote branches; close open PRs (`gh pr list --state open --json number` → `gh pr close`); mark all deployments inactive and delete them (`gh api -X POST …/statuses -f state=inactive`, `gh api -X DELETE …/deployments/<id>`).
  - Recreate `demo-run/devA` and `demo-run/devB` (fresh clones of the worker repo; local `user.name` `Dev A` / `Dev B`), and `demo-run/api` for the vault.
  - Never touches `balkars/changetrace`.
- `scripts/demo-env.ps1`: prepends `<repo>\.venv\Scripts` to `$env:PATH` for the current PowerShell session.
- `slack/manifest.yml`: app `ChangeTrace`; Socket Mode on; bot scopes `chat:write`, `commands`, `app_mentions:read`, `incoming-webhook`; slash command `/ct` ("why KEY | dev-since WHEN"); event `app_mention`.
- `demo/hub.yml`: `repos: [{name: Worker service, path: demo-run/devB, github: balkars/changetrace-demo-worker}, {name: API service, path: demo-run/api, github: balkars/changetrace-demo-api}]`.
- `docs/demo/meeting-script.md`: spec §6.9 steps with the exact prompts — Dev A: *"Failed jobs take too long to recover. Find why and fix it."*; Dev B: *"Retries are hammering the payments API. Set RETRY_DELAY_SECONDS back to 2."* — the commands to run between steps, what each screen should show, and the cut rule (skip any step whose feature isn't built).

- [ ] **Step 1: Write the failing test** — `test_reset_no_push_builds_clones(tmp_path)`: run `demo_reset.main(["--run-dir", str(tmp_path/"run")], remote_for=lambda n: str(bare_repo_for(n)))` against local bare repos created in the test (GitHub cleanup calls are skipped when the remote is not a `github.com` URL); expect `run/devA/worker/config.py` default `2`, `run/devA/.context/decisions` has no records, `git -C run/devB log --oneline` has 1 commit.
- [ ] **Step 2: Run** `pytest tests/test_demo_reset.py -v` — Expected: FAIL. Then implement, run again — Expected: PASS. Commit.
- [ ] **Step 3: Owner approval — create repos.** Ask the owner: "Create public repos `balkars/changetrace` and `balkars/changetrace-demo-worker` now?" On yes: `gh repo create balkars/changetrace --public --source . --push`; `gh repo create balkars/changetrace-demo-worker --public`. Confirm the tool CI run is green: `gh run list -R balkars/changetrace -L 1` → `completed success`.
- [ ] **Step 4: Owner action — Slack app.** Owner creates the app from `slack/manifest.yml` in the team workspace, installs it, creates incoming webhooks for `#engineering-prs` and `#engineering-dev`, and adds repo secrets themselves: `gh secret set SLACK_WEBHOOK_PRS -R balkars/changetrace-demo-worker` and `… SLACK_WEBHOOK_DEV …` (they paste the values). Bot and app tokens go into a local `.env` (gitignored) for Task 14.
- [ ] **Step 5: First live run** — `python scripts/demo_reset.py`; verify `gh api repos/balkars/changetrace-demo-worker/environments` lists `dev` after the first push-triggered `deploy-dev` run, and `#engineering-dev` received the digest.
- [ ] **Step 6: Full rehearsal** — run `docs/demo/meeting-script.md` end to end with Claude Code in `demo-run/devA` and Copilot CLI in `demo-run/devB`. Pass criteria: PR comment shows CTX-001; `#engineering-prs` and `#engineering-dev` messages arrive; Dev B's assistant names CTX-001 and its *Watch out* before the edit stands; `ct why RETRY_DELAY_SECONDS` in `devB` shows PR and dev deployment. Record the screen as the fallback video. Fix anything that failed, reset, rehearse again until one clean run.
- [ ] **Step 7: Commit** — `git add -A && git commit -m "feat: demo reset, Slack manifest, meeting script"` and push.

---

## Part D — Should-have (only after Task 12 passes)

### Task 13: Obsidian vault builder and API demo repo

**Files:**
- Create: `src/changetrace/vault.py`, `demo/api/` (`api/settings.yaml` with `rate_limit.requests_per_minute: 120`, `.context/` initialised with one committed record `CTX-001 Raise API rate limit` guarding `rate_limit.requests_per_minute` expect `120` previous `60`, `github: balkars/changetrace-demo-api`)
- Modify: `src/changetrace/cli.py` (add `vault build`), `scripts/demo_reset.py` (include `api`)
- Test: `tests/test_vault.py`

**Interfaces:**
- Produces:
  - `@dataclass HubRepo(name: str, path: Path | None, github: str | None)`; `load_hub(path: Path) -> list[HubRepo]` (relative paths resolve against the hub file's folder's parent repo root).
  - `build_vault(repos: list[HubRepo], out: Path, gh_for: Callable[[str], GitHub | None] = default) -> list[Path]` — writes the spec §6.8 tree. Note names: decisions `"<ID> <Title>.md"` inside `<Project>/Decisions/`. **All wikilinks use full vault paths with an alias** (`[[Worker service/Decisions/CTX-002 Controlled backoff|CTX-002]]`) because IDs repeat across repos. `Keys/<KEY>.md` and `Files/<path with / → ->.md` are hubs listing linking records across projects. Front matter of each decision note = the record's front matter + `project: <name>`. First body line: `> Generated from <github or path>@<short sha> — edit in the repository, not here.` plus `Source: <GitHub blob URL at implementing commit>`. Deployment notes only when `gh` is available. `Dashboards/Decisions.md` = Markdown tables (Active / Superseded) per project; `Dashboards/Decisions.base` = Bases YAML with views *Active decisions* (`status == "active"`) and *Superseded* — check the syntax against Obsidian's Bases help before writing.
  - Ownership: writes `.changetrace-vault` marker at `out`; on rebuild deletes only folders that `build_vault` creates (`Engineering overview.md`, project folders, `Keys`, `Files`, `Dashboards`) and only if the marker exists; refuses (`ValueError`) to build into a non-empty folder without the marker.
  - CLI `ct vault build --hub demo/hub.yml --out <dir>`.

- [ ] **Step 1: Write the failing tests** — `test_vault_tree` (two HubRepos from scenario clones → expected files exist), `test_vault_links_are_path_qualified` (CTX-001 note in Worker contains `[[Worker service/Decisions/CTX-002 Controlled backoff|CTX-002]]` after a supersede), `test_key_hub_lists_both_records`, `test_vault_preserves_user_notes` (a user file `My notes.md` at `out` survives rebuild), `test_vault_refuses_foreign_folder`.
- [ ] **Step 2: Run** `pytest tests/test_vault.py -v` — Expected: FAIL. Implement. Run — Expected: PASS.
- [ ] **Step 3: Owner approval — create** `balkars/changetrace-demo-api` (public). Re-run `demo_reset.py`; `ct vault build --hub demo/hub.yml --out "<vault dir>"`; open in Obsidian: graph shows CTX-001 → CTX-002 chain, both projects, key hub; dashboard renders.
- [ ] **Step 4: Commit** — `git add -A && git commit -m "feat: Obsidian vault builder and API demo repo"`

### Task 14: Slack query bot

**Files:**
- Create: `src/changetrace/slack/bot.py`
- Modify: `src/changetrace/cli.py` (add `slack-bot --hub`), `docs/demo/meeting-script.md` (add bot step)
- Test: `tests/test_bot.py`

**Interfaces:**
- Produces:
  - `parse_query(text: str) -> tuple[Literal["why", "dev-since", "help"], str]` — `why KEY`, `dev-since WHEN`; free text: first token matching `[A-Z][A-Z0-9_]{2,}` or containing `#` → `why`; else `help`.
  - `handle_query(text: str, hub: list[HubRepo], gh_for: Callable[[str], GitHub | None], now: datetime) -> dict` — Block Kit payload; `why` searches every hub repo and labels results by project; no result → `No decisions found for <KEY>.`
  - `create_app(hub: list[HubRepo]) -> slack_bolt.App` — `/ct` command and `app_mention` both `ack()` then respond with `handle_query`; Socket Mode handler started by `ct slack-bot --hub demo/hub.yml` using `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN` from env or `.env`; exits with a clear message if either is missing.
- [ ] **Step 1: Write the failing tests** — `test_parse_query` cases (`"why RETRY_DELAY_SECONDS"`, `"<@U1> why is RETRY_DELAY_SECONDS 0?"` → `why, RETRY_DELAY_SECONDS`; `"dev-since yesterday"`; `"hello"` → help), `test_handle_why_across_repos` (scenario clone + api template → result names "Worker service" and CTX-001), `test_handle_unknown_key`.
- [ ] **Step 2: Run** `pytest tests/test_bot.py -v` — Expected: FAIL. Implement. Run — Expected: PASS.
- [ ] **Step 3: Live check** — `ct slack-bot --hub demo/hub.yml`; in Slack `/ct why RETRY_DELAY_SECONDS` and `@ChangeTrace why is RETRY_DELAY_SECONDS 0?` both answer within 3 s.
- [ ] **Step 4: Final rehearsal** — full meeting script including vault and bot steps; one clean run; update the fallback recording.
- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat: Slack query bot"` and push.
