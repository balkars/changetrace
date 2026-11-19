"""`ct init`: set a repository up for ChangeTrace. Writes only inside the repository."""
from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path

from .records import CONTEXT_DIR

SKILL_DIRS = (".agents/skills/changetrace", ".claude/skills/changetrace")
POINTER_FILES = ("AGENTS.md", "CLAUDE.md", ".github/copilot-instructions.md")
POINTER_MARK = ".agents/skills/changetrace"
HOOK_COMMAND = "ct hook claude"


def _template(*parts: str):
    node = files("changetrace") / "templates"
    for p in parts:
        node = node / p
    return node


def _text(*parts: str) -> str:
    return _template(*parts).read_text(encoding="utf-8")


def _inside(repo: Path, rel: str) -> Path:
    target = (repo / rel).resolve()
    target.relative_to(repo.resolve())  # raises ValueError if it escapes the repo
    return target


def _write_new(repo: Path, rel: str, text: str, written: list[str]) -> None:
    target = _inside(repo, rel)
    if target.exists():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8", newline="\n")
    written.append(rel)


def _add_pointer(repo: Path, rel: str, line: str, written: list[str]) -> None:
    target = _inside(repo, rel)
    existing = target.read_text(encoding="utf-8-sig") if target.is_file() else ""
    if POINTER_MARK in existing:
        return
    sep = "" if not existing or existing.endswith("\n") else "\n"
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "a", encoding="utf-8", newline="\n") as f:
        f.write(f"{sep}{line}")
    written.append(rel)


def _merge_claude_settings(repo: Path, written: list[str]) -> None:
    rel = ".claude/settings.json"
    target = _inside(repo, rel)
    ours = json.loads(_text("claude-settings.json"))
    if target.is_file():
        try:
            data = json.loads(target.read_text(encoding="utf-8-sig") or "{}")
        except json.JSONDecodeError as e:
            raise ValueError(f"{rel} is not valid JSON: {e}") from e
        if not isinstance(data, dict):
            raise ValueError(f"{rel} must contain a JSON object")
    else:
        data = {}
    post = data.setdefault("hooks", {}).setdefault("PostToolUse", [])
    if any(h.get("command") == HOOK_COMMAND
           for entry in post if isinstance(entry, dict) for h in entry.get("hooks", [])):
        return
    post.extend(ours["hooks"]["PostToolUse"])
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8", newline="\n")
    written.append(rel)


def _copy_workflows(repo: Path, written: list[str]) -> None:
    src = _template("workflows")
    if not src.is_dir():
        return
    for item in sorted(src.iterdir(), key=lambda p: p.name):
        if item.is_file():
            _write_new(repo, f".github/workflows/{item.name}", item.read_text(encoding="utf-8"), written)


def init_repo(repo: Path, project: str | None = None, claude_hooks: bool = False,
              github: bool = False) -> list[str]:
    """Create the ChangeTrace files in `repo`; return the repo-relative paths written."""
    repo = Path(repo)
    written: list[str] = []
    name = project or repo.resolve().name
    _write_new(repo, f"{CONTEXT_DIR}/config.yml", _text("config.yml").replace("__PROJECT__", name), written)
    _write_new(repo, f"{CONTEXT_DIR}/decisions/.gitkeep", "", written)
    _write_new(repo, f"{CONTEXT_DIR}/observations/.gitkeep", "", written)
    skill = _text("SKILL.md")
    for d in SKILL_DIRS:
        _write_new(repo, f"{d}/SKILL.md", skill, written)
    pointer = _text("pointer.md")
    for rel in POINTER_FILES:
        _add_pointer(repo, rel, pointer, written)
    if claude_hooks:
        _merge_claude_settings(repo, written)
    if github:
        _copy_workflows(repo, written)
    return written
