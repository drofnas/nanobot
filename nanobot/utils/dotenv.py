"""Minimal dotenv loader (no external dependencies).

Loads environment variables from optional .env files, without overriding any
variables that were already present in the process environment.

Precedence:
1) process environment (never overridden)
2) ~/.nanobot/.env (overrides values loaded from ./.
3) ./.env (current working directory)
"""

from __future__ import annotations

import os
from pathlib import Path


def load_dotenv_files(
    *,
    cwd_path: Path | None = None,
    home_path: Path | None = None,
) -> None:
    """
    Load dotenv variables from ./ .env then ~/.nanobot/.env.

    - Existing process env vars are never overridden.
    - ~/.nanobot/.env overrides values loaded from ./ .env.
    """
    protected_keys = set(os.environ.keys())

    local = cwd_path if cwd_path is not None else (Path.cwd() / ".env")
    home = home_path if home_path is not None else (Path.home() / ".nanobot" / ".env")

    # Load local first, then global override.
    _load_one(local, protected_keys=protected_keys, override_existing=False)
    _load_one(home, protected_keys=protected_keys, override_existing=True)


def _load_one(path: Path, *, protected_keys: set[str], override_existing: bool) -> None:
    """Load a single dotenv file if present."""
    try:
        if not path.exists() or not path.is_file():
            return
        text = path.read_text(encoding="utf-8")
    except Exception:
        return

    pairs = _parse_dotenv(text)
    _apply_env(pairs, protected_keys=protected_keys, override_existing=override_existing)


def _apply_env(
    pairs: dict[str, str],
    *,
    protected_keys: set[str],
    override_existing: bool,
) -> None:
    for k, v in pairs.items():
        if not k or k in protected_keys:
            continue
        if not override_existing and k in os.environ:
            continue
        os.environ[k] = v


def _parse_dotenv(text: str) -> dict[str, str]:
    """
    Parse a minimal subset of dotenv format.

    - Supports: KEY=VALUE, optional leading 'export '
    - Ignores blank lines and lines starting with '#'
    - Supports quoted values ('...' or \"...\") and simple escapes for \\n, \\r, \\t, \\\\.
    """
    out: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()

        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        value = value.strip()

        if value and value[0] in ("'", '"') and value[-1:] == value[:1]:
            value = _unescape(value[1:-1], quote=value[:1])

        out[key] = value
    return out


def _unescape(val: str, *, quote: str) -> str:
    # Keep this intentionally small and predictable.
    # Only a few escapes are useful for secrets and multi-line tokens.
    val = val.replace("\\n", "\n").replace("\\r", "\r").replace("\\t", "\t").replace("\\\\", "\\")
    if quote == '"':
        val = val.replace('\\"', '"')
    if quote == "'":
        val = val.replace("\\'", "'")
    return val

