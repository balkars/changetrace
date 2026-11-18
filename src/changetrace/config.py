"""Loader for .context/config.yml."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .records import CONTEXT_DIR


@dataclass
class Config:
    project: str
    base_branch: str = "main"
    github: str | None = None
    environments: list[str] = field(default_factory=lambda: ["dev"])
    pr_channel: str = "#engineering-prs"
    dev_channel: str = "#engineering-dev"


def load_config(repo: Path) -> Config:
    repo = Path(repo)
    cfg = Config(project=repo.resolve().name)
    path = repo / CONTEXT_DIR / "config.yml"
    if not path.is_file():
        return cfg
    data = yaml.safe_load(path.read_text(encoding="utf-8-sig")) or {}
    if not isinstance(data, dict):
        return cfg
    if data.get("project"):
        cfg.project = str(data["project"])
    if data.get("base_branch"):
        cfg.base_branch = str(data["base_branch"])
    if data.get("github"):
        cfg.github = str(data["github"])
    envs = data.get("environments")
    if isinstance(envs, list) and envs:
        cfg.environments = [str(e) for e in envs]
    slack = data.get("slack")
    if isinstance(slack, dict):
        if slack.get("pr_channel"):
            cfg.pr_channel = str(slack["pr_channel"])
        if slack.get("dev_channel"):
            cfg.dev_channel = str(slack["dev_channel"])
    return cfg
