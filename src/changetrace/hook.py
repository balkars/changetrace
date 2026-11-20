"""Claude Code PostToolUse hook: run the conflict check on the edited file."""
from __future__ import annotations

import json
from pathlib import Path

from .check import format_text, has_conflict, run_check
from .gitops import to_repo_path
from .records import load_records


def claude_post_edit(stdin_json: str, repo: Path) -> tuple[int, str]:
    """Return (2, message) when the edit conflicts with a decision or cannot be verified.

    Silent (0, "") only for unparsable hook JSON, a missing file_path, a path outside the
    repo, or no findings. Any other failure is reported, never swallowed.
    """
    try:
        data = json.loads(stdin_json)
        file_path = data["tool_input"]["file_path"]
        if not isinstance(file_path, str) or not file_path:
            return 0, ""
        rel = to_repo_path(repo, file_path)
    except Exception:
        return 0, ""
    try:
        findings = run_check(repo, file=rel)
        if not any(f.kind in ("conflict", "warning") for f in findings):
            return 0, ""
        by_id = {r.id: r for r in load_records(repo)}
        return 2, format_text(findings, by_id)
    except Exception as exc:
        return 2, f"ChangeTrace could not check {rel} ({type(exc).__name__}) — run ct check"


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
