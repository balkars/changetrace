from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from changetrace.cli import main
from changetrace.gitops import git, to_repo_path
from changetrace.hook import claude_post_edit
from changetrace.init import init_repo
from helpers import dev_a_ships_ctx001, set_retry, write


def test_init_writes_only_inside_repo(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    repo = tmp_path / "r"
    repo.mkdir()
    git(repo, "init", "-b", "main")
    written = init_repo(repo, project="Worker service", claude_hooks=True)
    assert ".agents/skills/changetrace/SKILL.md" in written and ".claude/settings.json" in written
    assert list(home.iterdir()) == []
    assert (repo / ".agents/skills/changetrace/SKILL.md").read_bytes() == (
        repo / ".claude/skills/changetrace/SKILL.md").read_bytes()
    assert "project: Worker service" in (repo / ".context/config.yml").read_text(encoding="utf-8")
    assert (repo / ".context/decisions/.gitkeep").is_file()
    assert (repo / ".context/observations/.gitkeep").is_file()


def test_init_idempotent_pointer(tmp_path):
    git(tmp_path, "init", "-b", "main")
    init_repo(tmp_path)
    second = init_repo(tmp_path)
    for name in ("AGENTS.md", "CLAUDE.md", ".github/copilot-instructions.md"):
        assert (tmp_path / name).read_text(encoding="utf-8").count(".agents/skills/changetrace") == 1
    assert second == []


def test_init_keeps_existing_files(tmp_path):
    git(tmp_path, "init", "-b", "main")
    write(tmp_path, "AGENTS.md", "# Rules\nBe nice.\n")
    write(tmp_path, ".context/config.yml", "project: Mine\n")
    init_repo(tmp_path, project="Other")
    text = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert text.startswith("# Rules\nBe nice.\n") and ".agents/skills/changetrace" in text
    assert (tmp_path / ".context/config.yml").read_text(encoding="utf-8") == "project: Mine\n"


def test_init_merges_existing_claude_settings(tmp_path):
    git(tmp_path, "init", "-b", "main")
    write(tmp_path, ".claude/settings.json", '{"model": "x"}')
    init_repo(tmp_path, claude_hooks=True)
    init_repo(tmp_path, claude_hooks=True)
    s = json.loads((tmp_path / ".claude/settings.json").read_text(encoding="utf-8"))
    assert s["model"] == "x"
    assert len(s["hooks"]["PostToolUse"]) == 1
    assert s["hooks"]["PostToolUse"][0]["hooks"][0]["command"] == "ct hook claude"


def test_init_github_copies_workflows(tmp_path):
    git(tmp_path, "init", "-b", "main")
    written = init_repo(tmp_path, github=True)
    from importlib.resources import files
    for name in ("changetrace-pr.yml", "deploy-dev.yml"):
        template = (files("changetrace") / "templates" / "workflows" / name).read_text(encoding="utf-8")
        assert f".github/workflows/{name}" in written
        assert (tmp_path / ".github" / "workflows" / name).read_text(encoding="utf-8") == template


def test_skill_content():
    from importlib.resources import files
    text = (files("changetrace") / "templates" / "SKILL.md").read_text(encoding="utf-8")
    assert text.startswith("---\nname: changetrace\n")
    for cmd in ("ct explain", "ct why", "ct check --file", "ct capture --from-diff --input -",
                "ct supersede <ID> --input -"):
        assert cmd in text
    for phrase in ("stop before editing", "is **not** permission to override",
                   "wait for the developer's answer", "override CTX-NNN anyway?"):
        assert phrase in text
    repo = Path(__file__).resolve().parents[1]
    for copy in ("demo/worker/.agents/skills/changetrace/SKILL.md",
                 "demo/worker/.claude/skills/changetrace/SKILL.md"):
        assert (repo / copy).read_bytes() == (files("changetrace") / "templates" / "SKILL.md").read_bytes()


def test_hook_absolute_windows_path(scenario):
    dev_a_ships_ctx001(scenario)
    set_retry(scenario.dev_b, "2")
    p = str(scenario.dev_b / "worker" / "config.py").replace("/", "\\")
    code, msg = claude_post_edit(json.dumps({"tool_input": {"file_path": p}}), scenario.dev_b)
    assert code == 2 and "CTX-001" in msg


def test_hook_no_conflict_is_silent(scenario):
    dev_a_ships_ctx001(scenario)
    p = str(scenario.dev_b / "worker" / "config.py")
    assert claude_post_edit(json.dumps({"tool_input": {"file_path": p}}), scenario.dev_b) == (0, "")


def test_hook_ignores_bad_input(scenario):
    assert claude_post_edit("not json", scenario.dev_b) == (0, "")
    assert claude_post_edit("[]", scenario.dev_b) == (0, "")
    assert claude_post_edit('{"tool_input": {}}', scenario.dev_b) == (0, "")
    assert claude_post_edit('{"tool_input": {"file_path": "C:\\\\elsewhere\\\\x.py"}}',
                            scenario.dev_b) == (0, "")


def test_windows_path_with_space_maps_to_repo_path():
    repo = Path("C:/Users/x/My Repo")
    assert to_repo_path(repo, "C:\\Users\\x\\My Repo\\worker\\config.py") == "worker/config.py"


def test_cli_hook_exit_codes(scenario):
    dev_a_ships_ctx001(scenario)
    set_retry(scenario.dev_b, "2")
    p = str(scenario.dev_b / "worker" / "config.py")
    payload = json.dumps({"cwd": str(scenario.dev_b), "tool_name": "Edit", "tool_input": {"file_path": p}})
    r = CliRunner().invoke(main, ["hook", "claude"], input=payload)
    assert r.exit_code == 2 and "CTX-001" in r.stderr
    r = CliRunner().invoke(main, ["hook", "claude"], input="garbage")
    assert r.exit_code == 0 and r.stderr == ""


def test_cli_init(tmp_path):
    git(tmp_path, "init", "-b", "main")
    r = CliRunner().invoke(main, ["init", "--repo", str(tmp_path), "--project", "P", "--claude-hooks"])
    assert r.exit_code == 0 and (tmp_path / ".claude/settings.json").is_file()


def test_hook_warning_is_reported(scenario):
    dev_a_ships_ctx001(scenario)
    write(scenario.dev_b, "worker/config.py", 'import os\nRETRY_DELAY_SECONDS = int(os.getenv("R") or 2)\n')
    p = str(scenario.dev_b / "worker" / "config.py")
    code, msg = claude_post_edit(json.dumps({"tool_input": {"file_path": p}}), scenario.dev_b)
    assert code == 2 and "cannot verify" in msg


def test_hook_unexpected_error_is_reported(scenario):
    dev_a_ships_ctx001(scenario)
    d = scenario.dev_b / ".context" / "decisions"
    (d / "CTX-009-broken.md").write_text("not a record\n", encoding="utf-8")
    p = str(scenario.dev_b / "worker" / "config.py")
    code, msg = claude_post_edit(json.dumps({"tool_input": {"file_path": p}}), scenario.dev_b)
    assert code == 2 and "could not check worker/config.py" in msg and "run ct check" in msg


def test_hook_bad_json_still_silent(scenario):
    assert claude_post_edit("{oops", scenario.dev_b) == (0, "")
