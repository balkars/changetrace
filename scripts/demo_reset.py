"""Reset the ChangeTrace demo to its starting state.

Rebuilds each demo repo from its template under demo/ as a single commit,
force-pushes main of the demo repos only, cleans up GitHub leftovers (open
PRs, other branches, deployments), and recreates fresh clones under the run
directory.

    python scripts/demo_reset.py [--owner balkars] [--no-push] [--run-dir demo-run]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ("worker", "api")
TOOL_REPO = "changetrace"
AUTHOR = {"name": "ChangeTrace Demo", "email": "demo@example.test"}
DEVS = (("devA", "Dev A", "dev-a@example.test"), ("devB", "Dev B", "dev-b@example.test"))
COPY_IGNORE = shutil.ignore_patterns("__pycache__", ".pytest_cache", "*.pyc", ".git")
MARKER = ".changetrace-demo-run"
GITHUB_URL = re.compile(r"github\.com[/:]([^/]+)/([^/]+?)(?:\.git)?/?$")


def _warn(message: str) -> None:
    print(f"warning: {message}", file=sys.stderr)


def _clear_readonly(func, path, _exc) -> None:
    os.chmod(path, stat.S_IWRITE)
    func(path)


def _rmtree(path: Path) -> None:
    if not path.exists():
        return
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=_clear_readonly)
    else:
        shutil.rmtree(path, onerror=_clear_readonly)


def _git(cwd: Path | None, *args: str, env: dict[str, str] | None = None) -> str:
    cmd = ["git", *(["-C", str(cwd)] if cwd else []), *args]
    result = subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8",
        env={**os.environ, **(env or {})},
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {args[0]} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def _gh(args: list[str]) -> str:
    result = subprocess.run(
        ["gh", *args], capture_output=True, text=True, encoding="utf-8",
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"gh {args[0]} failed")
    return result.stdout


def _is_tool_repo(url: str) -> bool:
    tail = re.split(r"[/:\\]", url.strip().rstrip("/\\"))[-1]
    tail = tail[:-4] if tail.endswith(".git") else tail
    return tail.lower() == TOOL_REPO


def _safe_to_wipe(run_dir: Path) -> bool:
    if not run_dir.exists() or (run_dir / MARKER).is_file():
        return True
    return run_dir != ROOT and ROOT in run_dir.parents  # strictly inside the tool repo


def _build_repo(template: Path, dest: Path) -> None:
    shutil.copytree(template, dest, ignore=COPY_IGNORE)
    identity = {
        "GIT_AUTHOR_NAME": AUTHOR["name"], "GIT_AUTHOR_EMAIL": AUTHOR["email"],
        "GIT_COMMITTER_NAME": AUTHOR["name"], "GIT_COMMITTER_EMAIL": AUTHOR["email"],
    }
    _git(None, "init", "-q", "-b", "main", str(dest))
    _git(dest, "add", "-A")
    _git(dest, "-c", "core.autocrlf=false", "commit", "-q", "-m", "Initial state", env=identity)


def _github_cleanup(url: str) -> None:
    match = GITHUB_URL.search(url)
    if not match:
        _warn(f"cannot read owner/repo from {url}; skipping GitHub cleanup")
        return
    slug = f"{match.group(1)}/{match.group(2)}"
    steps = (
        ("close open PRs", lambda: _close_prs(slug)),
        ("delete other branches", lambda: _delete_branches(url)),
        ("remove deployments", lambda: _remove_deployments(slug)),
    )
    for label, step in steps:
        try:
            step()
        except Exception as exc:  # cleanup is best effort; the reset itself already worked
            _warn(f"{slug}: could not {label}: {exc}")


def _close_prs(slug: str) -> None:
    listing = json.loads(_gh(["pr", "list", "-R", slug, "--state", "open", "--json", "number"]) or "[]")
    for pr in listing:
        _gh(["pr", "close", str(pr["number"]), "-R", slug])


def _delete_branches(url: str) -> None:
    heads = _git(None, "ls-remote", "--heads", url)
    for line in heads.splitlines():
        ref = line.split("\t", 1)[1]
        branch = ref.removeprefix("refs/heads/")
        if branch != "main":
            _git(None, "push", "-q", url, "--delete", branch)


def _remove_deployments(slug: str) -> None:
    ids = _gh(["api", f"repos/{slug}/deployments", "--paginate", "--jq", ".[].id"]).split()
    for dep in ids:
        base = f"repos/{slug}/deployments/{dep}"
        _gh(["api", "-X", "POST", f"{base}/statuses", "-f", "state=inactive"])
        _gh(["api", "-X", "DELETE", base])


def _clone(url: str, dest: Path, name: str, email: str) -> None:
    _git(None, "clone", "-q", "-b", "main", url, str(dest))
    _git(dest, "config", "user.name", name)
    _git(dest, "config", "user.email", email)


def main(
    argv: list[str] | None = None,
    remote_for: Callable[[str], str] | None = None,
) -> int:
    parser = argparse.ArgumentParser(description="Reset the ChangeTrace demo repos and clones.")
    parser.add_argument("--owner", default="balkars")
    parser.add_argument("--no-push", action="store_true",
                        help="skip GitHub; clone from local seed repos in <run-dir>/_seed")
    parser.add_argument("--run-dir", default="demo-run")
    args = parser.parse_args(argv)

    if remote_for is None:
        def remote_for(name: str) -> str:
            return f"https://github.com/{args.owner}/changetrace-demo-{name}.git"

    names = [n for n in TEMPLATES if (ROOT / "demo" / n).is_dir()]
    if not names:
        print("error: no templates under demo/", file=sys.stderr)
        return 2

    urls: dict[str, str] = {}
    if not args.no_push:
        for name in names:
            urls[name] = remote_for(name)
            if _is_tool_repo(urls[name]):
                print(f"error: refusing to reset {urls[name]}: that is the tool repo, "
                      "not a demo repo", file=sys.stderr)
                return 2

    run_dir = Path(args.run_dir)
    if not run_dir.is_absolute():
        run_dir = ROOT / run_dir
    run_dir = run_dir.resolve()
    if not _safe_to_wipe(run_dir):
        print(f"error: refusing to wipe {run_dir}: it must be inside {ROOT}, "
              f"new, or contain {MARKER}", file=sys.stderr)
        return 2
    _rmtree(run_dir)
    run_dir.mkdir(parents=True)
    (run_dir / MARKER).write_text("created by scripts/demo_reset.py", encoding="utf-8")

    try:
        return _reset(args, names, urls, remote_for, run_dir)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def _reset(args, names, urls, remote_for, run_dir: Path) -> int:
    sources: dict[str, str] = {}
    for name in names:
        with tempfile.TemporaryDirectory() as tmp:
            built = Path(tmp) / name
            _build_repo(ROOT / "demo" / name, built)
            if args.no_push:
                seed = run_dir / "_seed" / name
                shutil.copytree(built, seed)
                sources[name] = str(seed)
                print(f"{name}: built local seed (no push)")
                continue
            _git(built, "push", "-q", "--force", urls[name], "main")
            sources[name] = urls[name]
            print(f"{name}: force-pushed main to {urls[name]}")
            if "github.com" in urls[name]:
                _github_cleanup(urls[name])
            else:
                print(f"{name}: not a github.com remote, GitHub cleanup skipped")

    if "worker" in sources:
        for folder, user, email in DEVS:
            _clone(sources["worker"], run_dir / folder, user, email)
            print(f"cloned worker -> {run_dir / folder}")
    if "api" in sources:
        _clone(sources["api"], run_dir / "api", "Dev B", "dev-b@example.test")
        print(f"cloned api -> {run_dir / 'api'}")
    else:
        print("api: no demo/api template yet, skipped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
