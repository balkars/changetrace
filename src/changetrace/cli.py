"""`ct` command line: thin wiring over the library modules."""
from __future__ import annotations

import functools
import os
import sys
from datetime import datetime
from dataclasses import replace
from pathlib import Path

import click

from . import capture as capture_mod
from .capture import CaptureError
from .check import format_json, format_markdown, format_text, has_conflict, run_check
from .config import load_config
from .deploy import (
    build_deploy_report, dev_since as dev_since_reports, format_report_markdown, format_report_text, parse_since,
)
from .github import GitHub, GitHubUnavailable
from .hook import claude_post_edit, hook_repo
from .init import init_repo
from .gitops import GitError, base_ref, git, read_at, repo_root
from .query import explain as explain_views
from .query import format_views, history as history_entries, why as why_views
from .slack.notify import deploy_payload, post_webhook, pr_payload
from .records import CONTEXT_DIR, KINDS, RecordError, load_records, next_id, parse_record, record_path, render_record
from .validate import validate_repo


def _repo_option(f):
    @click.option("--repo", type=click.Path(file_okay=False), default=None,
                  help="Repository path (default: the repo containing the current directory).")
    @functools.wraps(f)
    def wrapper(*args, repo=None, **kwargs):
        try:
            root = Path(repo).resolve() if repo else Path(repo_root(Path.cwd())).resolve()
            return f(*args, repo=root, **kwargs)
        except (RecordError, CaptureError, GitError) as e:
            click.echo(f"error: {e}", err=True)
            sys.exit(1)
    return wrapper


def _gh(repo: Path) -> GitHub | None:
    slug = load_config(repo).github
    return GitHub(slug) if slug else None


def _saved(repo: Path, rec) -> None:
    click.echo(f"Saved {rec.id} → {Path(rec.path).relative_to(repo).as_posix()}")


_input = click.option("--input", "input_file", type=click.File("r", encoding="utf-8"), default="-",
                      help="Draft file, or - for stdin.")
_from_diff = click.option("--from-diff", is_flag=True, help="Derive guards from the working-tree diff.")


