"""Deterministic conflict check: compare the working tree against active records' guards."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Literal

from .config import load_config
from .extractors import extract_value, values_equal
from .gitops import base_ref, changed_files, read_at, to_repo_path
from .records import Record, parse_record


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


def _read_text(repo: Path, rel: str) -> str | None:
    p = Path(repo) / rel
    try:
        return p.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    except (OSError, UnicodeDecodeError):
        return None


def _rel(repo: Path, rec: Record) -> str | None:
    if rec.path is None:
        return None
    try:
        return to_repo_path(repo, str(rec.path))
    except ValueError:
        return None


def _frozen(rec: Record) -> Record:
    return replace(rec, status="", superseded_by=None, path=None)


def run_check(repo: Path, base: str | None = None, staged: bool = False,
              file: str | None = None) -> list[Finding]:
    from .records import load_records

    repo = Path(repo)
    if base is None:
        base = base_ref(repo, load_config(repo).base_branch)
    ref = base or "HEAD"
    diff = set(changed_files(repo, base, staged))
    scope = {to_repo_path(repo, file)} & diff if file is not None else diff

    records = load_records(repo)
    changed_records = [r for r in records if _rel(repo, r) in diff]
    findings: list[Finding] = []

    for rec in records:
        rel = _rel(repo, rec)
        if rec.status == "active":
            live = True
        elif rec.status == "superseded":
            old = read_at(repo, ref, rel) if rel else None
            live = old is not None and parse_record(old).status == "active"
        else:
            live = False

        guarded_files = {g.file.replace("\\", "/") for g in rec.guards}
        for g in rec.guards:
            gfile = g.file.replace("\\", "/")
            if not live or gfile not in scope:
                continue
            text = _read_text(repo, gfile)
            got = extract_value(gfile, text, g.key) if text is not None else None
            if got is None or got.status == "missing":
                if rec.status == "active":
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
            if rec.status == "superseded":
                findings.append(Finding(
                    "resolved", rec.id, gfile,
                    f"superseded by {rec.superseded_by} in this change", g.key, got.value))
            elif any(rec.id in c.supersedes for c in changed_records):
                by = next(c.id for c in changed_records if rec.id in c.supersedes)
                findings.append(Finding(
                    "resolved", rec.id, gfile,
                    f"superseded by {by} in this change", g.key, got.value))
            else:
                msg = f"changes {g.key} from {g.expect} to {got.value}"
                if g.previous is not None and values_equal(got.value, g.previous):
                    msg += f" — this restores the value {rec.id} moved away from"
                findings.append(Finding("conflict", rec.id, gfile, msg, g.key, got.value))

        if rec.status == "active":
            for t in rec.touches:
                tfile = t.split("#", 1)[0].replace("\\", "/")
                if tfile in scope and tfile not in guarded_files:
                    findings.append(Finding(
                        "info", rec.id, tfile, f"relevant: {rec.id} {rec.title}"))
                    break

    for rec in changed_records:
        rel = _rel(repo, rec)
        if file is not None and rel not in scope:
            continue
        old = read_at(repo, ref, rel)
        if old is not None and _frozen(parse_record(old)) != _frozen(rec):
            findings.append(Finding(
                "conflict", rec.id, rel, "records are append-only — use ct supersede"))
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
