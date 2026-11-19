from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from click.testing import CliRunner

from changetrace.cli import main
from changetrace.deploy import (
    build_deploy_report, dev_since, format_report_markdown, format_report_text, parse_since,
)
from changetrace.github import GitHub
from changetrace.gitops import git
from fakes import FakeGh
from helpers import dev_a_ships_ctx001

DEPLOYS = "api repos/o/r/deployments?environment=dev"


def _statuses(i: int) -> str:
    return f"api repos/o/r/deployments/{i}/statuses"


def _pulls(sha: str) -> str:
    return f"api repos/o/r/commits/{sha}/pulls"


def _pr(n=1):
    return {"number": n, "title": "Immediate retry", "html_url": f"https://x/pull/{n}", "user": {"login": "deva"}}


def _fake(scenario, deployments, states=None, pr_commits=None):
    """deployments: list of (id, sha, created_at); pr_commits: shas that belong to PR #1."""
    responses = {DEPLOYS: [{"id": i, "sha": s, "created_at": c} for i, s, c in deployments]}
    for i, _, _ in deployments:
        responses[_statuses(i)] = [{"state": (states or {}).get(i, "success")}]
    for sha in git(scenario.dev_a, "rev-list", "--all").split():
        responses[_pulls(sha)] = [_pr()] if sha in (pr_commits or []) else []
    return GitHub("o/r", FakeGh(responses))


def _setup(scenario):
    initial = git(scenario.dev_a, "rev-parse", "HEAD")
    dev_a_ships_ctx001(scenario)
    head = git(scenario.dev_a, "rev-parse", "main")
    commits = git(scenario.dev_a, "rev-list", f"{initial}..{head}").split()
    return initial, head, commits


def test_report_includes_ctx001_and_pr(scenario):
    initial, head, commits = _setup(scenario)
    gh = _fake(scenario, [(1, initial, "2026-11-17T10:00:00Z")], pr_commits=commits)
    r = build_deploy_report(scenario.dev_a, "dev", head, gh, run_number="42")
    assert r.prev_sha == initial and r.run_number == "42"
    assert sorted(r.commits) == sorted(commits)
    assert [x.id for x in r.records] == ["CTX-001"]
    assert [p["number"] for p in r.prs] == [1]


def test_report_first_deployment_takes_all(scenario):
    _, head, _ = _setup(scenario)
    gh = _fake(scenario, [])
    r = build_deploy_report(scenario.dev_a, "dev", head, gh)
    assert r.prev_sha is None
    assert [x.id for x in r.records] == ["CTX-001"]


def test_report_skips_non_ancestor_prev(scenario):
    initial, head, _ = _setup(scenario)
    gh = _fake(scenario, [(2, "deadbeef" * 5, "2026-11-18T10:00:00Z")])
    assert build_deploy_report(scenario.dev_a, "dev", head, gh).prev_sha is None


def test_report_ignores_unsuccessful_and_same_sha_deployments(scenario):
    initial, head, _ = _setup(scenario)
    gh = _fake(
        scenario,
        [(3, head, "2026-11-18T12:00:00Z"), (2, head, "2026-11-18T11:00:00Z"), (1, initial, "2026-11-17T10:00:00Z")],
        states={3: "in_progress", 2: "success"},
    )
    assert build_deploy_report(scenario.dev_a, "dev", head, gh).prev_sha == initial


def test_report_offline_uses_local_data(scenario):
    _, head, _ = _setup(scenario)
    r = build_deploy_report(scenario.dev_a, "dev", head, GitHub("o/r", FakeGh.offline()))
    assert r.prev_sha is None and r.prs == [] and r.links_available is False
    assert [x.id for x in r.records] == ["CTX-001"]


def test_parse_since():
    now = datetime(2026, 11, 18, 15)
    assert parse_since("yesterday", now) == datetime(2026, 11, 17, 0, 0)
    assert parse_since("2d", now) == now - timedelta(hours=48)
    assert parse_since("5h", now) == now - timedelta(hours=5)
    assert parse_since("2026-11-01", now) == datetime(2026, 11, 1)
    with pytest.raises(ValueError):
        parse_since("whenever", now)


def test_dev_since_orders_oldest_first(scenario):
    initial, head, commits = _setup(scenario)
    # created_at is UTC; use far-apart dates so local conversion cannot reorder them.
    gh = _fake(scenario, [(2, head, "2026-11-18T12:00:00Z"), (1, initial, "2026-11-10T10:00:00Z")],
               pr_commits=commits)
    reports = dev_since(scenario.dev_a, datetime(2026, 11, 1), "dev", gh)
    assert [r.sha for r in reports] == [initial, head]
    assert reports[1].prev_sha == initial and reports[1].created_at == "2026-11-18T12:00:00Z"
    later = dev_since(scenario.dev_a, datetime(2026, 11, 15), "dev", gh)
    assert [r.sha for r in later] == [head]


