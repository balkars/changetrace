from __future__ import annotations

import importlib.util
import stat
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent


def _load_reset():
    spec = importlib.util.spec_from_file_location("demo_reset", ROOT / "scripts" / "demo_reset.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


demo_reset = _load_reset()


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=True, capture_output=True, text=True, encoding="utf-8",
    ).stdout.strip()


def _bare(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "init", "-q", "--bare", "-b", "main", str(path)],
        check=True, capture_output=True, text=True, encoding="utf-8",
    )
    return path


def _remote_for(tmp_path: Path, fragment: str = ""):
    def remote_for(name: str) -> str:
        return _bare(tmp_path / "remotes" / fragment / f"{name}.git").as_posix()
    return remote_for


def test_reset_no_push_builds_clones(tmp_path, capsys):
    run = tmp_path / "run"
    code = demo_reset.main(["--run-dir", str(run)], remote_for=_remote_for(tmp_path))
    assert code == 0
    assert (run / "devA" / "worker" / "config.py").read_text(encoding="utf-8").count(
        '"RETRY_DELAY_SECONDS", 2)'
    ) == 1
    assert list((run / "devA" / ".context" / "decisions").glob("*.md")) == []
    assert _git(run / "devB", "log", "--oneline").count("\n") == 0
    assert _git(run / "devB", "log", "-1", "--format=%s|%an|%ae|%cn") == (
        "Initial state|ChangeTrace Demo|demo@example.test|ChangeTrace Demo"
    )
    assert _git(run / "devA", "config", "--local", "user.name") == "Dev A"
    assert _git(run / "devB", "config", "--local", "user.email") == "dev-b@example.test"
    assert _git(run / "devA", "branch", "--show-current") == "main"
    assert "__pycache__" not in {p.name for p in run.rglob("*")}


def test_reset_is_repeatable_and_wipes_run_dir(tmp_path):
    run = tmp_path / "run"
    remote_for = _remote_for(tmp_path)
    assert demo_reset.main(["--run-dir", str(run)], remote_for=remote_for) == 0
    (run / "devA" / "worker" / "config.py").write_text("changed\n", encoding="utf-8")
    (run / "stray.txt").write_text("x", encoding="utf-8")
    (run / "devB" / ".git" / "objects").chmod(stat.S_IREAD | stat.S_IEXEC)
    assert demo_reset.main(["--run-dir", str(run)], remote_for=remote_for) == 0
    assert not (run / "stray.txt").exists()
    assert "changed" not in (run / "devA" / "worker" / "config.py").read_text(encoding="utf-8")
    assert _git(run / "devA", "status", "--porcelain") == ""


def test_reset_force_pushes_main_over_existing_history(tmp_path):
    remote_for = _remote_for(tmp_path)
    url = remote_for("worker")
    seed = tmp_path / "seed"
    subprocess.run(["git", "init", "-q", "-b", "main", str(seed)], check=True)
    (seed / "old.txt").write_text("old", encoding="utf-8")
    _git(seed, "add", "-A")
    _git(seed, "-c", "user.name=x", "-c", "user.email=x@example.test", "commit", "-qm", "old history")
    _git(seed, "push", "-q", url, "main")
    first = _git(tmp_path / "remotes" / "worker.git", "rev-parse", "main")
    demo_reset.main(["--run-dir", str(tmp_path / "run")], remote_for=lambda n: url if n == "worker" else remote_for(n))
    second = _git(tmp_path / "remotes" / "worker.git", "rev-parse", "main")
    assert first != second
    assert _git(tmp_path / "remotes" / "worker.git", "log", "--oneline", "main").count("\n") == 0


def test_no_push_clones_from_local_seed(tmp_path):
    run = tmp_path / "run"
    def boom(name):
        raise AssertionError("remote_for must not be needed with --no-push")
    assert demo_reset.main(["--no-push", "--run-dir", str(run)], remote_for=boom) == 0
    assert (run / "devA" / "worker" / "config.py").exists()
    assert _git(run / "devB", "log", "--oneline").count("\n") == 0


def test_refuses_tool_repo_remote(tmp_path, capsys):
    run = tmp_path / "run"
    run.mkdir()
    (run / "keep.txt").write_text("keep", encoding="utf-8")
    for url in (
        "https://github.com/balkars/changetrace.git",
        "git@github.com:balkars/changetrace.git",
        "https://github.com/balkars/changetrace",
    ):
        code = demo_reset.main(["--run-dir", str(run)], remote_for=lambda n, u=url: u)
        assert code == 2
        assert (run / "keep.txt").exists()
    assert "changetrace" in capsys.readouterr().err


