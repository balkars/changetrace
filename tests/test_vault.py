from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
import yaml

from changetrace.capture import capture, supersede
from changetrace.github import GitHub, GitHubUnavailable
from changetrace.gitops import git
from changetrace.vault import HubRepo, build_vault, load_hub
from fakes import FakeGh
from helpers import commit_all, dev_a_ships_ctx001, write

SUPERSEDER = (
    "---\ntitle: Controlled backoff\nguards:\n  - file: worker/config.py\n    key: RETRY_DELAY_SECONDS\n"
    "    expect: '1'\n---\n\n## Decided\nBounded exponential backoff.\n"
)
API_DRAFT = "---\ntitle: Raise API rate limit\n---\n\n## Problem\nClients are throttled.\n\n## Decided\nLimit is 120.\n"


def _no_gh(slug):
    return None


@pytest.fixture
def worker(scenario):
    dev_a_ships_ctx001(scenario)
    supersede(scenario.dev_b, "CTX-001", SUPERSEDER)
    commit_all(scenario.dev_b, "supersede CTX-001")
    return scenario.dev_b


@pytest.fixture
def api(tmp_path):
    repo = tmp_path / "api_repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.name", "Api Dev")
    git(repo, "config", "user.email", "api@example.test")
    write(repo, "api/settings.yaml", "rate_limit:\n  requests_per_minute: 60\n")
    write(repo, ".context/config.yml", "project: API service\ngithub: own/api\n")
    commit_all(repo, "initial")
    write(repo, "api/settings.yaml", "rate_limit:\n  requests_per_minute: 120\n")
    capture(repo, API_DRAFT, from_diff=True)
    commit_all(repo, "raise limit")
    return repo


def _repos(worker, api):
    return [
        HubRepo("Worker service", worker, "own/worker"),
        HubRepo("API service", api, None),
    ]


def test_vault_tree(worker, api, tmp_path):
    out = tmp_path / "vault"
    written = build_vault(_repos(worker, api), out, gh_for=_no_gh)
    for rel in [
        ".changetrace-vault",
        "Engineering overview.md",
        "Worker service/Decisions/CTX-001 Immediate retry for failed jobs.md",
        "Worker service/Decisions/CTX-002 Controlled backoff.md",
        "API service/Decisions/CTX-001 Raise API rate limit.md",
        "Keys/RETRY_DELAY_SECONDS.md",
        "Keys/rate_limit.requests_per_minute.md",
        "Files/worker-config.py.md",
        "Files/api-settings.yaml.md",
        "Dashboards/Decisions.md",
        "Dashboards/Decisions.base",
    ]:
        assert (out / rel).is_file(), rel
    assert all(p.is_file() for p in written)
    assert (out / "Engineering overview.md") in written
    note = (out / "Worker service/Decisions/CTX-002 Controlled backoff.md").read_text(encoding="utf-8")
    assert note.startswith("---\n")
    meta = yaml.safe_load(note.split("---\n")[1])
    assert meta["project"] == "Worker service" and meta["status"] == "active"
    assert "> Generated from own/worker@" in note
    assert "edit in the repository, not here." in note
    assert "Source: https://github.com/own/worker/blob/" in note
    base = yaml.safe_load((out / "Dashboards/Decisions.base").read_text(encoding="utf-8"))
    names = [v["name"] for v in base["views"]]
    assert names == ["Active decisions", "Superseded"]
    table = (out / "Dashboards/Decisions.md").read_text(encoding="utf-8")
    assert "## Worker service" in table and "## API service" in table
    assert not any(b"\r\n" in p.read_bytes() for p in written)


def test_vault_links_are_path_qualified(worker, api, tmp_path):
    out = tmp_path / "vault"
    build_vault(_repos(worker, api), out, gh_for=_no_gh)
    old = (out / "Worker service/Decisions/CTX-001 Immediate retry for failed jobs.md").read_text(encoding="utf-8")
    assert "[[Worker service/Decisions/CTX-002 Controlled backoff|CTX-002]]" in old
    new = (out / "Worker service/Decisions/CTX-002 Controlled backoff.md").read_text(encoding="utf-8")
    assert "[[Worker service/Decisions/CTX-001 Immediate retry for failed jobs|CTX-001]]" in new
    assert "[[Keys/RETRY_DELAY_SECONDS|RETRY_DELAY_SECONDS]]" in old
    assert "[[Files/worker-config.py|worker/config.py]]" in old
    api_note = (out / "API service/Decisions/CTX-001 Raise API rate limit.md").read_text(encoding="utf-8")
    assert "Source: .context/decisions/CTX-001-raise-api-rate-limit.md@" in api_note
    assert "@" in api_note.split("\n\n> ")[1].split("\n")[0]


def test_key_hub_lists_both_records(worker, api, tmp_path):
    out = tmp_path / "vault"
    build_vault(_repos(worker, api), out, gh_for=_no_gh)
    hub = (out / "Keys/RETRY_DELAY_SECONDS.md").read_text(encoding="utf-8")
    assert "[[Worker service/Decisions/CTX-001 Immediate retry for failed jobs|" in hub
    assert "[[Worker service/Decisions/CTX-002 Controlled backoff|" in hub
    assert "Generated from" in hub
    other = (out / "Keys/rate_limit.requests_per_minute.md").read_text(encoding="utf-8")
    assert "[[API service/Decisions/CTX-001 Raise API rate limit|" in other
    assert "Worker service" not in other


