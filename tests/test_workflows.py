from __future__ import annotations

import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / "src" / "changetrace" / "templates" / "workflows"
DEMO = ROOT / "demo" / "worker"


def load(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if True in data:  # PyYAML parses the key `on` as boolean True
        data["on"] = data.pop(True)
    return data


def runs(job: dict) -> list[str]:
    return [step["run"] for step in job["steps"] if "run" in step]


def test_pr_workflow_shape():
    wf = load(TEMPLATES / "changetrace-pr.yml")
    assert wf["on"]["pull_request"]["types"] == ["opened", "synchronize", "reopened", "ready_for_review"]
    assert wf["permissions"] == {"contents": "read", "pull-requests": "write"}
    (job,) = wf["jobs"].values()
    commands = "\n".join(runs(job))
    assert "ct validate || echo validate > ct.failed" in commands
    assert commands.index("ct validate") < commands.index("ct check") < commands.index("gh pr comment")
    assert "ct check --base origin/${{ github.base_ref }} --format markdown" in commands
    assert "--edit-last" in commands
    assert job["steps"][0]["with"]["fetch-depth"] == 0
    slack = [s for s in job["steps"] if "ct notify slack pr" in s.get("run", "")]
    assert len(slack) == 1
    assert slack[0]["env"]["SLACK_WEBHOOK_URL"] == "${{ secrets.SLACK_WEBHOOK_PRS }}"
    assert "opened" in slack[0]["if"] and "ready_for_review" in slack[0]["if"]
    assert "synchronize" not in slack[0]["if"]
    assert job["steps"][-1]["run"].strip() == "test ! -f ct.failed"
    for step in job["steps"]:
        if "gh pr comment" in step.get("run", "") or "ct notify" in step.get("run", ""):
            assert step["env"]["GH_TOKEN"] == "${{ github.token }}"


def test_deploy_workflow_shape():
    wf = load(TEMPLATES / "deploy-dev.yml")
    assert wf["on"]["push"]["branches"] == ["main"]
    assert "workflow_dispatch" in wf["on"]
    job = wf["jobs"]["deploy"]
    assert job["environment"] == "dev"
    assert job["permissions"] == {"contents": "read", "deployments": "read", "pull-requests": "read"}
    stand_in = [s for s in job["steps"] if "stand-in" in s.get("name", "")]
    assert len(stand_in) == 1
    assert "python -m pytest -q" in stand_in[0]["run"] and "python -m worker.retry --smoke" in stand_in[0]["run"]
    report = [s for s in job["steps"] if "ct deploy report" in s.get("run", "")]
    assert len(report) == 1
    assert "--run-number ${{ github.run_number }}" in report[0]["run"]
    assert "--sha ${{ github.sha }}" in report[0]["run"]
    assert report[0]["env"]["GH_TOKEN"] == "${{ github.token }}"
    assert report[0]["env"]["SLACK_WEBHOOK_URL"] == "${{ secrets.SLACK_WEBHOOK_DEV }}"


def test_tool_ci_workflow_shape():
    wf = load(ROOT / ".github" / "workflows" / "ci.yml")
    job = wf["jobs"]["test"]
    assert job["strategy"]["matrix"]["os"] == ["ubuntu-latest", "windows-latest"]
    assert job["strategy"]["matrix"]["python-version"] == ["3.11", "3.13"]
    commands = "\n".join(runs(job))
    assert 'pip install -e ".[dev,slack]"' in commands
    assert "pytest -q" in commands
    assert "git config --global user.name" in commands


def test_demo_worker_template_initialised():
    skills = [DEMO / ".claude" / "skills" / "changetrace" / "SKILL.md",
              DEMO / ".agents" / "skills" / "changetrace" / "SKILL.md"]
    assert all(p.is_file() for p in skills)
    assert skills[0].read_bytes() == skills[1].read_bytes()
    config = yaml.safe_load((DEMO / ".context" / "config.yml").read_text(encoding="utf-8"))
    assert config["github"] == "balkars/changetrace-demo-worker"
    assert config["project"] == "Worker service"
    assert sorted(p.name for p in (DEMO / ".context" / "decisions").iterdir()) == [".gitkeep"]
    assert not (DEMO / ".git").exists()
    for name in ("changetrace-pr.yml", "deploy-dev.yml"):
        assert (DEMO / ".github" / "workflows" / name).read_bytes() == (TEMPLATES / name).read_bytes()
    assert "ct hook claude" in (DEMO / ".claude" / "settings.json").read_text(encoding="utf-8")


def test_demo_worker_tests_pass(tmp_path):
    """Run exactly the stand-in deploy step's commands in a copy of the demo worker."""
    work = tmp_path / "worker-copy"
    shutil.copytree(DEMO, work)
    deploy = load(DEMO / ".github" / "workflows" / "deploy-dev.yml")
    (step,) = [s for s in deploy["jobs"]["deploy"]["steps"] if "stand-in" in s.get("name", "")]
    lines = [ln.strip() for ln in step["run"].splitlines() if ln.strip()]
    assert lines
    for line in lines:
        args = shlex.split(line)
        assert args[0] == "python"
        args[0] = sys.executable
        result = subprocess.run(args, cwd=work, capture_output=True, text=True)
        assert result.returncode == 0, f"{line}\n{result.stdout}{result.stderr}"
    assert "retry delay: " in result.stdout


def test_demo_worker_plain_pytest_works(tmp_path):
    work = tmp_path / "worker-copy"
    shutil.copytree(DEMO, work)
    result = subprocess.run([sys.executable, "-c", "import sys; from pytest import console_main; sys.argv=['pytest','-q','-p','no:cacheprovider']; sys.exit(console_main())"],
                            cwd=work, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
