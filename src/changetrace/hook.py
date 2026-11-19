"""Claude Code PostToolUse hook: run the conflict check on the edited file."""
from __future__ import annotations

import json
from pathlib import Path

from .check import format_text, has_conflict, run_check
from .gitops import to_repo_path
from .records import load_records


def claude_post_edit(stdin_json: str, repo: Path) -> tuple[int, str]:
    """Return (2, message) when the edit conflicts with an active decision, else (0, "").

    Never raises: any problem (bad JSON, path outside the repo, git or parse errors) is a silent pass.
    """
    try:
        data = json.loads(stdin_json)
        file_path = data["tool_input"]["file_path"]
        rel = to_repo_path(repo, file_path)
        findings = run_check(repo, file=rel)
        if not has_conflict(findings):
            return 0, ""
        by_id = {r.id: r for r in load_records(repo)}
        return 2, format_text(findings, by_id)
    except Exception:
        return 0, ""


def hook_repo(stdin_json: str, cwd: Path) -> Path:
    """The repo to check: the hook payload's `cwd` if present, else `cwd`."""
    from .gitops import repo_root

    start = cwd
    try:
        c = json.loads(stdin_json).get("cwd")
        if isinstance(c, str) and c:
            start = Path(c)
    except Exception:
        pass
    return Path(repo_root(start)).resolve()
