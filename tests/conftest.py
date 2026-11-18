from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from changetrace.gitops import git
from helpers import CONFIG_PY, Scenario, commit_all, write


def _clone(origin: Path, dest: Path, name: str, email: str, autocrlf: str) -> None:
    subprocess.run(
        ["git", "clone", "-q", str(origin), str(dest)],
        check=True, capture_output=True, text=True, encoding="utf-8",
    )
    git(dest, "config", "user.name", name)
    git(dest, "config", "user.email", email)
    git(dest, "config", "core.autocrlf", autocrlf)


@pytest.fixture
def scenario(tmp_path: Path) -> Scenario:
    origin = tmp_path / "origin.git"
    subprocess.run(
        ["git", "init", "-q", "--bare", "-b", "main", str(origin)],
        check=True, capture_output=True, text=True, encoding="utf-8",
    )
    dev_a = tmp_path / "dev_a"
    dev_b = tmp_path / "dev_b"
    _clone(origin, dev_a, "DevA", "deva@example.test", "false")
    git(dev_a, "checkout", "-q", "-B", "main")
    write(dev_a, "worker/config.py", CONFIG_PY)
    write(dev_a, ".context/config.yml", "project: Worker service\n")
    commit_all(dev_a, "initial")
    git(dev_a, "push", "-q", "-u", "origin", "main")
    _clone(origin, dev_b, "DevB", "devb@example.test", "true")
    return Scenario(origin=origin, dev_a=dev_a, dev_b=dev_b)
