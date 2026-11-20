"""Obsidian team vault: aggregate records from several repos into one read-only vault."""
from __future__ import annotations

import json
import re
import shutil
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable

import yaml

from .config import load_config
from .github import GitHub, GitHubUnavailable
from .gitops import GitError, added_commit, git, is_ancestor, repo_root
from .records import Record, load_records, render_record

MARKER = ".changetrace-vault"
OVERVIEW = "Engineering overview.md"
FIXED_FOLDERS = ("Keys", "Files", "Dashboards")
BANNER_TAIL = "edit in the repository, not here."


@dataclass
class HubRepo:
    name: str
    path: Path | None
    github: str | None


def load_hub(path: Path) -> list[HubRepo]:
    """Read hub.yml. Relative `path` entries resolve against the git repo root containing the hub file
    (fallback: the hub file's folder)."""
    hub = Path(path).resolve()
    try:
        base = Path(repo_root(hub.parent)).resolve()
    except (GitError, OSError):
        base = hub.parent
    data = yaml.safe_load(hub.read_text(encoding="utf-8-sig")) or {}
    entries = data.get("repos") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        raise ValueError("hub file needs a 'repos' list")
    repos: list[HubRepo] = []
    for e in entries:
        if not isinstance(e, dict) or not e.get("name"):
            raise ValueError("each hub repo needs a 'name'")
        raw = e.get("path")
        gh = str(e["github"]) if e.get("github") else None
        if not raw and not gh:
            raise ValueError(f"hub repo '{e['name']}' needs a 'path' or 'github'")
        p = None
        if raw:
            p = Path(str(raw))
            if not p.is_absolute():
                p = base / p
        repos.append(HubRepo(str(e["name"]), p, gh))
    return repos


def _default_gh(slug: str) -> GitHub | None:
    return GitHub(slug)


def _safe(name: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|#^\[\]]+', "-", name).strip(" .-")
    return cleaned or "untitled"


def _link(target: str, alias: str) -> str:
    return f"[[{target}|{alias}]]"


def _write(root: Path, rel: str, text: str, written: list[str]) -> None:
    """Write `rel` under `root`; refuse anything that would land outside it."""
    path = root / rel
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        raise ValueError(f"refusing to write outside the vault: {rel}") from None
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    written.append(Path(rel).as_posix())


def _short_head(repo: Path) -> str:
    return git(repo, "rev-parse", "--short", "HEAD", check=False) or "unknown"


@dataclass
class _Item:
    project: str
    rec: Record
    rel: str            # record path relative to its repo, POSIX
    note: str           # vault-relative note path without .md
    commit: str | None  # commit that added the record file


def _banner(origin: str, sha: str) -> str:
    return f"> Generated from {origin}@{sha} — {BANNER_TAIL}"


def _read_owned(out: Path) -> list[str]:
    """Vault-relative POSIX paths of files a previous build wrote (from the marker)."""
    try:
        data = json.loads((out / MARKER).read_text(encoding="utf-8"))
        files = data.get("files", [])
    except (OSError, ValueError, AttributeError):
        return []
    ok = []
    for f in files if isinstance(files, list) else []:
        if isinstance(f, str) and f and f != MARKER and ".." not in Path(f).parts and not Path(f).is_absolute():
            ok.append(f)
    return ok


def _check_out(out: Path, new_files: list[str]) -> list[str]:
    """Validate ownership and return the previously written files. Raises ValueError before anything changes."""
    if out.exists() and not out.is_dir():
        raise ValueError(f"{out} is not a folder")
    marked = (out / MARKER).is_file()
    if out.is_dir() and not marked and any(out.iterdir()):
        raise ValueError(f"refusing to build into {out}: it is not empty and has no {MARKER} marker")
    owned = _read_owned(out) if marked else []
    for rel in new_files:
        if (out / rel).exists() and rel not in owned:
            raise ValueError(f"refusing to overwrite '{rel}' in {out}: it was not written by ct vault build")
    return owned


def _remove_owned(out: Path, owned: list[str]) -> None:
    """Delete only files the builder wrote earlier, then prune directories left empty."""
    root = out.resolve()
    for rel in owned:
        f = out / rel
        if f.is_file() and not f.is_symlink():
            f.unlink()
            parent = f.parent
            while parent.resolve() != root:
                try:
                    parent.rmdir()
                except OSError:
                    break
                parent = parent.parent


def build_vault(
    repos: list[HubRepo],
    out: Path,
    gh_for: Callable[[str], GitHub | None] = _default_gh,
) -> list[Path]:
    out = Path(out)
    names = [r.name for r in repos]
    for n in names:
        if _safe(n) != n or n in FIXED_FOLDERS or n + ".md" == OVERVIEW or n == OVERVIEW[:-3]:
            raise ValueError(f"project name '{n}' is not usable as a vault folder")
    if len(set(names)) != len(names):
        raise ValueError("project names must be unique")
    for r in repos:
        if r.path is None or not Path(r.path).is_dir():
            raise ValueError(f"repo '{r.name}': local path not found ({r.path})")

    loaded: list[tuple[HubRepo, Path, str, list[_Item]]] = []
    for r in repos:
        path = Path(r.path)
        sha = _short_head(path)
        origin = r.github or path.as_posix()
        items: list[_Item] = []
        for rec in load_records(path):
            rel = Path(rec.path).resolve().relative_to(path.resolve()).as_posix()
            folder = "Decisions" if rec.kind == "decision" else "Observations"
            note = f"{r.name}/{folder}/{rec.id} {_safe(rec.title)}"
            items.append(_Item(r.name, rec, rel, note, added_commit(path, rel)))
        loaded.append((r, path, origin, items))

    out.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".ct-vault-stage-", dir=out.parent))
    try:
        files = _generate(loaded, names, stage, gh_for)
        owned = _check_out(out, files)
        _remove_owned(out, owned)
        out.mkdir(parents=True, exist_ok=True)
        for rel in files:
            dest = out / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(stage / rel, dest)
        marker = json.dumps({"files": files}, indent=2) + "\n"
        with open(out / MARKER, "w", encoding="utf-8", newline="\n") as f:
            f.write(marker)
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    return [out / MARKER, *(out / f for f in files)]


