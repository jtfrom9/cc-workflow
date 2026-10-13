#!/usr/bin/env python3
"""Status line for Claude Code: context usage, cost and rate-limit windows.

Wire it up by adding the following to ``~/.claude/settings.json`` (or any
settings file loaded via ``--settings``)::

    {
      "statusLine": {
        "type": "command",
        "command": "python3 /<absolute path to plugin>/tools/status_line.py"
      }
    }

Everything is rendered from the JSON Claude Code pipes on stdin
(https://code.claude.com/docs/en/statusline); no transcript parsing and no
network access:

- ``context_window``: used tokens / window size / ``used_percentage``
- ``cost.total_cost_usd``: client-side estimate at list price (not the bill)
- ``rate_limits.five_hour`` / ``seven_day``: Pro/Max subscription windows

Output example::

    📁 cc-workflow · 🧠 ██████░░░░ 562k/1M (56%) · claude-opus-5-5 · 💰$1.23 · 🟢 85% 2h21m · 7d 96%
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

# The status line renders emoji and box-drawing glyphs that legacy Windows
# console code pages (e.g. cp932) cannot encode, which would crash the script
# with UnicodeEncodeError. Force UTF-8 output regardless of the console code
# page so the line renders everywhere.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass


def _num(v: object) -> float | None:
    """Coerce a JSON value to float, or None if it is missing / non-numeric."""
    if isinstance(v, bool):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _dict(payload: dict, key: str) -> dict:
    v = payload.get(key)
    return v if isinstance(v, dict) else {}


def _fmt(n: float) -> str:
    if n >= 1_000_000:
        s = f"{n / 1_000_000:.1f}".rstrip("0").rstrip(".")
        return f"{s}M"
    if n >= 1_000:
        return f"{round(n / 1_000)}k"
    return str(int(n))


def _bar(ratio: float, width: int = 10) -> str:
    ratio = max(0.0, min(1.0, ratio))
    filled = int(round(width * ratio))
    return "█" * filled + "░" * (width - filled)


def _append(line: str, segment: str) -> str:
    """Append a non-empty segment with the standard separator."""
    return f"{line} · {segment}" if segment else line


def _model_label(payload: dict) -> str:
    """Model id without any bracketed variant suffix (e.g. ``[1m]``)."""
    model = payload.get("model")
    if isinstance(model, str):
        name = model
    elif isinstance(model, dict):
        name = model.get("id") or model.get("display_name") or ""
    else:
        name = ""
    return re.sub(r"\[.*?\]$", "", name).strip() or "?"


def _context_segment(payload: dict) -> str:
    """Render ``context_window`` as ``🧠 <bar> used/size (pct%)``.

    ``used_percentage`` is null before the first API response and right after
    ``/compact``; render ``🧠 —`` then instead of guessing.
    """
    cw = _dict(payload, "context_window")
    pct = _num(cw.get("used_percentage"))
    size = _num(cw.get("context_window_size"))
    if pct is None or not size:
        return "🧠 —"
    used = _num(cw.get("total_input_tokens"))
    if used is None:
        used = size * pct / 100
    return f"🧠 {_bar(pct / 100)} {_fmt(used)}/{_fmt(size)} ({round(pct)}%)"


def _cost_segment(payload: dict) -> str:
    """Render ``cost.total_cost_usd`` as ``💰$1.23``.

    Claude Code estimates this client-side at API list price for every model,
    so for Pro/Max subscribers it is a notional figure, not what is billed.
    "" when absent, non-numeric, or zero.
    """
    total = _num(_dict(payload, "cost").get("total_cost_usd"))
    if total is None or total <= 0:
        return ""
    return f"💰${total:.2f}"


def _format_time_left(resets_at: object, now: float) -> str:
    """Render seconds until ``resets_at`` (epoch seconds) as ``2h21m`` / ``21m`` / ``<1m``."""
    reset = _num(resets_at)
    if reset is None:
        return ""
    secs = reset - now
    if secs <= 0:
        return ""
    if secs < 60:
        return "<1m"
    hours, mins = divmod(int(secs // 60), 60)
    return f"{hours}h{mins}m" if hours else f"{mins}m"


def _limit_emoji(remaining_pct: float) -> str:
    """Traffic light by how much of the window is left."""
    if remaining_pct > 50:
        return "🟢"
    if remaining_pct > 20:
        return "🟡"
    if remaining_pct > 5:
        return "🟠"
    return "🔴"


def _remaining(window: object) -> float | None:
    if not isinstance(window, dict):
        return None
    used = _num(window.get("used_percentage"))
    return None if used is None else max(0.0, 100.0 - used)


def _rate_limit_segment(payload: dict, now: float | None = None) -> str:
    """Render ``rate_limits`` as ``🟢 85% 2h21m · 7d 96%`` (remaining share).

    ``rate_limits`` is only present for Pro/Max subscribers after the first
    API response, and each window may be absent on its own.
    """
    now = time.time() if now is None else now
    limits = _dict(payload, "rate_limits")
    parts: list[str] = []
    five = limits.get("five_hour")
    rem5 = _remaining(five)
    if rem5 is not None:
        seg = f"{_limit_emoji(rem5)} {round(rem5)}%"
        left = _format_time_left(five.get("resets_at"), now)
        parts.append(f"{seg} {left}" if left else seg)
    rem7 = _remaining(limits.get("seven_day"))
    if rem7 is not None:
        parts.append(f"7d {round(rem7)}%")
    return " · ".join(parts)


def _folder_label(payload: dict) -> str:
    """Basename of the session's working directory, or "" if unknown."""
    cwd = _dict(payload, "workspace").get("current_dir") or payload.get("cwd") or ""
    return Path(cwd).name if cwd else ""


def render(payload: dict, now: float | None = None) -> str:
    folder = _folder_label(payload)
    line = f"📁 {folder} · " if folder else ""
    line += f"{_context_segment(payload)} · {_model_label(payload)}"
    line = _append(line, _cost_segment(payload))
    return _append(line, _rate_limit_segment(payload, now))


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    print(render(payload))
    return 0


if __name__ == "__main__":
    sys.exit(main())
