"""Shared utilities for cc-workflow Python hooks/scripts.

Standard library only. Cross-platform (macOS / Linux / Windows).
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path


# ----------------------------------------------------------------------
# Paths
# ----------------------------------------------------------------------

def normalize_runtime_path(path: str | Path) -> Path:
    """Convert an MSYS2-style drive path to a native Windows path."""
    raw = str(path).replace("\\", "/")
    if os.name == "nt":
        m = re.match(r"^/([A-Za-z])(?:/(.*))?$", raw)
        if m:
            raw = f"{m.group(1).upper()}:/{m.group(2) or ''}"
        else:
            m = re.match(r"^/cygdrive/([A-Za-z])(?:/(.*))?$", raw)
            if m:
                raw = f"{m.group(1).upper()}:/{m.group(2) or ''}"
    return Path(raw)


def encode_claude_project_path(path: str | Path) -> str:
    """Return Claude Code's directory name for a project transcript path."""
    normalized = normalize_runtime_path(path).as_posix()
    return normalized.replace(":", "-").replace("/", "-")


def data_dir() -> Path:
    """Plugin runtime data root. Honors CC_WORKFLOW_DIR and shell HOME."""
    d = os.environ.get("CC_WORKFLOW_DIR")
    if d:
        return normalize_runtime_path(d)
    home = os.environ.get("HOME")
    if home:
        return normalize_runtime_path(home) / ".cc-workflow"
    return Path.home() / ".cc-workflow"


def state_dir_for(session_id: str) -> Path:
    return data_dir() / "state" / session_id


# ----------------------------------------------------------------------
# Project detection
# ----------------------------------------------------------------------

def get_project_info(
    cwd: Path | None = None,
    session_id: str | None = None,
) -> tuple[str, Path]:
    """Return (project_name, project_root_path).

    Resolution order for ``project_root``:

    1. The caller's explicit ``cwd``.
    2. The cwd recorded by the SessionStart hook (``state/<sid>/cwd``).
       This pins the project to where ``claude`` was launched, even if the
       process cwd shifts later in the session (e.g. when a submodule
       subdirectory becomes the active working location).
    3. ``Path.cwd()`` (the hook process's current cwd) as a last resort.

    ``project_name`` is the resolved root's basename. git is never consulted.
    """
    if cwd is not None:
        return cwd.name, cwd

    sid = session_id or detect_current_session_id()
    if sid:
        cwd_file = state_dir_for(sid) / "cwd"
        if cwd_file.is_file():
            try:
                recorded = cwd_file.read_text(encoding="utf-8").strip()
            except OSError:
                recorded = ""
            if recorded:
                root = normalize_runtime_path(recorded)
                return root.name, root

    fallback = Path.cwd()
    return fallback.name, fallback


# ----------------------------------------------------------------------
# Session detection (mtime heuristic on state/<sid>/)
# ----------------------------------------------------------------------

def detect_current_session_id() -> str:
    """Best-effort session id detection from state dir mtimes.

    Returns the most recently modified subdirectory under ``data_dir()/state/``,
    or an empty string if none. UserPromptSubmit hooks touch
    ``state/<sid>/`` every turn, so this is reliable in practice.
    """
    base = data_dir() / "state"
    if not base.exists():
        return ""
    try:
        subs = [d for d in base.iterdir() if d.is_dir()]
        if not subs:
            return ""
        latest = max(subs, key=lambda d: d.stat().st_mtime)
        return latest.name
    except Exception:
        return ""


# ----------------------------------------------------------------------
# Text helpers
# ----------------------------------------------------------------------

_UNSAFE_RE = re.compile(r'[\s/\\:*?"<>|]+')
_MULTI_DASH_RE = re.compile(r"-+")


def slugify(text: str) -> str:
    """Filesystem-safe slug. Preserves UTF-8 (e.g. Japanese kanji)."""
    if not text:
        return ""
    # Strip control characters
    text = "".join(c for c in text if ord(c) >= 32 and c != "\x7f")
    text = _UNSAFE_RE.sub("-", text)
    text = _MULTI_DASH_RE.sub("-", text)
    text = text.strip("-")
    return text


# ----------------------------------------------------------------------
# Time
# ----------------------------------------------------------------------

def now_iso() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")


# ----------------------------------------------------------------------
# Cross-platform detached subprocess (POSIX + Windows)
# ----------------------------------------------------------------------

def spawn_detached(args: list[str], extra_env: dict | None = None) -> None:
    """Spawn a fully detached background subprocess.

    POSIX: ``start_new_session=True``.
    Windows: ``CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS``.
    """
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    kwargs: dict = dict(
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
        close_fds=True,
    )
    if sys.platform == "win32":
        creationflags = 0
        for name in ("CREATE_NEW_PROCESS_GROUP", "DETACHED_PROCESS", "CREATE_NO_WINDOW"):
            creationflags |= getattr(subprocess, name, 0)
        kwargs["creationflags"] = creationflags
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(args, **kwargs)


def python_executable() -> str:
    """Return the running Python interpreter path (for re-invocation)."""
    return sys.executable or "python3"