def _generate(loaded, names: list[str], out: Path, gh_for) -> list[str]:
    written: list[str] = []

    all_items = [i for _, _, _, items in loaded for i in items]
    keys: dict[str, list[_Item]] = {}
    files: dict[str, list[_Item]] = {}
    for it in all_items:
        for k in {g.key for g in it.rec.guards} | {t.split("#", 1)[1] for t in it.rec.touches if "#" in t}:
            keys.setdefault(k, []).append(it)
        for f in {g.file for g in it.rec.guards} | {t.split("#", 1)[0] for t in it.rec.touches}:
            files.setdefault(f, []).append(it)

    def file_note(f: str) -> str:
        return "Files/" + _safe(f.replace("/", "-"))

    for r, path, origin, items in loaded:
        sha = _short_head(path)
        by_id = {i.rec.id: i for i in items}
        reverse: dict[str, str] = {}
        for i in items:
            for old in i.rec.supersedes:
                reverse.setdefault(old, i.rec.id)

        def ref(rid: str) -> str:
            t = by_id.get(rid)
            return _link(t.note, rid) if t else rid

        deployments = _deployments(r, path, gh_for)
        for env, dep in deployments:
            members = [i for i in items if i.rec.kind == "decision" and i.commit and is_ancestor(path, i.commit, dep["sha"])]
            name = f"{r.name}/Deployments/{_safe(env)}-{_safe(str(dep['id']))}"
            lines = [_banner(origin, sha), "", f"# {env} deployment {dep['id']}", "",
                     f"- Commit: `{dep['sha'][:7]}`", f"- State: {dep['state']}",
                     f"- Created: {dep['created_at']}", "", "## Decisions in this deployment", ""]
            lines += [f"- {_link(i.note, i.rec.id)} {i.rec.title}" for i in members] or ["- none"]
            _write(out, f"{name}.md", "\n".join(lines) + "\n", written)
            for i in members:
                i.__dict__.setdefault("deployed", []).append(_link(name, f"{env} deploy {dep['sha'][:7]}"))

        for it in items:
            rec = it.rec
            head = render_record(replace(rec, body="")).split("---\n", 2)[1]
            meta = head + yaml.safe_dump({"project": r.name}, allow_unicode=True)
            commit = it.commit or git(path, "rev-parse", "HEAD", check=False) or sha
            if r.github:
                source = f"https://github.com/{r.github}/blob/{commit}/{it.rel}"
            else:
                source = f"{it.rel}@{commit[:7]}"
            links: list[str] = []
            if rec.supersedes:
                links.append("Supersedes: " + ", ".join(ref(x) for x in rec.supersedes))
            sup_by = rec.superseded_by or reverse.get(rec.id)
            if sup_by:
                links.append("Superseded by: " + ref(sup_by))
            if rec.about:
                links.append("About: " + ", ".join(ref(x) for x in rec.about))
            ks = sorted({g.key for g in rec.guards} | {t.split("#", 1)[1] for t in rec.touches if "#" in t})
            if ks:
                links.append("Keys: " + ", ".join(_link(f"Keys/{_safe(k)}", k) for k in ks))
            fs = sorted({g.file for g in rec.guards} | {t.split("#", 1)[0] for t in rec.touches})
            if fs:
                links.append("Files: " + ", ".join(_link(file_note(f), f) for f in fs))
            deployed = it.__dict__.get("deployed")
            if deployed:
                links.append("Deployed: " + ", ".join(deployed))
            if rec.deployment:
                links.append(f"Deployment: {rec.deployment}")
            text = (f"---\n{meta}---\n\n{_banner(origin, sha)}\n\nSource: {source}\n\n"
                    f"# {rec.id} {rec.title}\n\n{rec.body.strip()}\n")
            if links:
                text += "\n## Links\n\n" + "\n".join(f"- {x}" for x in links) + "\n"
            _write(out, f"{it.note}.md", text, written)

    def hub_note(path_: str, title: str, members: list[_Item]) -> None:
        lines = [f"> Generated from the linked repositories — {BANNER_TAIL}", "", f"# {title}", ""]
        for m in sorted(members, key=lambda m: (m.project, m.rec.id)):
            lines.append(f"- {m.project}: {_link(m.note, m.rec.id)} {m.rec.title} ({m.rec.status})")
        _write(out, f"{path_}.md", "\n".join(lines) + "\n", written)

    for k, members in sorted(keys.items()):
        hub_note(f"Keys/{_safe(k)}", k, members)
    for f, members in sorted(files.items()):
        hub_note(file_note(f), f, members)

    _write(out, "Dashboards/Decisions.md", _dashboard(names, all_items), written)
    _write(out, "Dashboards/Decisions.base", _BASE, written)
    _write(out, OVERVIEW, _overview(names, all_items), written)
    return written


