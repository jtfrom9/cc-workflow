#!/usr/bin/env python3
"""Status line for Claude Code: show context window usage.

Wire it up by adding the following to ``~/.claude/settings.json`` (or any
settings file loaded via ``--settings``)::

    {
      "statusLine": {
        "type": "command",
        "command": "python3 /<absolute path to plugin>/tools/status_line.py"
      }
    }

Reads the current session transcript (``~/.claude/projects/<encoded-cwd>/
<session-id>.jsonl``) from the tail, locates the most recent assistant
``message.usage`` entry, and renders the cumulative input tokens against
the model's known context window.

Appends a session rate-limit "remaining" segment from
``session_usage.load_segment()`` (5-hour / 7-day windows), refreshed in the
background so the status line never blocks on the network.

Output example::

    🧠 ██████░░░░ 562k/1M (56%) · claude-opus-4-7 · 🟢 85% 2h21m · 7d 96%
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _common  # noqa: E402
import session_usage  # noqa: E402

# The status line renders emoji and box-drawing glyphs that legacy Windows
# console code pages (e.g. cp932) cannot encode, which would crash the script
# with UnicodeEncodeError. Force UTF-8 output regardless of the console code
# page so the line renders everywhere.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass


# Approximate per-model context windows (in tokens).
# Falls through to 200k if nothing matches.
_MODEL_WINDOWS: list[tuple[str, int]] = [
    # explicit "[1m]" / "1m" suffix means the 1M extended-context variant
    (r"(?:\[1m\]|-1m\b|_1m\b|1m$)", 1_000_000),
    # Opus 4.x defaults to 1M extended in current product positioning
    (r"opus-?4", 1_000_000),
    (r"sonnet-?4", 200_000),
    (r"haiku-?4", 200_000),
]


def _max_tokens_for(model_id: str) -> int:
    lower = model_id.lower()
    for pat, n in _MODEL_WINDOWS:
        if re.search(pat, lower):
            return n
    return 200_000


def _encoded_cwd(cwd: str) -> str:
    if not cwd:
        return ""
    return _common.encode_claude_project_path(cwd)


def _locate_transcript(payload: dict) -> Path | None:
    tp = payload.get("transcript_path") or ""
    if tp:
        p = Path(tp)
        if p.is_file():
            return p
    sid = payload.get("session_id") or ""
    cwd = payload.get("cwd") or os.getcwd()
    if not sid:
        return None
    enc = _encoded_cwd(cwd)
    if not enc:
        return None
    candidate = Path.home() / ".claude" / "projects" / enc / f"{sid}.jsonl"
    return candidate if candidate.is_file() else None


def _read_last_usage(transcript: Path, tail_bytes: int = 256_000) -> dict | None:
    """Scan the tail of the JSONL for the most recent ``message.usage`` block."""
    try:
        with transcript.open("rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - tail_bytes))
            data = f.read()
    except OSError:
        return None
    # Process newest line first
    for raw in reversed(data.splitlines()):
        if b'"cache_read_input_tokens"' not in raw:
            continue
        try:
            obj = json.loads(raw)
        except Exception:
            continue
        msg = obj.get("message") if isinstance(obj, dict) else None
        if not isinstance(msg, dict):
            continue
        usage = msg.get("usage")
        if isinstance(usage, dict) and any(
            usage.get(k) for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
        ):
            return usage
    return None


def _short_model_id(model_id: str) -> str:
    # Strip any "[1m]" suffix and dated tail
    s = re.sub(r"\[.*?\]$", "", model_id).strip()
    return s


def _fmt(n: int) -> str:
    if n >= 1_000_000:
        v = n / 1_000_000
        s = f"{v:.1f}".rstrip("0").rstrip(".")
        return f"{s}M"
    if n >= 1_000:
        return f"{n // 1_000}k"
    return str(n)


def _bar(used: int, total: int, width: int = 10) -> str:
    if total <= 0:
        return ""
    ratio = max(0.0, min(1.0, used / total))
    filled = int(round(width * ratio))
    return "█" * filled + "░" * (width - filled)


def _append(line: str, segment: str) -> str:
    """Append a non-empty session segment with the standard separator."""
    return f"{line} · {segment}" if segment else line


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except Exception:
        payload = {}

    model_info = payload.get("model") or {}
    model_id = ""
    if isinstance(model_info, dict):
        model_id = model_info.get("id") or model_info.get("display_name") or ""
    elif isinstance(model_info, str):
        model_id = model_info

    # Session rate-limit segment (independent of the conversation transcript).
    session = session_usage.load_segment()

    transcript = _locate_transcript(payload)
    usage = _read_last_usage(transcript) if transcript is not None else None

    if not usage:
        # Render a minimal line so the status bar still shows something useful.
        print(_append(f"🧠 — · {_short_model_id(model_id) or '?'}", session))
        return 0

    used = (
        int(usage.get("input_tokens") or 0)
        + int(usage.get("cache_creation_input_tokens") or 0)
        + int(usage.get("cache_read_input_tokens") or 0)
    )
    max_tokens = _max_tokens_for(model_id)
    pct = int(round(used / max_tokens * 100)) if max_tokens else 0
    bar = _bar(used, max_tokens)
    short = _short_model_id(model_id) or "?"

    print(_append(f"🧠 {bar} {_fmt(used)}/{_fmt(max_tokens)} ({pct}%) · {short}", session))
    return 0


if __name__ == "__main__":
    sys.exit(main())
