from __future__ import annotations

import subprocess

import pytest

from changetrace import github
from changetrace.github import GitHub, GitHubUnavailable, run_gh
from fakes import FakeGh


def test_run_gh_passes_timeout_and_maps_timeout(monkeypatch):
    seen = {}

    def fake_run(cmd, **kw):
        seen.update(kw)
        raise subprocess.TimeoutExpired(cmd, kw["timeout"])

    monkeypatch.setattr(github.subprocess, "run", fake_run)
    with pytest.raises(GitHubUnavailable):
        run_gh(["api", "x"])
    assert seen["timeout"] == 30


def test_run_gh_maps_oserror(monkeypatch):
    def fake_run(cmd, **kw):
        raise PermissionError("denied")

    monkeypatch.setattr(github.subprocess, "run", fake_run)
    with pytest.raises(GitHubUnavailable):
        run_gh(["api", "x"])


def test_list_endpoint_returning_dict_is_unavailable():
    gh = GitHub("o/r", FakeGh({"api repos/o/r/commits/abc/pulls": {"message": "Not Found"}}))
    with pytest.raises(GitHubUnavailable):
        gh.prs_for_commit("abc")


def test_pr_returning_list_is_unavailable():
    gh = GitHub("o/r", FakeGh({"api repos/o/r/pulls/1": []}))
    with pytest.raises(GitHubUnavailable):
        gh.pr(1)


@pytest.mark.parametrize("bad", [{"sha": "abc"}, {"id": 1}, "nope"])
def test_deployment_missing_fields_is_unavailable(bad):
    gh = GitHub("o/r", FakeGh({"api repos/o/r/deployments?environment=dev": [bad]}))
    with pytest.raises(GitHubUnavailable):
        gh.deployments("dev")


def test_deployments_dict_is_unavailable():
    gh = GitHub("o/r", FakeGh({"api repos/o/r/deployments?environment=dev": {"message": "x"}}))
    with pytest.raises(GitHubUnavailable):
        gh.deployments("dev")