def _deployments(r: HubRepo, path: Path, gh_for) -> list[tuple[str, dict]]:
    if not r.github:
        return []
    out: list[tuple[str, dict]] = []
    try:
        gh = gh_for(r.github)
        if gh is None:
            return []
        for env in load_config(path).environments:
            for dep in gh.deployments(env):
                out.append((env, dep))
    except GitHubUnavailable:
        return []
    return out


def _dashboard(names: list[str], items: list[_Item]) -> str:
    lines = [f"> Generated by ct vault build — {BANNER_TAIL}", "", "# Decisions", ""]
    for n in names:
        decisions = sorted((i for i in items if i.project == n and i.rec.kind == "decision"), key=lambda i: i.rec.id)
        lines += [f"## {n}", ""]
        for title, status in (("Active", "active"), ("Superseded", "superseded")):
            rows = [i for i in decisions if (i.rec.status == status)]
            lines += [f"### {title}", "", "| ID | Title | Author | Created | Superseded by |", "|---|---|---|---|---|"]
            for i in rows:
                by = i.rec.superseded_by or ""
                lines.append(f"| {_link(i.note, i.rec.id)} | {i.rec.title} | {i.rec.author} | {i.rec.created} | {by} |")
            if not rows:
                lines.append("| none | | | | |")
            lines.append("")
    return "\n".join(lines) + "\n"


def _overview(names: list[str], items: list[_Item]) -> str:
    lines = [f"> Generated by ct vault build — {BANNER_TAIL}", "", "# Engineering overview", "",
             "| Project | Active | Superseded | Observations |", "|---|---|---|---|"]
    for n in names:
        mine = [i for i in items if i.project == n]
        a = sum(1 for i in mine if i.rec.kind == "decision" and i.rec.status == "active")
        s = sum(1 for i in mine if i.rec.kind == "decision" and i.rec.status == "superseded")
        o = sum(1 for i in mine if i.rec.kind == "observation")
        lines.append(f"| {n} | {a} | {s} | {o} |")
    recent = sorted((i for i in items if i.rec.kind == "decision"), key=lambda i: (i.rec.created, i.rec.id), reverse=True)[:10]
    lines += ["", "## Recent decisions", ""]
    lines += [f"- {_link(i.note, i.project + ' ' + i.rec.id)} {i.rec.title} ({i.rec.status})" for i in recent] or ["- none"]
    lines += ["", "## Dashboards", "", "- [[Dashboards/Decisions|Decisions]]", ""]
    return "\n".join(lines)


_BASE = """\
filters:
  and:
    - 'kind == "decision"'
views:
  - type: table
    name: Active decisions
    filters:
      and:
        - 'status == "active"'
    order:
      - note.project
      - note.id
      - note.title
      - note.author
      - note.created
  - type: table
    name: Superseded
    filters:
      and:
        - 'status == "superseded"'
    order:
      - note.project
      - note.id
      - note.title
      - note.superseded_by
"""