def test_vault_preserves_user_notes(worker, api, tmp_path):
    out = tmp_path / "vault"
    build_vault(_repos(worker, api), out, gh_for=_no_gh)
    (out / "My notes.md").write_text("mine", encoding="utf-8")
    (out / "Keys" / "stale.md").write_text("old", encoding="utf-8")
    build_vault(_repos(worker, api), out, gh_for=_no_gh)
    assert (out / "My notes.md").read_text(encoding="utf-8") == "mine"
    assert not (out / "Keys" / "stale.md").exists()
    assert (out / "Keys/RETRY_DELAY_SECONDS.md").is_file()


def test_vault_refuses_foreign_folder(worker, api, tmp_path):
    out = tmp_path / "vault"
    (out / "Keys").mkdir(parents=True)
    (out / "Keys" / "precious.md").write_text("keep", encoding="utf-8")
    with pytest.raises(ValueError):
        build_vault(_repos(worker, api), out, gh_for=_no_gh)
    assert (out / "Keys" / "precious.md").read_text(encoding="utf-8") == "keep"
    assert not (out / ".changetrace-vault").exists()


def test_vault_refuses_unowned_name_inside_marked_vault(worker, api, tmp_path):
    out = tmp_path / "vault"
    build_vault(_repos(worker, api), out, gh_for=_no_gh)
    (out / "Worker service").rename(out / "moved")
    (out / "Worker service").mkdir()
    (out / "Worker service" / "user.md").write_text("keep", encoding="utf-8")
    marker = json.loads((out / ".changetrace-vault").read_text(encoding="utf-8"))
    marker["owned"] = [n for n in marker["owned"] if n != "Worker service"]
    (out / ".changetrace-vault").write_text(json.dumps(marker), encoding="utf-8")
    with pytest.raises(ValueError):
        build_vault(_repos(worker, api), out, gh_for=_no_gh)
    assert (out / "Worker service" / "user.md").exists()
    assert (out / "moved").exists()


def test_vault_rejects_reserved_or_duplicate_project_names(worker, api, tmp_path):
    with pytest.raises(ValueError):
        build_vault([HubRepo("Keys", worker, None)], tmp_path / "v1", gh_for=_no_gh)
    with pytest.raises(ValueError):
        build_vault([HubRepo("A", worker, None), HubRepo("A", api, None)], tmp_path / "v2", gh_for=_no_gh)
    with pytest.raises(ValueError):
        build_vault([HubRepo("../x", worker, None)], tmp_path / "v3", gh_for=_no_gh)


def test_deployment_notes_only_with_gh(worker, tmp_path):
    sha = git(worker, "rev-parse", "HEAD")
    fake = FakeGh({
        "api repos/own/worker/deployments?environment=dev": [
            {"id": 86, "sha": sha, "created_at": "2026-11-18T10:00:00Z"}
        ],
        "api repos/own/worker/deployments/86/statuses": [{"state": "success"}],
    })
    out = tmp_path / "vault"
    build_vault([HubRepo("Worker service", worker, "own/worker")], out, gh_for=lambda s: GitHub(s, runner=fake))
    dep = out / "Worker service/Deployments/dev #86.md"
    assert dep.is_file()
    assert "[[Worker service/Decisions/CTX-002 Controlled backoff|CTX-002]]" in dep.read_text(encoding="utf-8")

    out2 = tmp_path / "vault2"
    build_vault([HubRepo("Worker service", worker, "own/worker")], out2,
                gh_for=lambda s: GitHub(s, runner=FakeGh.offline()))
    assert not (out2 / "Worker service" / "Deployments").exists()
    assert (out2 / "Worker service/Decisions/CTX-002 Controlled backoff.md").is_file()


def test_load_hub_resolves_paths_against_repo_root(tmp_path):
    repo = tmp_path / "tool"
    (repo / "demo").mkdir(parents=True)
    git(repo, "init", "-q", "-b", "main")
    (repo / "demo" / "hub.yml").write_text(
        "repos:\n  - name: A\n    path: demo-run/devB\n    github: o/a\n  - name: B\n    github: o/b\n",
        encoding="utf-8",
    )
    repos = load_hub(repo / "demo" / "hub.yml")
    assert repos[0].name == "A" and repos[0].github == "o/a"
    assert repos[0].path.resolve() == (repo / "demo-run" / "devB").resolve()
    assert repos[1].path is None and repos[1].github == "o/b"


def test_load_hub_outside_git_uses_hub_folder(tmp_path):
    (tmp_path / "hub.yml").write_text("repos:\n  - name: A\n    path: x\n", encoding="utf-8")
    assert load_hub(tmp_path / "hub.yml")[0].path.resolve() == (tmp_path / "x").resolve()


def test_cli_vault_build(worker, api, tmp_path):
    from click.testing import CliRunner
    from changetrace.cli import main

    hub = tmp_path / "hub.yml"
    hub.write_text(yaml.safe_dump({"repos": [{"name": "Worker service", "path": str(worker)}]}), encoding="utf-8")
    out = tmp_path / "vault"
    res = CliRunner().invoke(main, ["vault", "build", "--hub", str(hub), "--out", str(out)])
    assert res.exit_code == 0, res.output
    assert (out / "Dashboards/Decisions.md").is_file()
    (tmp_path / "other").mkdir()
    (tmp_path / "other" / "f.txt").write_text("x", encoding="utf-8")
    res = CliRunner().invoke(main, ["vault", "build", "--hub", str(hub), "--out", str(tmp_path / "other")])
    assert res.exit_code == 1 and "error:" in res.output