def test_formats(scenario):
    initial, head, commits = _setup(scenario)
    gh = _fake(scenario, [(1, initial, "2026-11-17T10:00:00Z")], pr_commits=commits)
    r = build_deploy_report(scenario.dev_a, "dev", head, gh, run_number="7")
    text, md = format_report_text(r), format_report_markdown(r)
    for out in (text, md):
        assert "CTX-001" in out and "Immediate retry" in out and head[:7] in out
    assert md.startswith("## ") and "#1" in md and "https://x/pull/1" in md


def _run_report(scenario, tmp_path, monkeypatch, gh):
    monkeypatch.setattr("changetrace.cli._gh", lambda repo: gh)
    summary = tmp_path / "summary.md"
    head = git(scenario.dev_a, "rev-parse", "main")
    res = CliRunner().invoke(
        main, ["deploy", "report", "--env", "dev", "--sha", head, "--run-number", "9", "--repo", str(scenario.dev_a)],
        env={"GITHUB_STEP_SUMMARY": str(summary)},
    )
    return res, summary


def test_cli_report_writes_summary(scenario, tmp_path, monkeypatch):
    initial, head, commits = _setup(scenario)
    gh = _fake(scenario, [(1, initial, "2026-11-17T10:00:00Z")], pr_commits=commits)
    res, summary = _run_report(scenario, tmp_path, monkeypatch, gh)
    assert res.exit_code == 0, res.output
    assert "links unavailable" not in res.output and "CTX-001" in res.output
    assert "#1" in summary.read_text(encoding="utf-8")


def test_cli_report_offline_still_succeeds(scenario, tmp_path, monkeypatch):
    _setup(scenario)
    res, summary = _run_report(scenario, tmp_path, monkeypatch, GitHub("o/r", FakeGh.offline()))
    assert res.exit_code == 0, res.output
    assert "links unavailable (offline or gh not logged in)" in res.output
    assert "CTX-001" in summary.read_text(encoding="utf-8")


def test_cli_dev_since_prints_reports(scenario, monkeypatch):
    initial, head, commits = _setup(scenario)
    gh = _fake(scenario, [(1, initial, "2026-11-17T10:00:00Z")], pr_commits=commits)
    monkeypatch.setattr("changetrace.cli._gh", lambda repo: gh)
    res = CliRunner().invoke(main, ["dev-since", "2026-11-01", "--repo", str(scenario.dev_a)])
    assert res.exit_code == 0 and initial[:7] in res.output


def test_cli_dev_since_bad_value(scenario):
    res = CliRunner().invoke(main, ["dev-since", "whenever", "--repo", str(scenario.dev_a)])
    assert res.exit_code == 2


def test_cli_report_survives_unwritable_step_summary(scenario, tmp_path, monkeypatch):
    initial, head, commits = _setup(scenario)
    gh = _fake(scenario, [(1, initial, "2026-11-17T10:00:00Z")], pr_commits=commits)
    monkeypatch.setattr("changetrace.cli._gh", lambda repo: gh)
    res = CliRunner().invoke(
        main, ["deploy", "report", "--sha", head, "--repo", str(scenario.dev_a)],
        env={"GITHUB_STEP_SUMMARY": str(tmp_path)},  # a directory: cannot be opened for append
    )
    assert res.exit_code == 0, res.output
    assert "CTX-001" in res.output and "could not write GITHUB_STEP_SUMMARY" in res.output


def test_parse_since_timezone_aware_becomes_naive_local():
    from datetime import timezone
    now = datetime(2026, 11, 18, 15)
    got = parse_since("2026-11-01T10:00:00Z", now)
    assert got.tzinfo is None
    assert got == datetime(2026, 11, 1, 10, tzinfo=timezone.utc).astimezone().replace(tzinfo=None)
    assert parse_since("2026-11-01T10:00:00+02:00", now).tzinfo is None
    assert got < now  # comparable with naive datetimes


def test_first_deployment_caps_pr_lookups(scenario, monkeypatch):
    calls = []

    def runner(args):
        calls.append(args[1])
        return "[]"

    shas = [f"{i:040x}" for i in range(120)]
    monkeypatch.setattr("changetrace.deploy.rev_list", lambda repo, start, end: shas)
    head = git(scenario.dev_a, "rev-parse", "HEAD")
    r = build_deploy_report(scenario.dev_a, "dev", head, GitHub("o/r", runner), _deployments=[])
    assert r.prev_sha is None and len(r.commits) == 120
    assert len(calls) == 50 and calls[0].endswith(f"{shas[0]}/pulls")
    calls.clear()
    prev = [{"id": 1, "sha": head, "created_at": "", "state": "success"}]  # not != sha: still no prev
    build_deploy_report(scenario.dev_a, "dev", head, GitHub("o/r", runner), _deployments=prev)
    assert len(calls) == 50
