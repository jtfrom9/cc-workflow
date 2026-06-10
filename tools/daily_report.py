#!/usr/bin/env python3
"""daily_report — dump recent Claude Code transcript turns.

The ``daily-report`` skill runs this to gather raw material, then Claude
condenses it into a short itemized daily report. Only deterministic
extraction lives here; the summarization judgment is Claude's.

It scans every project under ``~/.claude/projects/`` and emits the
user/assistant turns whose timestamp falls inside a time window —
by default the rolling last 24 hours back from now — grouped by project
and session, as markdown.

Usage:
    python3 daily_report.py [--hours N] [--date YYYY-MM-DD]
                            [--snippet-chars N] [--projects-dir DIR]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import encode_claude_project_path  # noqa: E402


# ----------------------------------------------------------------------
# Timestamp helpers
# ----------------------------------------------------------------------

def _parse_ts(ts_iso, tz=None):
    """Parse an ISO-8601 timestamp into a tz-aware datetime in ``tz``.

    Accepts the trailing ``Z`` (UTC) form Claude Code writes. Naive
    timestamps are assumed UTC. ``tz=None`` converts to the local zone.
    Returns ``None`` on empty or unparseable input.
    """
    if not ts_iso or not isinstance(ts_iso, str):
        return None
    s = ts_iso.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(tz)


def in_window(ts_iso, start, end):
    """True if ``ts_iso`` parses to an instant in the half-open ``[start, end)``.

    ``start``/``end`` are tz-aware datetimes; the comparison is on absolute
    instants, so the timestamp's own zone is irrelevant. Unparseable input
    is treated as outside the window.
    """
    dt = _parse_ts(ts_iso)
    if dt is None:
        return False
    return start <= dt < end


def to_local_hm(ts_iso, tz=None):
    """Local ``HH:MM`` clock string for ``ts_iso``, or ``""`` if unparseable."""
    dt = _parse_ts(ts_iso, tz)
    return dt.strftime("%H:%M") if dt else ""


# ----------------------------------------------------------------------
# Message extraction
# ----------------------------------------------------------------------

def is_meta_text(text):
    """True for non-human user content: slash-command wrappers, local
    command output, or injected system reminders."""
    if not text:
        return True
    s = text.lstrip()
    return (
        s.startswith("<command-")
        or s.startswith("<local-command")
        or s.startswith("<system-reminder")
    )


def message_text(role, content):
    """Return the human-readable text of a turn, or ``None`` to skip it.

    - user string content is returned as-is.
    - a user turn carrying a ``tool_result`` block is tool output, not a
      human turn, and is skipped.
    - assistant content keeps ``text`` blocks only (``thinking`` and
      ``tool_use`` are dropped).
    """
    if role == "user":
        if isinstance(content, str):
            return content.strip() or None
        if isinstance(content, list):
            parts = []
            for p in content:
                if not isinstance(p, dict):
                    continue
                if p.get("type") == "tool_result":
                    return None
                if p.get("type") == "text":
                    t = (p.get("text") or "").strip()
                    if t:
                        parts.append(t)
            return "\n".join(parts) or None
        return None
    if role == "assistant":
        if isinstance(content, str):
            return content.strip() or None
        if isinstance(content, list):
            parts = []
            for p in content:
                if isinstance(p, dict) and p.get("type") == "text":
                    t = (p.get("text") or "").strip()
                    if t:
                        parts.append(t)
            return "\n".join(parts) or None
        return None
    return None


def truncate(text, limit):
    """Clip ``text`` to ``limit`` characters, ending with ``…`` if clipped."""
    if len(text) <= limit:
        return text
    if limit <= 1:
        return "…"
    return text[: limit - 1] + "…"


# ----------------------------------------------------------------------
# Collection
# ----------------------------------------------------------------------

def _iter_jsonl(path):
    try:
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
    except OSError:
        return


def collect(projects_root, start, end, project=None, tz=None):
    """Scan ``projects_root`` for turns inside the ``[start, end)`` window.

    When ``project`` is given (a Claude Code project directory name), only
    that one project is scanned; otherwise every project is scanned.

    Returns ``(sessions, order)`` where ``sessions`` maps
    ``(project_name, session_id)`` to a list of ``(hm, role, text)`` and
    ``order`` preserves first-seen key order for stable rendering.
    """
    sessions: dict = {}
    order: list = []
    if not projects_root.is_dir():
        return sessions, order
    if project is not None:
        proj_dirs = [projects_root / project]
    else:
        proj_dirs = sorted(projects_root.iterdir())
    for proj_dir in proj_dirs:
        if not proj_dir.is_dir():
            continue
        for jf in sorted(proj_dir.glob("*.jsonl")):
            for obj in _iter_jsonl(jf):
                if not in_window(obj.get("timestamp"), start, end):
                    continue
                msg = obj.get("message")
                if not isinstance(msg, dict):
                    continue
                role = msg.get("role")
                if role not in ("user", "assistant"):
                    continue
                text = message_text(role, msg.get("content"))
                if not text:
                    continue
                if role == "user" and is_meta_text(text):
                    continue
                sid = obj.get("sessionId") or jf.stem
                key = (proj_dir.name, sid)
                if key not in sessions:
                    sessions[key] = []
                    order.append(key)
                sessions[key].append((to_local_hm(obj.get("timestamp"), tz), role, text))
    return sessions, order


def render(sessions, order, start, end, snippet_chars, project=None):
    """Render collected turns as markdown grouped by project and session."""
    span = f"{start:%Y-%m-%d %H:%M} — {end:%Y-%m-%d %H:%M}"
    scope = f", project: {project}" if project else ""
    lines = [f"# Transcript dump: {span} (local{scope})", ""]
    if not order:
        lines.append("_(no transcript activity found in this window)_")
        return "\n".join(lines)
    cur_proj = None
    for key in order:
        proj, sid = key
        if proj != cur_proj:
            lines.append(f"## project: {proj}")
            cur_proj = proj
        lines.append(f"### session {sid[:8]}")
        for hm, role, text in sessions[key]:
            snippet = truncate(" ".join(text.split()), snippet_chars)
            lines.append(f"- [{hm}] {role}: {snippet}")
        lines.append("")
    return "\n".join(lines)


# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(description="Dump recent transcript turns.")
    ap.add_argument("--hours", type=float, default=24.0,
                    help="Rolling window size in hours back from now (default: 24).")
    ap.add_argument("--date",
                    help="Target a full local calendar day YYYY-MM-DD "
                         "instead of the rolling window.")
    ap.add_argument("--all-projects", action="store_true",
                    help="Scan every project, not just the current one.")
    ap.add_argument("--snippet-chars", type=int, default=280,
                    help="Per-turn truncation length (default: 280).")
    ap.add_argument("--projects-dir", help="Override ~/.claude/projects root.")
    args = ap.parse_args(argv)

    now = datetime.now().astimezone()
    if args.date:
        day = date.fromisoformat(args.date)
        start = datetime(day.year, day.month, day.day, tzinfo=now.tzinfo)
        end = start + timedelta(days=1)
    else:
        end = now
        start = now - timedelta(hours=args.hours)
    root = (Path(args.projects_dir) if args.projects_dir
            else Path.home() / ".claude" / "projects")
    project = None if args.all_projects else encode_claude_project_path(Path.cwd())

    sessions, order = collect(root, start, end, project=project)
    out = render(sessions, order, start, end, args.snippet_chars, project=project)

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
