"""Test doubles for the GitHub CLI runner."""
from __future__ import annotations

import json

from changetrace.github import GitHubUnavailable


class FakeGh:
    """Callable runner keyed by " ".join(args) -> JSON-able value; records calls."""

    def __init__(self, responses: dict | None = None):
        self.responses = responses or {}
        self.calls: list[str] = []

    def __call__(self, args: list[str]) -> str:
        key = " ".join(args)
        self.calls.append(key)
        if key not in self.responses:
            raise GitHubUnavailable(f"no fake response for: {key}")
        return json.dumps(self.responses[key])

    @staticmethod
    def offline():
        def runner(args: list[str]) -> str:
            raise GitHubUnavailable("offline")
        return runner
