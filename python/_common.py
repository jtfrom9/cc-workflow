"""Shared utilities for jtfrom9-cc-workflow Python hooks/scripts.

Standard library only. Cross-platform (macOS / Linux / Windows).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path


# ----------------------------------------------------------------------
# Paths
# ----------------------------------------------------------------------

def data_dir() -> Path:
    """Plugin runtime data root. Honors JTFROM9_CC_WORKFLOW_DIR."""
    d = os.environ.get("JTFROM9_CC_WORKFLOW_DIR")
    if d:
        return Path(d)
    return Path.home() / ".jtfrom9-cc-workflow"


def state_dir_for(session_id: str) -> Path:
    return data_dir() / "state" / session_id


def project_tasks_dir(project: str) -> Path:
    return data_dir() / "tasks" / project


# ----------------------------------------------------------------------
# Hook I/O
# ----------------------------------------------------------------------

def read_hook_input() -> dict:
    """Read the hook JSON payload from stdin. Returns {} on parse failure."""
    try:
        raw = sys.stdin.read()
        if not raw:
            return {}
        return json.loads(raw)
    except Exception:
        return {}


def write_systemmessage(msg: str) -> None:
    json.dump({"systemMessage": msg}, sys.stdout, ensure_ascii=False)


def write_continue_false(reason: str) -> None:
    json.dump({"continue": False, "stopReason": reason}, sys.stdout, ensure_ascii=False)


# ----------------------------------------------------------------------
# Project detection
# ----------------------------------------------------------------------

def get_project_info(cwd: Path | None = None) -> tuple[str, Path]:
    """Return (project_name, project_root_path).

    Uses ``git rev-parse --show-toplevel``; falls back to the cwd's basename.
    """
    cwd = cwd or Path.cwd()
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            root = Path(result.stdout.strip())
            return root.name, root
    except Exception:
        pass
    return cwd.name, cwd


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


_H1_RE = re.compile(r"^# +(.+?)\s*$")


def extract_h1(content: str) -> str:
    """First H1 heading in markdown ``content``, skipping any YAML frontmatter."""
    in_fm = False
    for i, line in enumerate(content.splitlines()):
        stripped = line.strip()
        if i == 0 and stripped == "---":
            in_fm = True
            continue
        if in_fm:
            if stripped == "---":
                in_fm = False
            continue
        m = _H1_RE.match(line)
        if m:
            return m.group(1)
    return ""


def first_non_empty_line(content: str) -> str:
    for line in content.splitlines():
        s = line.strip()
        if s:
            return s
    return ""


# ----------------------------------------------------------------------
# taskId index numbering
# ----------------------------------------------------------------------

_INDEX_PREFIX_RE = re.compile(r"^(\d{4})")


def compute_next_index(project_tasks: Path) -> int:
    """Return the next 4-digit index, persisting it to ``<project>/.last_index``.

    Uses ``max(.last_index, max-existing-dir-prefix) + 1`` so deletion of the
    highest-numbered folder doesn't let the next task reuse the same id.
    """
    project_tasks.mkdir(parents=True, exist_ok=True)
    counter = project_tasks / ".last_index"

    last_from_file = 0
    if counter.exists():
        try:
            last_from_file = int(counter.read_text().strip())
        except (ValueError, OSError):
            last_from_file = 0

    last_from_dirs = 0
    try:
        for entry in project_tasks.iterdir():
            if entry.is_dir():
                m = _INDEX_PREFIX_RE.match(entry.name)
                if m:
                    n = int(m.group(1))
                    if n > last_from_dirs:
                        last_from_dirs = n
    except Exception:
        pass

    last_used = max(last_from_file, last_from_dirs)
    nxt = last_used + 1
    counter.write_text(f"{nxt}\n")
    return nxt


def make_taskid(index: int, slug: str, today: datetime | None = None) -> str:
    today = today or datetime.now()
    return f"{index:04d}-{today.strftime('%y%m%d')}-{slug}"


# ----------------------------------------------------------------------
# Frontmatter (minimal)
# ----------------------------------------------------------------------

def parse_frontmatter(path: Path) -> dict:
    """Read top-of-file YAML-ish frontmatter. Only handles ``key: "value"``
    or ``key: value`` lines; no nested structures."""
    out: dict[str, str] = {}
    if not path.exists():
        return out
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return out
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return out
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if ":" in line:
            k, _, v = line.partition(":")
            k = k.strip()
            v = v.strip()
            if v.startswith('"') and v.endswith('"'):
                v = v[1:-1]
            out[k] = v
    return out


# ----------------------------------------------------------------------
# Time
# ----------------------------------------------------------------------

def now_iso() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")


# ----------------------------------------------------------------------
# "Currently open" task tracking
# ----------------------------------------------------------------------

def open_task_marker(session_id: str) -> Path:
    return state_dir_for(session_id) / "open_task_id"


def mark_task_open(taskid: str, session_id: str | None = None) -> bool:
    """Record ``taskid`` as the currently-open task for this session.

    If ``session_id`` is not provided, falls back to ``detect_current_session_id()``.
    Returns True on success, False when no session id could be determined.
    """
    sid = session_id or detect_current_session_id()
    if not sid:
        return False
    sdir = state_dir_for(sid)
    sdir.mkdir(parents=True, exist_ok=True)
    open_task_marker(sid).write_text(f"{taskid}\n", encoding="utf-8")
    return True


def read_open_task(session_id: str | None = None) -> str:
    """Return the currently-open taskId for ``session_id`` (auto-detect when None)."""
    sid = session_id or detect_current_session_id()
    if not sid:
        return ""
    marker = open_task_marker(sid)
    if not marker.is_file():
        return ""
    try:
        return marker.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


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


def write_temp_json(payload: dict) -> Path:
    """Write JSON payload to a temp file, return its Path.
    Caller (the spawned background) is responsible for unlinking it."""
    fd, name = tempfile.mkstemp(prefix="jtfrom9cc-", suffix=".json", text=True)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    return Path(name)


def python_executable() -> str:
    """Return the running Python interpreter path (for re-invocation)."""
    return sys.executable or "python3"


def claude_command() -> list[str]:
    """Return the argv prefix used to invoke ``claude -p`` for background work.

    Defaults to ``["claude"]``. Overridable via ``JTFROM9_CC_WORKFLOW_CLAUDE_CMD``
    (parsed with :func:`shlex.split`) when the user's environment routes the
    ``claude`` binary through a wrapper that doesn't tolerate non-TTY callers
    (e.g. docker / sandbox wrappers requiring ``-it``). Point this at the real
    underlying binary, or at a stub like ``false`` to disable summary calls.
    """
    raw = os.environ.get("JTFROM9_CC_WORKFLOW_CLAUDE_CMD", "").strip()
    if raw:
        import shlex
        return shlex.split(raw)
    return ["claude"]
