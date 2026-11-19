"""Read side: why / explain / history with linked evidence."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from .config import load_config
from .extractors import extract_value, values_equal
from .github import GitHub, GitHubUnavailable
from .gitops import added_commit, git, is_ancestor, read_at
from .records import Record, load_records

OFFLINE_NOTE = "links unavailable (offline or gh not logged in)"


@dataclass
class Evidence:
    commit: str | None
    prs: list[dict] = field(default_factory=list)
    deployments: list[dict] = field(default_factory=list)
    note: str | None = None


@dataclass
class RecordView:
    record: Record
    current: bool
    chain: list[str]
    evidence: Evidence | None
    observations: list[Record] = field(default_factory=list)


@dataclass
class HistoryEntry:
    when: str
    kind: Literal["value", "record", "deployment"]
    text: str


def _rel(repo: Path, rec: Record) -> str | None:
    if rec.path is None:
        return None
    p = Path(rec.path)
    try:
        return p.relative_to(repo).as_posix()
    except ValueError:
        return p.resolve().relative_to(Path(repo).resolve()).as_posix()


def _deployments_containing(repo: Path, commit: str, gh: GitHub) -> list[dict]:
    found = []
    for env in load_config(repo).environments:
        for d in gh.deployments(env):
            if d["sha"] and is_ancestor(repo, commit, d["sha"]):
                found.append({**d, "env": env})
    return found


def resolve_evidence(repo: Path, rec: Record, gh: GitHub | None) -> Evidence:
    rel = _rel(Path(repo), rec)
    commit = added_commit(repo, rel) if rel else None
    if gh is None:
        return Evidence(commit, note=OFFLINE_NOTE)
    if commit is None:
        return Evidence(None)
    try:
        prs = gh.prs_for_commit(commit)
        deployments = _deployments_containing(repo, commit, gh)
    except GitHubUnavailable:
        return Evidence(commit, note=OFFLINE_NOTE)
    return Evidence(commit, prs, deployments)


def _chain(rec: Record, by_id: dict[str, Record]) -> list[str]:
    ids = [rec.id]
    seen = {rec.id}
    cur = rec
    while cur.supersedes and cur.supersedes[0] in by_id and cur.supersedes[0] not in seen:
        cur = by_id[cur.supersedes[0]]
        seen.add(cur.id)
        ids.insert(0, cur.id)
    cur = rec
    while cur.superseded_by and cur.superseded_by in by_id and cur.superseded_by not in seen:
        cur = by_id[cur.superseded_by]
        seen.add(cur.id)
        ids.append(cur.id)
    return ids


def _with_successors(records: list[Record], by_id: dict[str, Record]) -> list[Record]:
    """Matched records plus everything reachable forward through superseded_by (cycle-safe)."""
    out = {r.id: r for r in records}
    for r in records:
        cur = r
        while cur.superseded_by and cur.superseded_by in by_id and cur.superseded_by not in out:
            cur = by_id[cur.superseded_by]
            out[cur.id] = cur
    return list(out.values())


def _observations_of(rec_id: str, all_records: list[Record]) -> list[Record]:
    return sorted(
        (o for o in all_records if o.kind == "observation" and rec_id in o.about),
        key=lambda o: (o.created, o.id))


def _views(repo: Path, records: list[Record], gh: GitHub | None) -> list[RecordView]:
    all_records = load_records(repo)
    by_id = {r.id: r for r in all_records}
    decisions = [r for r in _with_successors(records, by_id) if r.kind != "observation"]
    ordered = sorted(decisions, key=lambda r: (r.status == "active", r.created, r.id), reverse=True)
    return [
        RecordView(r, r.status == "active", _chain(r, by_id), resolve_evidence(repo, r, gh),
                   _observations_of(r.id, all_records))
        for r in ordered
    ]


def _matches_why(rec: Record, target: str) -> bool:
    for g in rec.guards:
        if target in (g.key, g.file, f"{g.file}#{g.key}"):
            return True
    for t in rec.touches:
        file, _, symbol = t.partition("#")
        if target in (t, file) or (symbol and target == symbol):
            return True
    return False


def why(repo: Path, target: str, gh: GitHub | None = None) -> list[RecordView]:
    repo = Path(repo)
    return _views(repo, [r for r in load_records(repo) if _matches_why(r, target)], gh)


def explain(repo: Path, path: str, gh: GitHub | None = None) -> list[RecordView]:
    repo = Path(repo)
    path = path.replace("\\", "/")
    hits = [
        r for r in load_records(repo)
        if any(t.partition("#")[0] == path for t in r.touches) or any(g.file == path for g in r.guards)
    ]
    return _views(repo, hits, gh)


def _short(sha: str) -> str:
    return sha[:7]


def history(repo: Path, key: str, gh: GitHub | None = None) -> list[HistoryEntry]:
    repo = Path(repo)
    all_records = load_records(repo)
    records = [r for r in all_records if any(g.key == key for g in r.guards)]
    entries: list[HistoryEntry] = []
    change_commits: list[str] = []
    for fname in sorted({g.file for r in records for g in r.guards if g.key == key}):
        log = git(repo, "log", "--format=%H %as", "--", fname, check=False).splitlines()
        prev: str | None = None
        for line in reversed(log):
            sha, when = line.split()
            text = read_at(repo, sha, fname)
            res = extract_value(fname, text, key) if text is not None else None
            if res is None or res.status != "found":
                continue
            if prev is not None and not values_equal(prev, res.value):
                entries.append(HistoryEntry(when, "value", f"{key} {prev} → {res.value} (commit {_short(sha)})"))
                change_commits.append(sha)
            prev = res.value
    shown = [r for r in _with_successors(records, {r.id: r for r in all_records}) if r.kind != "observation"]
    for r in shown:
        entries.append(HistoryEntry(r.created, "record", f"{r.id} {r.title} ({r.status})"))
        for o in _observations_of(r.id, all_records):
            entries.append(HistoryEntry(
                o.created, "record", f"{o.id} {o.title} (observation about {r.id})"))
    if gh is not None and change_commits:
        try:
            for env in load_config(repo).environments:
                deploys = gh.deployments(env)
                for sha in change_commits:
                    first = [d for d in deploys if d["sha"] and is_ancestor(repo, sha, d["sha"])]
                    if first:
                        d = min(first, key=lambda d: d["created_at"])
                        entries.append(HistoryEntry(
                            d["created_at"][:10], "deployment", f"{env} deploy {_short(d['sha'])} ({d['state']})"))
        except GitHubUnavailable:
            pass
    unique = list(dict.fromkeys((e.when, e.kind, e.text) for e in entries))
    return sorted((HistoryEntry(*e) for e in unique), key=lambda e: e.when)


def _evidence_line(ev: Evidence) -> str:
    parts: list[str] = []
    if ev.commit:
        parts.append(f"commit {_short(ev.commit)}")
    parts += [f"PR #{p['number']}" for p in ev.prs]
    parts += [f"{d['env']} deploy {d['created_at'][:10]}" for d in ev.deployments]
    if ev.note:
        parts.append(ev.note)
    return " · ".join(parts) if parts else "none found"


def format_views(views: list[RecordView]) -> str:
    blocks = []
    for v in views:
        r = v.record
        lines = [f"{r.id} · {r.status} · {r.author} · {r.created} — {r.title}"]
        if len(v.chain) > 1:
            lines.append("  Chain: " + " → ".join(v.chain))
        for name in ("Decided", "Watch out"):
            text = r.section(name)
            if text:
                lines.append(f"  {name}: " + text.replace("\n", "\n    "))
        if v.evidence is not None:
            lines.append("  Evidence: " + _evidence_line(v.evidence))
        for o in v.observations:
            where = "".join(f" · {x}" for x in (o.environment, f"deployment {o.deployment}" if o.deployment else "") if x)
            lines.append(f"  Observed: {o.id}{where} — {o.title}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)
