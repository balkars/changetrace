"""Repository validation for CI: records parse, link up, and match their guards."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .capture import scan_secrets
from .extractors import extract_value, values_equal
from .gitops import to_repo_path
from .records import CONTEXT_DIR, KINDS, Record, RecordError, parse_record

SKILL_COPIES = (".agents/skills/changetrace/SKILL.md", ".claude/skills/changetrace/SKILL.md")


@dataclass
class Problem:
    path: str
    message: str


def _check_guards(repo: Path, rel: str, rec: Record, out: list[Problem]) -> None:
    for g in rec.guards:
        try:
            f = repo / to_repo_path(repo, g.file)
            text = f.read_text(encoding="utf-8-sig") if f.is_file() else None
        except (ValueError, UnicodeDecodeError):
            text = None
        found = extract_value(g.file, text, g.key) if text is not None else None
        if found is None or found.status == "missing":
            out.append(Problem(rel, f"guard {g.key} missing in {g.file}"))
        elif found.status == "found" and not values_equal(g.expect, found.value):
            out.append(Problem(rel, f"guard {g.key} expects {g.expect}, found {found.value}"))


def validate_repo(repo: Path) -> list[Problem]:
    repo = Path(repo)
    problems: list[Problem] = []
    parsed: list[tuple[str, Record]] = []
    for _, sub in KINDS.values():
        d = repo / CONTEXT_DIR / sub
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.md")):
            rel = f.relative_to(repo).as_posix()
            try:
                text = f.read_text(encoding="utf-8")
                rec = parse_record(text, f)
            except UnicodeDecodeError:
                problems.append(Problem(rel, "parse error: not valid UTF-8"))
                continue
            except RecordError as e:
                problems.append(Problem(rel, f"parse error: {e}"))
                continue
            parsed.append((rel, rec))
            for line_no, _name in scan_secrets(text):
                problems.append(Problem(rel, f"possible secret on line {line_no}"))

    by_id: dict[str, Record] = {}
    for rel, rec in parsed:
        if rec.id in by_id:
            problems.append(Problem(rel, f"duplicate id {rec.id}"))
        else:
            by_id[rec.id] = rec
    for rel, rec in parsed:
        for sid in rec.supersedes:
            if sid not in by_id:
                problems.append(Problem(rel, f"supersedes unknown {sid}"))
        if rec.superseded_by and rec.id not in getattr(by_id.get(rec.superseded_by), "supersedes", []):
            problems.append(Problem(rel, f"superseded_by {rec.superseded_by} does not supersede {rec.id}"))
        if rec.kind == "decision" and rec.status == "active":
            _check_guards(repo, rel, rec, problems)

    copies = [repo / p for p in SKILL_COPIES]
    if all(c.is_file() for c in copies) and copies[0].read_bytes() != copies[1].read_bytes():
        problems.append(Problem(SKILL_COPIES[1], "skill copies differ"))
    return problems
