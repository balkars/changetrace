"""Deterministic conflict check: compare the working tree against active records' guards."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Literal

from .config import load_config
from .extractors import extract_value, values_equal
from .gitops import base_ref, changed_files, git, read_at, to_repo_path
from .records import CONTEXT_DIR, Record, load_records, parse_record


APPEND_ONLY = "records are append-only — use ct supersede"


@dataclass
class Finding:
    kind: Literal["conflict", "resolved", "warning", "info"]
    record_id: str
    file: str
    message: str
    key: str | None = None
    current: str | None = None


def has_conflict(findings: list[Finding]) -> bool:
    return any(f.kind == "conflict" for f in findings)


def _text(repo: Path, rel: str, staged: bool) -> str | None:
    if staged:
        t = read_at(repo, "", rel)
    else:
        try:
            t = (Path(repo) / rel).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None
    return None if t is None else t.replace("\r\n", "\n").lstrip("﻿")


def _is_record_path(rel: str) -> bool:
    return rel.endswith(".md") and rel.startswith((f"{CONTEXT_DIR}/decisions/", f"{CONTEXT_DIR}/observations/"))


def _current_records(repo: Path, staged: bool) -> list[tuple[str, Record]]:
    if not staged:
        return [(Path(r.path).relative_to(repo).as_posix(), r) for r in load_records(repo)]
    out = []
    for rel in git(repo, "ls-files", CONTEXT_DIR).splitlines():
        text = _text(repo, rel, True) if _is_record_path(rel) else None
        if text is not None:
            out.append((rel, parse_record(text, repo / rel)))
    return sorted(out, key=lambda x: x[1].id)


def _frozen(rec: Record) -> Record:
    return replace(rec, status="", superseded_by=None, path=None)


def run_check(repo: Path, base: str | None = None, staged: bool = False,
              file: str | None = None) -> list[Finding]:
    repo = Path(repo).resolve()
    if base is None:
        base = base_ref(repo, load_config(repo).base_branch)
    ref = base or "HEAD"
    diff = set(changed_files(repo, base, staged))
    scope = {to_repo_path(repo, file)} & diff if file is not None else diff

    current = _current_records(repo, staged)
    present = {rel for rel, _ in current}
    changed = [r for rel, r in current if rel in diff]
    findings: list[Finding] = []

    def old_of(rel: str) -> Record | None:
        text = read_at(repo, ref, rel)
        return parse_record(text, repo / rel) if text is not None else None

    # (record, old-at-ref, path, still present)
    items: list[tuple[Record, Record | None, str, bool]] = []
    for rel, rec in current:
        items.append((rec, old_of(rel) if rel in diff else None, rel, True))
    for rel in sorted(diff - present):
        old = old_of(rel) if _is_record_path(rel) else None
        if old is not None:
            items.append((old, old, rel, False))
            if rel in scope or file is None:
                findings.append(Finding("conflict", old.id, rel, APPEND_ONLY))

    for rec, old, rel, exists in items:
        was_active = old is not None and old.status == "active"
        live = rec.status == "active" or was_active
        if exists and old is not None:
            if _frozen(old) != _frozen(rec) and (file is None or rel in scope):
                findings.append(Finding("conflict", rec.id, rel, APPEND_ONLY))
            if was_active and rec.status not in ("active", "superseded"):
                findings.append(Finding(
                    "conflict", rec.id, rel,
                    f"status of {rec.id} changed from active to {rec.status} — use ct supersede"))
        guards = old.guards if old is not None else rec.guards
        guarded_files = {g.file.replace("\\", "/") for g in guards}

        def resolver() -> str | None:
            for c in changed:
                if c.id != rec.id and rec.id in c.supersedes and exists and (
                        rec.status == "active"
                        or (rec.status == "superseded" and rec.superseded_by == c.id)):
                    return c.id
            return None

        if exists and was_active and rec.status == "superseded" and resolver() is None                 and (file is None or rel in scope):
            findings.append(Finding(
                "conflict", rec.id, rel,
                f"{rec.id} marked superseded without a superseding record — use ct supersede"))

        for g in guards:
            gfile = g.file.replace("\\", "/")
            if not live or gfile not in scope:
                continue
            text = _text(repo, gfile, staged)
            got = extract_value(gfile, text, g.key) if text is not None else None
            by = resolver()
            if got is None or got.status == "missing":
                if by:
                    findings.append(Finding(
                        "resolved", rec.id, gfile, f"superseded by {by} in this change", g.key))
                else:
                    findings.append(Finding(
                        "conflict", rec.id, gfile,
                        f"guarded key removed: {g.key} is no longer in {gfile}", g.key))
                continue
            if got.status == "unreadable":
                findings.append(Finding(
                    "warning", rec.id, gfile, f"cannot verify — read {rec.id}", g.key))
                continue
            if values_equal(got.value, g.expect):
                continue
            if by:
                findings.append(Finding(
                    "resolved", rec.id, gfile, f"superseded by {by} in this change",
                    g.key, got.value))
                continue
            msg = f"changes {g.key} from {g.expect} to {got.value}"
            if g.previous is not None and values_equal(got.value, g.previous):
                msg += f" — this restores the value {rec.id} moved away from"
            findings.append(Finding("conflict", rec.id, gfile, msg, g.key, got.value))

        if exists and rec.status == "active":
            for t in rec.touches:
                tfile = t.split("#", 1)[0].replace("\\", "/")
                if tfile in scope and tfile not in guarded_files:
                    findings.append(Finding(
                        "info", rec.id, tfile, f"relevant: {rec.id} {rec.title}"))
                    break
    reported = {f.record_id for f in findings}
    for rel, rec in current:
        if (rel in diff and rec.kind == "decision" and rec.status == "active"
                and rec.id not in reported and old_of(rel) is None):
            findings.append(Finding("info", rec.id, rel, f"new decision: {rec.id} {rec.title}"))
    return findings


def _decided_watch(rec: Record | None) -> tuple[str, str]:
    if rec is None:
        return "", ""
    return rec.section("Decided"), rec.section("Watch out")


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def format_text(findings: list[Finding], records: dict[str, Record]) -> str:
    out: list[str] = []
    for f in findings:
        rec = records.get(f.record_id)
        if f.kind == "conflict":
            out.append(f"✗ {f.file} — {f.message}")
            if rec:
                out.append(f"  {rec.id} · {rec.author} · {rec.created}: {rec.title}")
                decided, watch = _decided_watch(rec)
                if decided:
                    out.append(f"  Decided: {decided}")
                if watch:
                    out.append(f"  Watch out: {watch}")
        elif f.kind == "resolved":
            out.append(f"✓ {f.file} — {f.record_id} {f.message}")
        elif f.kind == "warning":
            out.append(f"! {f.file} — {f.message}")
        else:
            out.append(f"i {f.file} — {f.message}")
    n = sum(1 for f in findings if f.kind == "conflict")
    out.append(f"{n} conflict(s)" if n else "no conflicts")
    return "\n".join(out) + "\n"


def format_json(findings: list[Finding]) -> str:
    return json.dumps([asdict(f) for f in findings], indent=2, ensure_ascii=False)


def format_markdown(findings: list[Finding], records: dict[str, Record]) -> str:
    linked = len({f.record_id for f in findings})
    n = sum(1 for f in findings if f.kind == "conflict")
    lines = ["### ChangeTrace", "",
             f"{_plural(linked, 'linked decision')} · {_plural(n, 'conflict')}", ""]
    marks = {"conflict": "✗", "resolved": "✓", "warning": "!", "info": "i"}
    for f in findings:
        rec = records.get(f.record_id)
        title = f" {rec.title}" if rec else ""
        line = f"- {marks[f.kind]} **{f.record_id}**{title} — `{f.file}`: {f.message}"
        decided, watch = _decided_watch(rec)
        if decided:
            line += f"\n  - *Decided:* {decided}"
        if watch:
            line += f"\n  - *Watch out:* {watch}"
        lines.append(line)
    return "\n".join(lines) + "\n"
