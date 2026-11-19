"""Minimal GitHub client over the `gh` CLI (read-only `gh api` calls)."""
from __future__ import annotations

import json
import subprocess
from typing import Callable


class GitHubUnavailable(RuntimeError):
    """gh is missing, not logged in, or the request failed."""


def run_gh(args: list[str]) -> str:
    try:
        r = subprocess.run(["gh", *args], capture_output=True, text=True, encoding="utf-8", timeout=30)
    except subprocess.TimeoutExpired as e:
        raise GitHubUnavailable("gh timed out") from e
    except OSError as e:
        raise GitHubUnavailable(f"gh could not be run: {e}") from e
    if r.returncode != 0:
        raise GitHubUnavailable(r.stderr.strip() or f"gh exited with {r.returncode}")
    return r.stdout


def _pr(raw: dict) -> dict:
    return {
        "number": raw.get("number"),
        "title": raw.get("title", ""),
        "url": raw.get("html_url", ""),
        "author": (raw.get("user") or {}).get("login", ""),
    }


class GitHub:
    def __init__(self, repo_slug: str, runner: Callable[[list[str]], str] = run_gh):
        self.slug = repo_slug
        self._run = runner

    def _get(self, path: str):
        try:
            return json.loads(self._run(["api", path]))
        except json.JSONDecodeError as e:
            raise GitHubUnavailable(f"unexpected response for {path}") from e

    def _get_as(self, path: str, kind: type):
        data = self._get(path)
        if not isinstance(data, kind):
            raise GitHubUnavailable(f"unexpected response for {path}")
        return data

    def prs_for_commit(self, sha: str) -> list[dict]:
        pulls = self._get_as(f"repos/{self.slug}/commits/{sha}/pulls", list)
        if not all(isinstance(p, dict) for p in pulls):
            raise GitHubUnavailable(f"unexpected response for commits/{sha}/pulls")
        return [_pr(p) for p in pulls]

    def pr(self, number: int) -> dict:
        return _pr(self._get_as(f"repos/{self.slug}/pulls/{number}", dict))

    def deployments(self, env: str) -> list[dict]:
        """Deployments to `env`, newest first."""
        out = []
        for d in self._get_as(f"repos/{self.slug}/deployments?environment={env}", list):
            if not isinstance(d, dict) or "id" not in d or "sha" not in d:
                raise GitHubUnavailable("unexpected deployment entry (missing id or sha)")
            statuses = self._get_as(f"repos/{self.slug}/deployments/{d['id']}/statuses", list)
            first = statuses[0] if statuses else {}
            state = first.get("state", "unknown") if isinstance(first, dict) else "unknown"
            out.append({"id": d["id"], "sha": d["sha"], "created_at": d.get("created_at", ""), "state": state})
        return sorted(out, key=lambda d: d["created_at"], reverse=True)

    def html_url(self, path: str, ref: str) -> str:
        return f"https://github.com/{self.slug}/blob/{ref}/{path}"
