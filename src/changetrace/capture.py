"""Write new records: capture decisions, supersede them, log observations."""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import yaml

from .config import load_config
from .extractors import changed_keys
from .gitops import base_ref, changed_files, git, read_at
from .records import (
    CONTEXT_DIR,
    Guard,
    Record,
    RecordError,
    load_records,
    next_id,
    parse_record,
    record_path,
    render_record,
)


class CaptureError(ValueError):
    """Raised when a draft cannot be stored."""


_SECRET_PATTERNS = [
    (name, re.compile(p))
    for name, p in (
        ("aws-access-key", r"AKIA[0-9A-Z]{16}"),
        ("github-token", r"gh[pousr]_[A-Za-z0-9]{20,}"),
        ("slack-token", r"xox[abposr]-[A-Za-z0-9-]{10,}"),
        ("slack-webhook", r"hooks\.slack\.com/services/\S+"),
        ("private-key", r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
        ("credential-assignment",
         r"(?i)(password|passwd|secret|api[_-]?key|token)\s*[:=]\s*\S{6,}"),
    )
]


def scan_secrets(text: str) -> list[tuple[int, str]]:
    """Return (line number, pattern name) for each line that looks like it holds a secret.

    The matched text itself is never returned, so callers cannot echo it."""
    hits: list[tuple[int, str]] = []
    for n, line in enumerate(text.replace("\r\n", "\n").split("\n"), start=1):
        for name, pattern in _SECRET_PATTERNS:
            if pattern.search(line):
                hits.append((n, name))
                break
    return hits


def guards_from_diff(repo: Path) -> list[Guard]:
    repo = Path(repo)
    base = base_ref(repo, load_config(repo).base_branch) or "HEAD"
    guards: list[Guard] = []
    for path in changed_files(repo, base):
        if path == CONTEXT_DIR or path.startswith(CONTEXT_DIR + "/"):
            continue
        f = repo / path
        if not f.is_file():
            continue
        try:
            new_text = f.read_text(encoding="utf-8").replace("\r\n", "\n")
        except UnicodeDecodeError:
            continue
        old_text = read_at(repo, base, path)
        if old_text is not None:
            old_text = old_text.replace("\r\n", "\n")
        for key, old, new in changed_keys(path, old_text, new_text):
            guards.append(Guard(path, key, new, old))
    return guards


def _split_draft(draft: str) -> tuple[dict, str]:
    lines = draft.lstrip("\ufeff").replace("\r\n", "\n").split("\n")
    if not lines or lines[0].strip() != "---":
        raise CaptureError("draft must start with YAML front matter")
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        raise CaptureError("draft front matter is not closed")
    try:
        meta = yaml.safe_load("\n".join(lines[1:end])) or {}
    except yaml.YAMLError as e:
        raise CaptureError(f"invalid front matter: {e}") from e
    if not isinstance(meta, dict):
        raise CaptureError("front matter must be a mapping")
    return meta, "\n".join(lines[end + 1:]).strip()


def _check_secrets(draft: str) -> None:
    hits = scan_secrets(draft)
    if hits:
        line_no, name = hits[0]
        raise CaptureError(f"draft contains a possible secret (line {line_no}: {name})")


def _check_record_secrets(rec: Record) -> None:
    """Scan the rendered record and each guard value (diff-derived guards bypass the draft scan)."""
    lines = [render_record(rec)]
    for g in rec.guards:
        lines.append(f"{g.key} = {g.expect}")
        if g.previous is not None:
            lines.append(f"{g.key} = {g.previous}")
    _check_secrets("\n".join(lines))


def _author(repo: Path, author: str | None) -> str:
    return author or git(repo, "config", "user.name", check=False) or "unknown"


def _write(rec: Record) -> None:
    rec.path.parent.mkdir(parents=True, exist_ok=True)
    with open(rec.path, "w", encoding="utf-8", newline="\n") as f:
        f.write(render_record(rec))


def _str_list(meta: dict, key: str) -> list[str]:
    v = meta.get(key)
    if v is None:
        return []
    if not isinstance(v, list):
        raise CaptureError(f"'{key}' must be a list")
    return [str(x) for x in v]


def _draft_guards(meta: dict) -> list[Guard]:
    out: list[Guard] = []
    raw = meta.get("guards") or []
    if not isinstance(raw, list):
        raise CaptureError("'guards' must be a list")
    for g in raw:
        if not isinstance(g, dict) or not {"file", "key", "expect"} <= g.keys():
            raise CaptureError("each guard needs file, key and expect")
        prev = g.get("previous")
        out.append(Guard(str(g["file"]), str(g["key"]), str(g["expect"]), None if prev is None else str(prev)))
    return out


def _new_decision(
    repo: Path, draft: str, from_diff: bool, author: str | None, today: date | None
) -> Record:
    repo = Path(repo)
    _check_secrets(draft)
    meta, body = _split_draft(draft)
    title = str(meta.get("title") or "").strip()
    if not title:
        raise CaptureError("draft needs a 'title'")
    status = str(meta.get("status") or "active")
    if status not in ("active", "proposed"):
        raise CaptureError("draft status must be 'active' or 'proposed'")
    rec = Record(
        id=next_id(repo, "decision"),
        kind="decision",
        title=title,
        status=status,
        author=_author(repo, author),
        created=(today or date.today()).isoformat(),
        touches=_str_list(meta, "touches"),
        guards=_draft_guards(meta),
        tags=_str_list(meta, "tags"),
        body=body,
    )
    if not rec.section("Decided"):
        raise CaptureError("draft needs a non-empty '## Decided' section")
    if from_diff:
        for g in guards_from_diff(repo):
            rec.guards.append(g)
            ref = f"{g.file}#{g.key}"
            if ref not in rec.touches:
                rec.touches.append(ref)
    _check_record_secrets(rec)
    rec.path = record_path(repo, rec)
    return rec


def capture(
    repo: Path,
    draft: str,
    from_diff: bool = False,
    author: str | None = None,
    today: date | None = None,
) -> Record:
    rec = _new_decision(repo, draft, from_diff, author, today)
    _write(rec)
    return rec


def supersede(
    repo: Path,
    old_id: str,
    draft: str,
    from_diff: bool = False,
    author: str | None = None,
    today: date | None = None,
) -> Record:
    repo = Path(repo)
    old = next((r for r in load_records(repo) if r.id == old_id), None)
    if old is None:
        raise CaptureError(f"no record {old_id}")
    if old.status != "active":
        raise CaptureError(f"{old_id} is {old.status}, only an active record can be superseded")
    new = _new_decision(repo, draft, from_diff, author, today)
    new.status = "active"
    new.supersedes = [old_id]
    try:
        old_rec = parse_record(old.path.read_text(encoding="utf-8"), old.path)
    except RecordError as e:
        raise CaptureError(str(e)) from e
    old_rec.status = "superseded"
    old_rec.superseded_by = new.id
    _write(new)
    _write(old_rec)
    return new


def observe(
    repo: Path,
    about: list[str],
    env: str,
    deployment: str | None,
    draft: str,
    author: str | None = None,
    today: date | None = None,
) -> Record:
    repo = Path(repo)
    _check_secrets(draft)
    meta, body = _split_draft(draft)
    title = str(meta.get("title") or "").strip()
    if not title:
        raise CaptureError("draft needs a 'title'")
    rec = Record(
        id=next_id(repo, "observation"),
        kind="observation",
        title=title,
        status="active",
        author=_author(repo, author),
        created=(today or date.today()).isoformat(),
        tags=_str_list(meta, "tags"),
        about=list(about),
        environment=env,
        deployment=deployment,
        body=body,
    )
    rec.path = record_path(repo, rec)
    _write(rec)
    return rec