def test_github_cleanup_only_for_github_remotes(tmp_path, monkeypatch):
    calls: list[list[str]] = []

    def fake_gh(args):
        calls.append(list(args))
        if args[:2] == ["pr", "list"]:
            return '[{"number": 7}]'
        if args[0] == "api" and "deployments" in args[1] and "-X" not in args:
            return "11\n12\n"
        return ""

    monkeypatch.setattr(demo_reset, "_gh", fake_gh)
    demo_reset.main(["--run-dir", str(tmp_path / "run1")], remote_for=_remote_for(tmp_path))
    assert calls == []

    code = demo_reset.main(
        ["--run-dir", str(tmp_path / "run2")], remote_for=_remote_for(tmp_path, "github.com/own")
    )
    assert code == 0
    flat = [" ".join(c) for c in calls]
    assert any(c.startswith("pr close 7 -R own/worker") for c in flat)
    assert any("repos/own/worker/deployments/11/statuses" in c and "state=inactive" in c for c in flat)
    assert any("-X DELETE repos/own/worker/deployments/12" in c for c in flat)
    assert all("balkars/changetrace " not in c + " " for c in flat)


def test_github_cleanup_failure_warns_and_continues(tmp_path, monkeypatch, capsys):
    def failing_gh(args):
        raise RuntimeError("gh not logged in")

    monkeypatch.setattr(demo_reset, "_gh", failing_gh)
    code = demo_reset.main(
        ["--run-dir", str(tmp_path / "run")], remote_for=_remote_for(tmp_path, "github.com/own")
    )
    assert code == 0
    assert "warning" in capsys.readouterr().err.lower()
    assert (tmp_path / "run" / "devA" / "worker" / "config.py").exists()


def test_slack_manifest_has_required_keys():
    data = yaml.safe_load((ROOT / "slack" / "manifest.yml").read_text(encoding="utf-8"))
    assert data["display_information"]["name"] == "ChangeTrace"
    assert data["features"]["bot_user"]["display_name"] == "ChangeTrace"
    commands = {c["command"]: c for c in data["features"]["slash_commands"]}
    assert "/ct" in commands and commands["/ct"]["usage_hint"] == "why KEY | dev-since WHEN"
    assert set(data["oauth_config"]["scopes"]["bot"]) == {
        "chat:write", "commands", "app_mentions:read", "incoming-webhook",
    }
    settings = data["settings"]
    assert settings["event_subscriptions"]["bot_events"] == ["app_mention"]
    assert settings["socket_mode_enabled"] is True
    assert settings["interactivity"]["is_enabled"] is False


def test_hub_yml_lists_both_demo_repos():
    data = yaml.safe_load((ROOT / "demo" / "hub.yml").read_text(encoding="utf-8"))
    assert data["repos"] == [
        {"name": "Worker service", "path": "demo-run/devB", "github": "balkars/changetrace-demo-worker"},
        {"name": "API service", "path": "demo-run/api", "github": "balkars/changetrace-demo-api"},
    ]


def test_meeting_script_has_prompts_and_cut_rule():
    text = (ROOT / "docs" / "demo" / "meeting-script.md").read_text(encoding="utf-8")
    assert "Failed jobs take too long to recover. Find why and fix it." in text
    assert "Retries are hammering the payments API. Set RETRY_DELAY_SECONDS back to 2." in text
    assert "skip if not built" in text.lower()
    assert "demo-env.ps1" in text and "gh auth status" in text


@pytest.mark.parametrize("target", [".", ".."])
def test_refuses_run_dir_at_or_above_tool_repo(target, capsys):
    before = sorted(p.name for p in ROOT.iterdir())
    assert demo_reset.main(["--run-dir", target]) == 2
    assert sorted(p.name for p in ROOT.iterdir()) == before
    assert "refusing" in capsys.readouterr().err


def test_refuses_unmarked_existing_dir_outside_repo(tmp_path):
    victim = tmp_path / "precious"
    victim.mkdir()
    (victim / "file.txt").write_text("keep", encoding="utf-8")
    assert demo_reset.main(["--run-dir", str(victim)], remote_for=_remote_for(tmp_path)) == 2
    assert (victim / "file.txt").read_text(encoding="utf-8") == "keep"
    (victim / ".changetrace-demo-run").write_text("", encoding="utf-8")
    assert demo_reset.main(["--run-dir", str(victim)], remote_for=_remote_for(tmp_path)) == 0
    assert not (victim / "file.txt").exists()


def test_git_failure_prints_error_and_returns_1(tmp_path, capsys):
    code = demo_reset.main(
        ["--run-dir", str(tmp_path / "run")],
        remote_for=lambda n: (tmp_path / "missing" / f"{n}.git").as_posix(),
    )
    assert code == 1
    assert capsys.readouterr().err.startswith("error: ")
