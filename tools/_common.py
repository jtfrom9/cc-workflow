"""Shared utilities for cc-workflow Python hooks/scripts.

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
    """Plugin runtime data root. Honors CC_WORKFLOW_DIR."""
    d = os.environ.get("CC_WORKFLOW_DIR")
    if d:
        return Path(d)
    return Path.home() / ".cc-workflow"


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
                root = Path(recorded)
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


# A taskId always starts with ``NNNN-YYMMDD`` (4 digits, dash, 6 digits) =
# 11 characters; the "name" suffix follows after another dash.
_SHORT_TASKID_RE = re.compile(r"^(\d{4}-\d{6})(?:-(.+))?$")


def split_taskid(taskid: str) -> tuple[str, str]:
    """Split a full taskId into ``(shortId, name)``.

    Example:
        >>> split_taskid("0001-260516-foo-bar")
        ("0001-260516", "foo-bar")
    """
    m = _SHORT_TASKID_RE.match(taskid)
    if not m:
        return (taskid, "")
    return (m.group(1), m.group(2) or "")


def resolve_taskid(project: str, arg: str) -> str | None:
    """Resolve a user-supplied taskId argument to a full taskId.

    Accepts either:
      - the full taskId (``0001-260516-foo-bar``) — returned as-is if the
        directory exists,
      - the shortId (``0001-260516``) — resolved by globbing
        ``tasks/<project>/<shortId>-*`` for a unique match.

    Returns ``None`` if no directory matches, or if a shortId matches more
    than one directory (which should not happen in practice since the
    (index, date) pair is unique per project).
    """
    if not arg:
        return None
    project_tasks = project_tasks_dir(project)
    if not project_tasks.is_dir():
        return None
    if (project_tasks / arg).is_dir():
        return arg
    # Try as shortId
    matches = sorted(
        p for p in project_tasks.glob(f"{arg}-*") if p.is_dir()
    )
    if len(matches) == 1:
        return matches[0].name
    return None


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
# Claude Code session transcript inspection
# ----------------------------------------------------------------------

def session_transcript_path(session_id: str, project_root: Path) -> Path:
    """Return the JSONL transcript path Claude Code uses for this session.

    Claude Code encodes ``project_root`` by replacing path separators with ``-``
    and stores transcripts at ``~/.claude/projects/<encoded>/<session_id>.jsonl``.
    """
    encoded = project_root.as_posix().replace("/", "-")
    return Path.home() / ".claude" / "projects" / encoded / f"{session_id}.jsonl"


def current_context_tokens(session_id: str, project_root: Path) -> int:
    """Return the largest ``cache_read + cache_creation + input_tokens`` seen in
    the session's transcript.

    Treated as a proxy for "context size in tokens at the most recent turn"
    because Claude Code emits this triple in the per-turn ``message.usage``
    of each assistant response.
    """
    transcript = session_transcript_path(session_id, project_root)
    if not transcript.is_file():
        return 0
    latest = 0
    try:
        with transcript.open(encoding="utf-8") as f:
            for line in f:
                try:
                    obj = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                msg = obj.get("message")
                if not isinstance(msg, dict):
                    continue
                usage = msg.get("usage")
                if not isinstance(usage, dict):
                    continue
                cr = usage.get("cache_read_input_tokens") or 0
                cc = usage.get("cache_creation_input_tokens") or 0
                it = usage.get("input_tokens") or 0
                tot = cr + cc + it
                if tot > latest:
                    latest = tot
    except OSError:
        return 0
    return latest


def extract_session_slice(
    transcript_path: Path,
    session_id: str,
    after_iso: str = "",
    before_iso: str = "",
) -> str:
    """Return user+assistant messages from the JSONL as markdown.

    Filters:
      - matching ``session_id``
      - ``after_iso < timestamp <= before_iso`` (either bound may be "" to skip)

    Each retained message becomes a ``## user`` / ``## assistant`` block with
    text content concatenated. Non-text content (tool_use, images, ...) is
    described briefly so the summary can still mention it.
    """
    if not transcript_path.is_file():
        return ""

    out: list[str] = []
    try:
        with transcript_path.open(encoding="utf-8") as f:
            for line in f:
                try:
                    obj = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                if session_id and obj.get("sessionId") != session_id:
                    continue
                ts = obj.get("timestamp", "")
                if after_iso and ts and ts <= after_iso:
                    continue
                if before_iso and ts and ts > before_iso:
                    continue

                msg = obj.get("message")
                if not isinstance(msg, dict):
                    continue
                role = msg.get("role")
                if role not in ("user", "assistant"):
                    continue

                parts: list[str] = []
                content = msg.get("content")
                if isinstance(content, str):
                    if content.strip():
                        parts.append(content)
                elif isinstance(content, list):
                    for p in content:
                        if not isinstance(p, dict):
                            continue
                        kind = p.get("type")
                        if kind == "text":
                            t = p.get("text", "")
                            if t and t.strip():
                                parts.append(t)
                        elif kind == "tool_use":
                            name = p.get("name", "?")
                            parts.append(f"_[tool_use: {name}]_")
                        elif kind == "tool_result":
                            parts.append("_[tool_result]_")
                        elif kind == "thinking":
                            parts.append("_[thinking]_")

                if parts:
                    out.append(f"## {role}")
                    out.append("")
                    out.append("\n\n".join(parts))
                    out.append("")
    except OSError:
        return ""

    return "\n".join(out)


def latest_task_in_project(project: str) -> Path | None:
    """Return the task folder with the highest 4-digit index in this project,
    or ``None`` if there are no tasks yet. Hidden entries (``.last_index``)
    are skipped."""
    pdir = project_tasks_dir(project)
    if not pdir.is_dir():
        return None
    best: Path | None = None
    best_idx = -1
    try:
        for entry in pdir.iterdir():
            if not entry.is_dir() or entry.name.startswith("."):
                continue
            m = _INDEX_PREFIX_RE.match(entry.name)
            if m:
                idx = int(m.group(1))
                if idx > best_idx:
                    best_idx = idx
                    best = entry
    except OSError:
        return None
    return best


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


# ----------------------------------------------------------------------
# Summary spawn (uniform rule across all task-creation paths)
# ----------------------------------------------------------------------

def maybe_spawn_summary(plan_path: Path) -> bool:
    """If ``plan.md`` exceeds the configured line threshold, write a
    placeholder ``summary.md`` next to it and spawn ``_summarize_worker.py``
    detached. Returns True if the worker was launched, False otherwise
    (file missing, short content, or read failure).

    This is the single rule for whether a task gets a summary at capture
    time: it depends only on ``plan.md`` size. Every path that produces a
    task (auto checkpoint, manual checkpoint, plan relocation, the
    ``maybe_spawn_summary.py`` CLI used from the /summarise flow) goes
    through here.
    """
    if not plan_path.is_file():
        return False
    threshold = int(os.environ.get("CC_WORKFLOW_SUMMARY_THRESHOLD_LINES", "50"))
    try:
        lines = plan_path.read_text(encoding="utf-8").count("\n")
    except OSError:
        return False
    if lines <= threshold:
        return False
    summary_path = plan_path.parent / "summary.md"
    summary_path.write_text("_(要約を生成中…)_\n", encoding="utf-8")
    spawn_detached(
        [
            python_executable(),
            str(Path(__file__).parent / "_summarize_worker.py"),
            str(plan_path),
            str(summary_path),
        ]
    )
    return True


def claude_command() -> list[str]:
    """Return the argv prefix used to invoke ``claude -p`` for background work.

    Defaults to ``["claude"]``. Overridable via ``CC_WORKFLOW_CLAUDE_CMD``
    (parsed with :func:`shlex.split`) when the user's environment routes the
    ``claude`` binary through a wrapper that doesn't tolerate non-TTY callers
    (e.g. docker / sandbox wrappers requiring ``-it``). Point this at the real
    underlying binary, or at a stub like ``false`` to disable summary calls.
    """
    raw = os.environ.get("CC_WORKFLOW_CLAUDE_CMD", "").strip()
    if raw:
        import shlex
        return shlex.split(raw)
    return ["claude"]
