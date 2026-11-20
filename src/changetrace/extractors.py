"""Read a key's current value out of a source or config file (deterministic, no I/O)."""
from __future__ import annotations

import ast
import json
import re
import tomllib
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Literal

import yaml


@dataclass(frozen=True)
class Extracted:
    status: Literal["found", "missing", "unreadable"]
    value: str | None = None


def _clean(text: str) -> str:
    return text.replace("\r\n", "\n").lstrip("\ufeff")


def normalize_value(v: object) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    s = str(v).strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        s = s[1:-1].strip()
    if s in ("True", "False"):
        s = s.lower()
    return s


def values_equal(a: str, b: str) -> bool:
    na, nb = normalize_value(a), normalize_value(b)
    if na == nb:
        return True
    try:
        return float(na) == float(nb)
    except ValueError:
        return False


def _kind(filename: str) -> str:
    name = PurePosixPath(filename.replace("\\", "/")).name.lower()
    if name.startswith(".env") or name.endswith(".env"):
        return "env"
    return {
        ".py": "py", ".yml": "yaml", ".yaml": "yaml", ".json": "json", ".toml": "toml",
    }.get(PurePosixPath(name).suffix, "other")


# ---- Python -------------------------------------------------------------

_BUILTINS = {"int": int, "float": float, "str": str, "bool": bool}
_ENV_GETTERS = {"getenv", "os.getenv", "os.environ.get"}


def _dotted(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_dotted(node.value)}.{node.attr}"
    return ""


def _evaluate(node: ast.AST) -> str | None:
    """Python's actual result for a literal, optionally wrapped in int/float/str/bool
    and/or an env getter's default; None when not statically readable."""
    applied = []
    while isinstance(node, ast.Call) and not node.keywords:
        fn = _dotted(node.func)
        if fn in _BUILTINS and len(node.args) == 1:
            applied.append(_BUILTINS[fn])
            node = node.args[0]
        elif fn in _ENV_GETTERS and len(node.args) == 2:
            node = node.args[1]
        else:
            return None
    if not isinstance(node, ast.Constant):
        return None
    value = node.value
    try:
        for fn in reversed(applied):
            value = fn(value)
    except (ValueError, TypeError, OverflowError, RecursionError):
        return None
    return normalize_value(value)


_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)


def _bound_names(node: ast.AST) -> set[str]:
    """Names bound anywhere under node at module scope (function/class bodies excluded)."""
    names: set[str] = set()
    stack = [node]
    while stack:
        n = stack.pop()
        if isinstance(n, _SCOPES):
            if not isinstance(n, ast.Lambda):
                names.add(n.name)
            continue
        if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
            names.add(n.id)
        elif isinstance(n, (ast.Global, ast.Nonlocal)):
            names.update(n.names)
        elif isinstance(n, ast.ExceptHandler) and n.name:
            names.add(n.name)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            for alias in n.names:
                names.add((alias.asname or alias.name).split(".")[0])
        elif isinstance(n, (ast.MatchAs, ast.MatchStar)) and n.name:
            names.add(n.name)
        elif isinstance(n, ast.MatchMapping) and n.rest:
            names.add(n.rest)
        stack.extend(ast.iter_child_nodes(n))
    return names


def _py_assignments(text: str) -> dict[str, str | None] | None:
    """Value per module-level name (None when not a plain top-level constant assignment,
    including any other kind of binding); None on parse error."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return None
    out: dict[str, str | None] = {}
    tainted: set[str] = set()
    for stmt in tree.body:
        plain = False
        if isinstance(stmt, ast.Assign):
            targets, value = stmt.targets, stmt.value
            plain = all(isinstance(t, ast.Name) for t in targets)
        elif isinstance(stmt, ast.AnnAssign) and stmt.value is not None:
            targets, value = [stmt.target], stmt.value
            plain = isinstance(stmt.target, ast.Name)
        if plain:
            tainted |= _bound_names(value)  # walrus inside the value
            val = _evaluate(value)
            for t in targets:
                out[t.id] = val
        else:
            tainted |= _bound_names(stmt)
    for name in tainted:
        out[name] = None
    return out


# ---- structured / env ---------------------------------------------------

def _load(kind: str, text: str) -> object:
    if kind == "yaml":
        return yaml.safe_load(text)
    if kind == "json":
        return json.loads(text)
    return tomllib.loads(text)


def _leaves(obj: object, prefix: str = "") -> dict[str, str]:
    out: dict[str, str] = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.update(_leaves(v, f"{prefix}.{k}" if prefix else str(k)))
    elif prefix and not isinstance(obj, (list, tuple)):
        out[prefix] = normalize_value("null" if obj is None else obj)
    return out


_ENV_LINE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_.]*)\s*=\s*(.*?)\s*$")


def _env_pairs(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.split("\n"):
        if line.lstrip().startswith("#"):
            continue
        m = _ENV_LINE.match(line)
        if m:
            out[m.group(1)] = normalize_value(m.group(2))
    return out


# ---- public API ---------------------------------------------------------

def extract_value(filename: str, text: str, key: str) -> Extracted:
    text = _clean(text)
    kind = _kind(filename)
    if kind == "py":
        assigned = _py_assignments(text)
        if assigned is None:
            return Extracted("unreadable")
        if key not in assigned:
            return Extracted("missing")
        val = assigned[key]
        return Extracted("unreadable") if val is None else Extracted("found", val)
    if kind in ("yaml", "json", "toml"):
        try:
            node = _load(kind, text)
        except Exception:
            return Extracted("unreadable")
        for part in key.split("."):
            if not isinstance(node, dict) or part not in node:
                return Extracted("missing")
            node = node[part]
        if isinstance(node, (dict, list, tuple)):
            return Extracted("unreadable")
        return Extracted("found", normalize_value("null" if node is None else node))
    if kind == "env":
        pairs = _env_pairs(text)
        return Extracted("found", pairs[key]) if key in pairs else Extracted("missing")
    found = [
        normalize_value(m.group(1))
        for m in re.finditer(rf"^\s*{re.escape(key)}\s*[:=]\s*(.+?)\s*$", text, re.MULTILINE)
    ]
    if not found:
        return Extracted("missing")
    if any(not values_equal(found[0], other) for other in found[1:]):
        return Extracted("unreadable")
    return Extracted("found", found[-1])


def read_keys(filename: str, text: str) -> dict[str, str]:
    text = _clean(text)
    kind = _kind(filename)
    if kind == "py":
        assigned = _py_assignments(text) or {}
        return {k: v for k, v in assigned.items() if v is not None and k.isupper()}
    if kind in ("yaml", "json", "toml"):
        try:
            return _leaves(_load(kind, text))
        except Exception:
            return {}
    if kind == "env":
        return _env_pairs(text)
    return {}


def changed_keys(
    filename: str, old_text: str | None, new_text: str
) -> list[tuple[str, str | None, str]]:
    new = read_keys(filename, new_text)
    old = None if old_text is None else read_keys(filename, old_text)
    out: list[tuple[str, str | None, str]] = []
    for key in sorted(new):
        prev = None if old is None else old.get(key)
        if prev is None or not values_equal(prev, new[key]):
            out.append((key, prev, new[key]))
    return out
