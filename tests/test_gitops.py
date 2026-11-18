from __future__ import annotations

import pytest

from changetrace.config import load_config
from changetrace.gitops import (
    GitError, added_commit, base_ref, changed_files, git, is_ancestor,
    read_at, repo_root, rev_list, to_repo_path,
)
from changetrace.records import parse_record
from helpers import CTX001_RECORD, CTX001_DRAFT, commit_all, set_retry, write, finish_and_merge


def test_ctx001_record_parses():
    assert parse_record(CTX001_RECORD).id == "CTX-001"


def test_changed_files_includes_untracked_and_branch(scenario):
    a = scenario.dev_a
    git(a, "checkout", "-b", "f"); set_retry(a, "0"); commit_all(a, "c")
    write(a, ".context/decisions/CTX-001-x.md", "x")
    base = base_ref(a, "main")
    assert changed_files(a, base) == [".context/decisions/CTX-001-x.md", "worker/config.py"]


def test_changed_files_staged_only(scenario):
    a = scenario.dev_a
    set_retry(a, "0"); git(a, "add", "worker/config.py")
    write(a, "other.txt", "x")
    assert changed_files(a, staged=True) == ["worker/config.py"]
    assert changed_files(a) == ["other.txt", "worker/config.py"]


def test_no_origin_repo_works(tmp_path):
    git(tmp_path, "init", "-b", "main"); write(tmp_path, "a.py", "X = 1\n")
    assert base_ref(tmp_path, "main") is None
    assert changed_files(tmp_path) == ["a.py"]


def test_no_commits_lists_tracked_and_untracked(tmp_path):
    git(tmp_path, "init", "-b", "main")
    write(tmp_path, "a.py", "1"); git(tmp_path, "add", "a.py"); write(tmp_path, "b.py", "2")
    assert changed_files(tmp_path) == ["a.py", "b.py"]


def test_base_ref_unknown_branch_is_none(scenario):
    assert base_ref(scenario.dev_a, "nope") is None


def test_base_ref_is_merge_base(scenario):
    a = scenario.dev_a
    head = git(a, "rev-parse", "HEAD")
    git(a, "checkout", "-b", "f"); set_retry(a, "0"); commit_all(a, "c")
    assert base_ref(a, "main") == head


def test_to_repo_path_windows_style(tmp_path):
    sub = tmp_path / "My Repo"; sub.mkdir()
    assert to_repo_path(sub, str(sub / "worker" / "config.py")) == "worker/config.py"
    assert to_repo_path(sub, "worker\\config.py") == "worker/config.py"


def test_to_repo_path_outside_raises(tmp_path):
    sub = tmp_path / "r"; sub.mkdir()
    with pytest.raises(ValueError):
        to_repo_path(sub, str(tmp_path / "elsewhere.py"))
    with pytest.raises(ValueError):
        to_repo_path(sub, "../x.py")


def test_added_commit(scenario):
    a = scenario.dev_a
    assert added_commit(a, "worker/config.py") == git(a, "rev-parse", "HEAD")
    assert added_commit(a, "missing.py") is None


def test_read_at(scenario):
    a = scenario.dev_a
    assert "RETRY_DELAY_SECONDS" in read_at(a, "HEAD", "worker/config.py")
    assert read_at(a, "HEAD", "nope.py") is None


def test_is_ancestor_and_rev_list(scenario):
    a = scenario.dev_a
    first = git(a, "rev-parse", "HEAD")
    second = commit_all_after(a)
    assert is_ancestor(a, first, second) and not is_ancestor(a, second, first)
    assert rev_list(a, first, second) == [second]
    assert rev_list(a, None, second) == [second, first]


def commit_all_after(a):
    write(a, "x.txt", "x")
    return commit_all(a, "second")


def test_git_error_carries_stderr(tmp_path):
    git(tmp_path, "init", "-b", "main")
    with pytest.raises(GitError) as e:
        git(tmp_path, "rev-parse", "nonexistent-ref")
    assert "nonexistent-ref" in str(e.value)


def test_repo_root(scenario):
    sub = scenario.dev_a / "worker"
    assert repo_root(sub) == scenario.dev_a.resolve()


def test_scenario_clones_and_merge(scenario):
    a, b = scenario.dev_a, scenario.dev_b
    assert git(a, "config", "user.name") == "DevA" and git(b, "config", "user.name") == "DevB"
    assert git(a, "config", "core.autocrlf") == "false" and git(b, "config", "core.autocrlf") == "true"
    assert (b / "worker" / "config.py").exists()
    git(a, "checkout", "-b", "fix/x"); set_retry(a, "0")
    finish_and_merge(scenario)
    assert git(a, "rev-parse", "--abbrev-ref", "HEAD") == "main"
    assert "RETRY_DELAY_SECONDS\", 0)" in (b / "worker" / "config.py").read_text(encoding="utf-8")
    assert len(git(b, "log", "--merges", "--format=%H").splitlines()) == 1


def test_finish_and_merge_on_main_just_pushes(scenario):
    set_retry(scenario.dev_a, "0")
    finish_and_merge(scenario)
    assert "RETRY_DELAY_SECONDS\", 0)" in (scenario.dev_b / "worker" / "config.py").read_text(encoding="utf-8")


def test_ctx001_draft_has_decided():
    assert "## Decided\nDefault retry delay is 0" in CTX001_DRAFT


def test_load_config_defaults(tmp_path):
    c = load_config(tmp_path)
    assert c.base_branch == "main" and c.environments == ["dev"]
    assert c.pr_channel == "#engineering-prs" and c.github is None


def test_load_config_reads_file_with_bom_crlf(tmp_path):
    p = tmp_path / ".context"; p.mkdir()
    (p / "config.yml").write_bytes(
        b"\xef\xbb\xbfproject: Worker service\r\nbase_branch: dev\r\ngithub: o/r\r\n"
        b"environments: [dev, prod]\r\nslack:\r\n  pr_channel: \"#p\"\r\n  dev_channel: \"#d\"\r\n"
    )
    c = load_config(tmp_path)
    assert (c.project, c.base_branch, c.github) == ("Worker service", "dev", "o/r")
    assert c.environments == ["dev", "prod"] and (c.pr_channel, c.dev_channel) == ("#p", "#d")


def test_committed_rename_lists_both_paths(scenario):
    a = scenario.dev_a
    git(a, "checkout", "-b", "r"); git(a, "mv", "worker/config.py", "worker/settings.py")
    commit_all(a, "rename")
    assert changed_files(a, base_ref(a, "main")) == ["worker/config.py", "worker/settings.py"]


def test_staged_rename_lists_both_paths(scenario):
    a = scenario.dev_a
    git(a, "mv", "worker/config.py", "worker/settings.py")
    assert changed_files(a, staged=True) == ["worker/config.py", "worker/settings.py"]
    assert changed_files(a) == ["worker/config.py", "worker/settings.py"]
