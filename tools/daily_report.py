#!/usr/bin/env python3
"""daily_report — dump a single day's Claude Code transcript turns.

The ``daily-report`` skill runs this to gather raw material, then Claude
condenses it into a short itemized daily report. Only deterministic
extraction lives here; the summarization judgment is Claude's.

It scans every project under ``~/.claude/projects/`` and emits the
user/assistant turns whose timestamp falls on the target *local* date,
grouped by project and session, as markdown.

Usage:
    python3 daily_report.py [--date YYYY-MM-DD] [--snippet-chars N]
                            [--projects-dir DIR]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path


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


def to_local_date(ts_iso, tz=None):
    """Local calendar date of ``ts_iso``, or ``None`` if unparseable."""
    dt = _parse_ts(ts_iso, tz)
    return dt.date() if dt else None


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


def collect(projects_root, target_date, tz=None):
    """Scan ``projects_root`` for turns on ``target_date``.

    Returns ``(sessions, order)`` where ``sessions`` maps
    ``(project_name, session_id)`` to a list of ``(hm, role, text)`` and
    ``order`` preserves first-seen key order for stable rendering.
    """
    sessions: dict = {}
    order: list = []
    if not projects_root.is_dir():
        return sessions, order
    for proj_dir in sorted(projects_root.iterdir()):
        if not proj_dir.is_dir():
            continue
        for jf in sorted(proj_dir.glob("*.jsonl")):
            for obj in _iter_jsonl(jf):
                if to_local_date(obj.get("timestamp"), tz) != target_date:
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


def render(sessions, order, target_date, snippet_chars):
    """Render collected turns as markdown grouped by project and session."""
    lines = [f"# Transcript dump: {target_date.isoformat()}", ""]
    if not order:
        lines.append("_(no transcript activity found for this date)_")
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
    ap = argparse.ArgumentParser(description="Dump a day's transcript turns.")
    ap.add_argument("--date", help="Target local date YYYY-MM-DD (default: today).")
    ap.add_argument("--snippet-chars", type=int, default=280,
                    help="Per-turn truncation length (default: 280).")
    ap.add_argument("--projects-dir", help="Override ~/.claude/projects root.")
    args = ap.parse_args(argv)

    target = (date.fromisoformat(args.date) if args.date
              else datetime.now().astimezone().date())
    root = (Path(args.projects_dir) if args.projects_dir
            else Path.home() / ".claude" / "projects")

    sessions, order = collect(root, target)
    out = render(sessions, order, target, args.snippet_chars)

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
