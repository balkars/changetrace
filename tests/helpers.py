"""Shared test helpers and constants (importable via pytest pythonpath)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from changetrace.gitops import git

CONFIG_PY = (
    "import os\n"
    "\n"
    "# Delay before retrying a failed job, in seconds.\n"
    'RETRY_DELAY_SECONDS = int(os.getenv("RETRY_DELAY_SECONDS", 2))\n'
    'MAX_RETRIES = int(os.getenv("MAX_RETRIES", 5))\n'
)

CTX001_RECORD = """\
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
"""

CTX001_DECIDED = "Default retry delay is 0 (immediate retry)."


def ctx001_draft(decided: str = CTX001_DECIDED) -> str:
    return f"""\
---
title: Immediate retry for failed jobs
---

## Problem
The two-second wait before retrying delayed failed-job recovery.

## Decided
{decided}

## Tried and ruled out
Keeping the delay and changing retry handling in the queue consumer — more code, same effect.

## Assumptions
Immediate retry is safe under current downstream behaviour.

## Watch out
Restoring 2 reintroduces slow recovery. Immediate retries can burst against an unavailable downstream dependency.
"""


CTX001_DRAFT = ctx001_draft()


@dataclass
class Scenario:
    origin: Path
    dev_a: Path
    dev_b: Path


def write(repo: Path, rel: str, text: str) -> None:
    p = Path(repo) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def commit_all(repo: Path, msg: str) -> str:
    git(repo, "add", "-A")
    git(repo, "commit", "-m", msg)
    return git(repo, "rev-parse", "HEAD")


def set_retry(repo: Path, value: str) -> None:
    p = Path(repo) / "worker" / "config.py"
    text = p.read_text(encoding="utf-8")
    new = re.sub(r'("RETRY_DELAY_SECONDS", )[^)]*\)', lambda m: f"{m.group(1)}{value})", text)
    write(repo, "worker/config.py", new)


def finish_and_merge(s: Scenario) -> None:
    """Dev A commits on the current branch, merges it into main (--no-ff), pushes; Dev B pulls."""
    a = s.dev_a
    branch = git(a, "rev-parse", "--abbrev-ref", "HEAD")
    git(a, "add", "-A")
    if git(a, "status", "--porcelain"):
        git(a, "commit", "-m", f"work on {branch}")
    if branch != "main":
        git(a, "checkout", "main")
        git(a, "merge", "--no-ff", "-m", f"merge {branch}", branch)
    git(a, "push", "origin", "main")
    git(s.dev_b, "pull")


def dev_a_ships_ctx001(s: Scenario, decided: str = CTX001_DECIDED) -> None:
    """Dev A changes the retry delay to 0, records CTX-001 from the diff, and ships it."""
    from changetrace.capture import capture

    a = s.dev_a
    git(a, "checkout", "-b", "fix/immediate-retry")
    set_retry(a, "0")
    capture(a, ctx001_draft(decided), from_diff=True)
    finish_and_merge(s)
