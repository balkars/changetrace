"""Record model: parse, render and load decision/observation records."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

CONTEXT_DIR = ".context"
KINDS = {"decision": ("CTX", "decisions"), "observation": ("OBS", "observations")}
STATUSES = ("proposed", "active", "superseded", "rejected")


class RecordError(ValueError):
    """Raised when a record cannot be parsed or fails validation."""


@dataclass
class Guard:
    file: str
    key: str
    expect: str
    previous: str | None = None


@dataclass
class Record:
    id: str
    kind: str
    title: str
    status: str
    author: str
    created: str
    touches: list[str] = field(default_factory=list)
    guards: list[Guard] = field(default_factory=list)
    supersedes: list[str] = field(default_factory=list)
    superseded_by: str | None = None
    tags: list[str] = field(default_factory=list)
    about: list[str] = field(default_factory=list)
    environment: str | None = None
    deployment: str | None = None
    body: str = ""
    path: Path | None = None

    def section(self, name: str) -> str:
        """Text under the `## name` heading, stripped; "" if absent."""
        lines = self.body.split("\n")
        out: list[str] = []
        inside = False
        for line in lines:
            m = re.match(r"##\s+(.*?)\s*$", line)
            if m and not line.startswith("###"):
                if inside:
                    break
                inside = m.group(1) == name
                continue
            if inside:
                out.append(line)
        return "\n".join(out).strip()


def _normalise(text: str) -> str:
    if text.startswith("\ufeff"):
        text = text[1:]
    return text.replace("\r\n", "\n")


def _str_or_none(v) -> str | None:
    return None if v is None else str(v)


def _str_list(v, field_name: str) -> list[str]:
    if v is None:
        return []
    if not isinstance(v, list):
        raise RecordError(f"'{field_name}' must be a list")
    return [str(x) for x in v]


def parse_record(text: str, path: Path | None = None) -> Record:
    text = _normalise(text)
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        raise RecordError("missing front matter")
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        raise RecordError("unterminated front matter")
    try:
        meta = yaml.safe_load("\n".join(lines[1:end])) or {}
    except yaml.YAMLError as e:
        raise RecordError(f"invalid front matter: {e}") from e
    if not isinstance(meta, dict):
        raise RecordError("front matter must be a mapping")
    body = "\n".join(lines[end + 1:]).strip()

    for req in ("id", "kind", "title", "status"):
        if meta.get(req) in (None, ""):
            raise RecordError(f"missing '{req}'")
    kind = str(meta["kind"])
    if kind not in KINDS:
        raise RecordError(f"unknown kind '{kind}'")
    status = str(meta["status"])
    if status not in STATUSES:
        raise RecordError(f"unknown status '{status}'")
    rid = str(meta["id"])
    if not re.fullmatch(rf"{KINDS[kind][0]}-\d{{3,}}", rid):
        raise RecordError(f"id '{rid}' does not match kind '{kind}'")

    guards: list[Guard] = []
    raw_guards = meta.get("guards") or []
    if not isinstance(raw_guards, list):
        raise RecordError("'guards' must be a list")
    for g in raw_guards:
        if not isinstance(g, dict) or "file" not in g or "key" not in g or "expect" not in g:
            raise RecordError("each guard needs file, key and expect")
        guards.append(Guard(str(g["file"]), str(g["key"]), str(g["expect"]), _str_or_none(g.get("previous"))))

    return Record(
        id=rid,
        kind=kind,
        title=str(meta["title"]),
        status=status,
        author=str(meta.get("author") or ""),
        created=str(meta.get("created") or ""),
        touches=_str_list(meta.get("touches"), "touches"),
        guards=guards,
        supersedes=_str_list(meta.get("supersedes"), "supersedes"),
        superseded_by=_str_or_none(meta.get("superseded_by")),
        tags=_str_list(meta.get("tags"), "tags"),
        about=_str_list(meta.get("about"), "about"),
        environment=_str_or_none(meta.get("environment")),
        deployment=_str_or_none(meta.get("deployment")),
        body=body,
        path=path,
    )


def render_record(rec: Record) -> str:
    meta: dict = {
        "id": rec.id,
        "kind": rec.kind,
        "title": rec.title,
        "status": rec.status,
        "author": rec.author,
        "created": rec.created,
        "touches": list(rec.touches),
        "guards": [
            {"file": g.file, "key": g.key, "expect": g.expect, "previous": g.previous}
            for g in rec.guards
        ],
        "supersedes": list(rec.supersedes),
        "superseded_by": rec.superseded_by,
        "tags": list(rec.tags),
    }
    if rec.about:
        meta["about"] = list(rec.about)
    if rec.environment:
        meta["environment"] = rec.environment
    if rec.deployment:
        meta["deployment"] = rec.deployment
    front = yaml.safe_dump(
        meta, sort_keys=False, allow_unicode=True, default_flow_style=None, width=10_000
    )
    return f"---\n{front}---\n\n{rec.body.strip()}\n"


def load_records(repo: Path) -> list[Record]:
    records: list[Record] = []
    for _, sub in KINDS.values():
        d = Path(repo) / CONTEXT_DIR / sub
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.md")):
            try:
                records.append(parse_record(f.read_text(encoding="utf-8"), f))
            except RecordError as e:
                raise RecordError(f"{f.name}: {e}") from e
    return sorted(records, key=lambda r: r.id)


def next_id(repo: Path, kind: str) -> str:
    if kind not in KINDS:
        raise RecordError(f"unknown kind '{kind}'")
    prefix, sub = KINDS[kind]
    d = Path(repo) / CONTEXT_DIR / sub
    highest = 0
    if d.is_dir():
        for f in d.glob(f"{prefix}-*.md"):
            m = re.match(rf"{prefix}-(\d+)", f.name)
            if m:
                highest = max(highest, int(m.group(1)))
    return f"{prefix}-{highest + 1:03d}"


def slugify(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower())[:40].strip("-")


def record_path(repo: Path, rec: Record) -> Path:
    sub = KINDS[rec.kind][1]
    return Path(repo) / CONTEXT_DIR / sub / f"{rec.id}-{slugify(rec.title)}.md"
