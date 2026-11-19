"""Deploy report: what a deployment added since the previous successful one."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from .github import GitHub, GitHubUnavailable
from .gitops import git, is_ancestor, rev_list
from .records import CONTEXT_DIR, Record, load_records


_FIRST_DEPLOY_PR_LOOKUPS = 50


@dataclass
class DeployReport:
    env: str
    sha: str
    run_number: str | None
    prev_sha: str | None
    commits: list[str]
    prs: list[dict]
    records: list[Record]
    created_at: str | None
    links_available: bool = field(default=True)


def _local_naive(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone().replace(tzinfo=None)


def _previous_sha(repo: Path, deployments: list[dict], sha: str) -> str | None:
    for d in deployments:  # newest first
        if d["state"] == "success" and d["sha"] != sha and is_ancestor(repo, d["sha"], sha):
            return d["sha"]
    return None


def _changed_records(repo: Path, prev_sha: str | None, sha: str) -> list[Record]:
    records = load_records(repo)
    if prev_sha is None:
        return records
    out = git(repo, "diff", "--name-only", f"{prev_sha}..{sha}", "--", f"{CONTEXT_DIR}/")
    changed = {ln.strip() for ln in out.splitlines() if ln.strip()}
    root = Path(repo).resolve()
    return [r for r in records if r.path and Path(r.path).resolve().relative_to(root).as_posix() in changed]


def build_deploy_report(repo: Path, env: str, sha: str, gh: GitHub | None, run_number: str | None = None,
                        *, _deployments: list[dict] | None = None) -> DeployReport:
    links = gh is not None
    deployments: list[dict] = []
    if gh is not None:
        try:
            deployments = _deployments if _deployments is not None else gh.deployments(env)
        except GitHubUnavailable:
            links = False
    prev_sha = _previous_sha(repo, deployments, sha)
    commits = rev_list(repo, prev_sha, sha)
    prs: list[dict] = []
    if links and gh is not None:
        seen: set = set()
        # A first deployment has no lower bound: look up PRs only for the newest commits.
        lookup = commits if prev_sha else commits[:_FIRST_DEPLOY_PR_LOOKUPS]
        try:
            for c in lookup:
                for p in gh.prs_for_commit(c):
                    if p["number"] not in seen:
                        seen.add(p["number"])
                        prs.append(p)
        except GitHubUnavailable:
            links, prs = False, []
    created = next((d["created_at"] for d in deployments if d["sha"] == sha and d["created_at"]), None)
    return DeployReport(env, sha, run_number, prev_sha, commits, prs, _changed_records(repo, prev_sha, sha),
                        created, links)


_REL = re.compile(r"^(\d+)([dh])$")


def parse_since(text: str, now: datetime) -> datetime:
    t = text.strip().lower()
    if t == "yesterday":
        return datetime(now.year, now.month, now.day) - timedelta(days=1)
    m = _REL.match(t)
    if m:
        n = int(m.group(1))
        return now - (timedelta(days=n) if m.group(2) == "d" else timedelta(hours=n))
    try:
        parsed = datetime.fromisoformat(text.strip())
    except ValueError:
        raise ValueError(f"cannot understand {text!r}: use yesterday, 2d, 5h or a date like 2026-11-01") from None
    return parsed.astimezone().replace(tzinfo=None) if parsed.tzinfo else parsed


def dev_since(repo: Path, since: datetime, env: str, gh: GitHub) -> list[DeployReport]:
    deployments = gh.deployments(env)
    chosen = [d for d in deployments if d["state"] == "success" and d["created_at"]
              and _local_naive(d["created_at"]) > since]
    chosen.sort(key=lambda d: d["created_at"])
    return [build_deploy_report(repo, env, d["sha"], gh, _deployments=deployments) for d in chosen]


def _title(r: DeployReport) -> str:
    run = f" (run {r.run_number})" if r.run_number else ""
    return f"Deployed {r.sha[:7]} to {r.env}{run}"


def _since_line(r: DeployReport) -> str:
    return f"since {r.prev_sha[:7]}" if r.prev_sha else "first deployment: all records included"


def format_report_text(r: DeployReport) -> str:
    when = f" at {r.created_at}" if r.created_at else ""
    lines = [f"{_title(r)}{when}", f"{len(r.commits)} commit(s) {_since_line(r)}"]
    lines.append("PRs:" if r.prs else "PRs: none found")
    lines += [f"  #{p['number']} {p['title']} ({p['author']})" for p in r.prs]
    lines.append("Decision records:" if r.records else "Decision records: none")
    lines += [f"  {x.id} {x.title} [{x.status}]" for x in r.records]
    return "\n".join(lines) + "\n"


def format_report_markdown(r: DeployReport) -> str:
    when = f" at {r.created_at}" if r.created_at else ""
    lines = [f"## {_title(r)}{when}", "", f"{len(r.commits)} commit(s) {_since_line(r)}.", ""]
    lines.append("**Pull requests**")
    lines += [f"- [#{p['number']}]({p['url']}) {p['title']} ({p['author']})" for p in r.prs] or ["- none found"]
    lines += ["", "**Decision records**"]
    lines += [f"- `{x.id}` {x.title} ({x.status})" for x in r.records] or ["- none"]
    return "\n".join(lines) + "\n"
