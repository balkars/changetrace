"""Thin wrapper around the git CLI."""
from __future__ import annotations

import posixpath
import re
import subprocess
from pathlib import Path


class GitError(RuntimeError):
    pass


def _run(repo: Path, *args: str) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            ["git", "-c", "core.quotepath=false", "-C", str(repo), *args],
            capture_output=True, text=True, encoding="utf-8",
        )
    except FileNotFoundError as e:
        raise GitError("git executable not found") from e


def git(repo: Path, *args: str, check: bool = True) -> str:
    """Run git in `repo`; return stripped stdout. Raise GitError with stderr on failure if `check`."""
    r = _run(repo, *args)
    if check and r.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed: {r.stderr.strip()}")
    return r.stdout.strip()


def _lines(out: str) -> list[str]:
    return [ln for ln in out.splitlines() if ln]


def repo_root(start: Path) -> Path:
    return Path(git(start, "rev-parse", "--show-toplevel"))


def _has_commits(repo: Path) -> bool:
    return _run(repo, "rev-parse", "--verify", "-q", "HEAD").returncode == 0


def base_ref(repo: Path, base_branch: str) -> str | None:
    """Merge-base of HEAD and origin/<base_branch>; None if unavailable."""
    if not _has_commits(repo):
        return None
    r = _run(repo, "merge-base", "HEAD", f"origin/{base_branch}")
    sha = r.stdout.strip()
    return sha if r.returncode == 0 and sha else None


def changed_files(repo: Path, base: str | None = None, staged: bool = False) -> list[str]:
    files: set[str] = set()
    if not _has_commits(repo):
        files.update(_lines(git(repo, "ls-files")))
        if not staged:
            files.update(_lines(git(repo, "ls-files", "--others", "--exclude-standard")))
        return sorted(files)
    if staged:
        files.update(_lines(git(repo, "diff", "--cached", "--name-only", "HEAD")))
        return sorted(files)
    files.update(_lines(git(repo, "diff", "--name-only", "HEAD")))
    files.update(_lines(git(repo, "ls-files", "--others", "--exclude-standard")))
    if base:
        files.update(_lines(git(repo, "diff", "--name-only", f"{base}..HEAD")))
    return sorted(files)


def read_at(repo: Path, ref: str, path: str) -> str | None:
    r = _run(repo, "show", f"{ref}:{path}")
    return r.stdout if r.returncode == 0 else None


def added_commit(repo: Path, path: str) -> str | None:
    """Commit that first added `path` (oldest), or None."""
    out = git(repo, "log", "--diff-filter=A", "--format=%H", "--", path, check=False)
    lines = _lines(out)
    return lines[-1] if lines else None


def is_ancestor(repo: Path, a: str, b: str) -> bool:
    return _run(repo, "merge-base", "--is-ancestor", a, b).returncode == 0


def rev_list(repo: Path, start: str | None, end: str) -> list[str]:
    rng = f"{start}..{end}" if start else end
    return _lines(git(repo, "rev-list", rng))


_ABS = re.compile(r"^(?:[A-Za-z]:)?/")


def to_repo_path(repo: Path, p: str) -> str:
    """Absolute or relative path (either slash style) -> POSIX path relative to `repo`."""
    s = p.replace("\\", "/")
    if _ABS.match(s):
        for root in (Path(repo).as_posix(), Path(repo).resolve().as_posix()):
            root = root.rstrip("/")
            if s.lower() == root.lower():
                return "."
            if s.lower().startswith(root.lower() + "/"):
                return s[len(root) + 1:]
        raise ValueError(f"path is outside the repository: {p}")
    norm = posixpath.normpath(s)
    if norm == ".." or norm.startswith("../"):
        raise ValueError(f"path is outside the repository: {p}")
    return norm