@click.group()
def main() -> None:
    """ChangeTrace: keep engineering decisions next to the code they protect."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


@main.command()
@_input
@_from_diff
@_repo_option
def capture(input_file, from_diff, repo):
    """Record a decision from a draft."""
    _saved(repo, capture_mod.capture(repo, input_file.read(), from_diff=from_diff))


@main.command()
@click.argument("old_id")
@_input
@_from_diff
@_repo_option
def supersede(old_id, input_file, from_diff, repo):
    """Replace an active decision with a new one."""
    _saved(repo, capture_mod.supersede(repo, old_id, input_file.read(), from_diff=from_diff))


@main.command()
@click.option("--about", multiple=True, required=True, help="Record id the observation is about.")
@click.option("--env", required=True, help="Environment observed.")
@click.option("--deployment", default=None, help="Deployment number.")
@_input
@_repo_option
def observe(about, env, deployment, input_file, repo):
    """Record an observation about one or more decisions."""
    _saved(repo, capture_mod.observe(repo, list(about), env, deployment, input_file.read()))


@main.command()
@click.argument("target")
@_repo_option
def why(target, repo):
    """Show the records behind a key, file or record id."""
    click.echo(format_views(why_views(repo, target, _gh(repo))) or f"no records for {target}")


@main.command()
@click.argument("path")
@_repo_option
def explain(path, repo):
    """Show the records that touch a file."""
    click.echo(format_views(explain_views(repo, path, _gh(repo))) or f"no records for {path}")


@main.command()
@click.option("--base", default=None, help="Compare against this ref.")
@click.option("--staged", is_flag=True, help="Check the staged snapshot.")
@click.option("--file", "file_", default=None, help="Limit to one file.")
@click.option("--format", "fmt", type=click.Choice(["text", "json", "markdown"]), default="text")
@_repo_option
def check(base, staged, file_, fmt, repo):
    """Warn when changes undo a recorded decision (exit 1 on conflict)."""
    findings = run_check(repo, base=base, staged=staged, file=file_)
    by_id = {r.id: r for r in load_records(repo)}
    if fmt == "json":
        click.echo(format_json(findings))
    elif fmt == "markdown":
        click.echo(format_markdown(findings, by_id), nl=False)
    else:
        click.echo(format_text(findings, by_id), nl=False)
    sys.exit(1 if has_conflict(findings) else 0)


@main.command()
@click.option("--key", required=True, help="Guarded key, e.g. RETRY_DELAY_SECONDS.")
@_repo_option
def history(key, repo):
    """Timeline of a key: value changes, records, deployments."""
    entries = history_entries(repo, key, _gh(repo))
    for e in entries:
        click.echo(f"{e.when}  {e.kind:<10} {e.text}")
    if not entries:
        click.echo(f"no history for {key}")


@main.command()
@_repo_option
def validate(repo):
    """Check records for problems (exit 1 on any)."""
    problems = validate_repo(repo)
    for p in problems:
        click.echo(f"{p.path}: {p.message}")
    if problems:
        click.echo(f"{len(problems)} problem(s)")
        sys.exit(1)
    click.echo("ok")


def _record_files_at(repo: Path, ref: str) -> dict[str, str]:
    """Map repo-relative record path -> record id for records present at `ref`."""
    found: dict[str, str] = {}
    for _, sub in KINDS.values():
        out = git(repo, "ls-tree", "-r", "--name-only", ref, f"{CONTEXT_DIR}/{sub}", check=False)
        for rel in out.splitlines():
            if rel.endswith(".md"):
                text = read_at(repo, ref, rel)
                try:
                    found[rel] = parse_record(text or "").id
                except RecordError:
                    continue
    return found


@main.command()
@_repo_option
def renumber(repo):
    """Give branch-added records new ids when they collide with ids at the base."""
    ref = base_ref(repo, load_config(repo).base_branch) or "HEAD"
    at_ref = _record_files_at(repo, ref)
    taken = set(at_ref.values())
    current = [(Path(r.path).relative_to(repo).as_posix(), r) for r in load_records(repo)]
    added = [(rel, r) for rel, r in current if rel not in at_ref]
    moves: dict[str, str] = {}
    for rel, rec in added:
        if rec.id in taken:
            new_id = next_id(repo, rec.kind)
            new = replace(rec, id=new_id)
            new.path = record_path(repo, new)
            new.path.write_text(render_record(new), encoding="utf-8", newline="\n")
            (repo / rel).unlink()
            moves[rec.id] = new_id
            click.echo(f"Renumbered {rec.id} → {new_id}")
    if not moves:
        return
    for rec in load_records(repo):
        if Path(rec.path).relative_to(repo).as_posix() in at_ref:
            continue
        fixed = replace(
            rec,
            supersedes=[moves.get(i, i) for i in rec.supersedes],
            superseded_by=moves.get(rec.superseded_by, rec.superseded_by) if rec.superseded_by else None,
        )
        if fixed != rec:
            Path(rec.path).write_text(render_record(fixed), encoding="utf-8", newline="\n")



@main.command()
@click.option("--project", default=None, help="Project name for .context/config.yml.")
@click.option("--claude-hooks", is_flag=True, help="Add the Claude Code PostToolUse hook to .claude/settings.json.")
@click.option("--github", is_flag=True, help="Copy the GitHub workflows to .github/workflows/.")
@_repo_option
def init(project, claude_hooks, github, repo):
    """Set up ChangeTrace in this repository (writes only inside it)."""
    try:
        written = init_repo(repo, project=project, claude_hooks=claude_hooks, github=github)
    except ValueError as e:
        click.echo(f"error: {e}", err=True)
        sys.exit(1)
    for rel in written:
        click.echo(f"wrote {rel}")
    if not written:
        click.echo("already set up")


@main.group()
def hook() -> None:
    """Assistant hooks."""


@hook.command("claude")
def hook_claude() -> None:
    """Claude Code PostToolUse hook: reads the tool call JSON on stdin; exit 2 on a conflict."""
    code, message = 0, ""
    try:
        payload = sys.stdin.buffer.read().decode("utf-8-sig", errors="replace")
        code, message = claude_post_edit(payload, hook_repo(payload, Path.cwd()))
    except Exception:
        code, message = 0, ""
    if message:
        click.echo(message.rstrip(), err=True)
    sys.exit(code)


def _repo_url(repo: Path) -> str:
    slug = load_config(repo).github
    return f"https://github.com/{slug}" if slug else ""


def _post_slack(repo: Path, report) -> None:
    payload = deploy_payload(report, load_config(repo).project, _repo_url(repo))
    post_webhook(os.environ.get("SLACK_WEBHOOK_URL"), payload)


@main.group()
def deploy() -> None:
    """Deployment commands."""


@deploy.command("report")
@click.option("--env", default="dev", show_default=True, help="Environment that was deployed.")
@click.option("--sha", required=True, help="Commit that was deployed.")
@click.option("--run-number", default=None, help="CI run number.")
@_repo_option
def deploy_report(env, sha, run_number, repo):
    """Report what this deployment added since the previous successful one."""
    report = build_deploy_report(repo, env, sha, _gh(repo), run_number)
    if not report.links_available:
        click.echo("links unavailable (offline or gh not logged in)")
    click.echo(format_report_text(report), nl=False)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        try:
            with open(summary, "a", encoding="utf-8", newline="\n") as f:
                f.write(format_report_markdown(report))
        except OSError as e:
            click.echo(f"warning: could not write GITHUB_STEP_SUMMARY: {e}", err=True)
    _post_slack(repo, report)


@main.command("dev-since")
@click.argument("when")
@click.option("--env", default="dev", show_default=True)
@_repo_option
def dev_since(when, env, repo):
    """What changed in an environment since WHEN (yesterday, 2d, 5h or a date)."""
    try:
        since = parse_since(when, datetime.now())
    except ValueError as e:
        raise click.BadParameter(str(e), param_hint="WHEN")
    gh = _gh(repo)
    try:
        if gh is None:
            raise GitHubUnavailable("no github repository configured")
        reports = dev_since_reports(repo, since, env, gh)
    except GitHubUnavailable:
        click.echo("links unavailable (offline or gh not logged in)")
        return
    for r in reports:
        click.echo(format_report_text(r))
    if not reports:
        click.echo(f"no successful deployments to {env} since {since:%Y-%m-%d %H:%M}")


@main.group()
def notify() -> None:
    """Send notifications."""


@notify.group()
def slack() -> None:
    """Slack notifications (webhook URL in SLACK_WEBHOOK_URL)."""


@slack.command("pr")
@click.option("--pr", "number", type=int, required=True, help="Pull request number.")
@_repo_option
def slack_pr(number, repo):
    """Post a pull request's decision records and Watch out notes to Slack."""
    cfg = load_config(repo)
    base = base_ref(repo, cfg.base_branch) or f"origin/{cfg.base_branch}"
    out = git(repo, "diff", "--name-only", f"{base}...HEAD", "--", f"{CONTEXT_DIR}/")
    changed = {ln.strip() for ln in out.splitlines() if ln.strip()}
    records = [r for r in load_records(repo) if Path(r.path).resolve().relative_to(repo).as_posix() in changed]
    pr = {"number": number, "title": f"PR #{number}", "author": "", "url": ""}
    gh = _gh(repo)
    if gh is not None:
        try:
            pr = gh.pr(number)
        except GitHubUnavailable:
            pass
    payload = pr_payload(pr, records, run_check(repo), _repo_url(repo), cfg.project)
    post_webhook(os.environ.get("SLACK_WEBHOOK_URL"), payload)
