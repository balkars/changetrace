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
    except (ValueError, TypeError):
        return None
    return normalize_value(value)


def _py_assignments(text: str) -> dict[str, str | None] | None:
    """Last module-level value per name (None when not a plain constant); None on parse error."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return None
    out: dict[str, str | None] = {}
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign):
            targets, value = stmt.targets, stmt.value
        elif isinstance(stmt, ast.AnnAssign) and stmt.value is not None:
            targets, value = [stmt.target], stmt.value
        else:
            continue
        val = _evaluate(value)
        for t in targets:
            if isinstance(t, ast.Name):
                out[t.id] = val
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
    m = re.search(rf"^\s*{re.escape(key)}\s*[:=]\s*(.+?)\s*$", text, re.MULTILINE)
    return Extracted("found", normalize_value(m.group(1))) if m else Extracted("missing")


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
