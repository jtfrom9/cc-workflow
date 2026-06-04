#!/usr/bin/env python3
"""Session rate-limit usage for the status line (no ccusage dependency).

Pulls the 5-hour and 7-day rate-limit windows from Anthropic's OAuth usage
endpoint and renders a compact "remaining" segment for the status line:

    🟢 85% 2h21m · 7d 96%
    └ 5h window ┘   └ 7d ┘

The accurate numbers come straight from ``GET /api/oauth/usage`` using the
Claude Code OAuth access token — ccusage is never consulted.

Token retrieval is cross-platform:

  1. ``CLAUDE_CODE_OAUTH_TOKEN`` env override, else
  2. macOS Keychain (``security find-generic-password -s
     "Claude Code-credentials" -w``), else
  3. the ``~/.claude/.credentials.json`` file (Windows / Linux), reading
     ``claudeAiOauth.accessToken``.

The status line must stay fast, so it never blocks on the network: it reads
a cached response and, when that cache is older than the TTL, spawns a
detached ``--refresh`` worker (this script) that fetches and rewrites the
cache. The current (possibly slightly stale) value is rendered meanwhile —
stale-while-revalidate.

Env vars:

  CC_WORKFLOW_SESSION_USAGE   "0" disables the segment entirely (no network)
  CC_WORKFLOW_USAGE_TTL       cache freshness seconds (default 60)
  CLAUDE_CODE_OAUTH_TOKEN     token override (skips keychain/file lookup)
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _common  # noqa: E402


USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
BETA_HEADER = "oauth-2025-04-20"
DEFAULT_TTL = 60
KEYCHAIN_SERVICE = "Claude Code-credentials"


# ----------------------------------------------------------------------
# Pure helpers (unit-tested in tests/test_session_usage.py)
# ----------------------------------------------------------------------

def extract_token_from_blob(text: str) -> str | None:
    """Pull ``claudeAiOauth.accessToken`` out of a credentials JSON blob."""
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    oauth = data.get("claudeAiOauth")
    if isinstance(oauth, dict):
        tok = oauth.get("accessToken")
        if isinstance(tok, str) and tok:
            return tok
    return None


def _window(w: object) -> dict | None:
    """Normalize one usage window into ``{remaining_pct, resets_at}`` or None."""
    if not isinstance(w, dict):
        return None
    util = w.get("utilization")
    if util is None:
        return None
    try:
        remaining = max(0.0, 100.0 - float(util))
    except (TypeError, ValueError):
        return None
    return {"remaining_pct": remaining, "resets_at": w.get("resets_at")}


def parse_usage(data: dict) -> dict:
    """Reduce the raw API payload to the two windows we render."""
    if not isinstance(data, dict):
        data = {}
    return {
        "five_hour": _window(data.get("five_hour")),
        "seven_day": _window(data.get("seven_day")),
    }


def format_time_left(resets_at: str | None, now: datetime) -> str:
    """Render time until ``resets_at`` as ``2h21m`` / ``21m`` / ``<1m``.

    Returns "" when the timestamp is missing, unparseable, or already past.
    """
    if not resets_at:
        return ""
    try:
        reset = datetime.fromisoformat(resets_at)
    except ValueError:
        return ""
    if reset.tzinfo is None:
        reset = reset.replace(tzinfo=timezone.utc)
    secs = (reset - now).total_seconds()
    if secs <= 0:
        return ""
    if secs < 60:
        return "<1m"
    minutes = int(secs // 60)
    hours, mins = divmod(minutes, 60)
    return f"{hours}h{mins}m" if hours else f"{mins}m"


def session_emoji(remaining_pct: float) -> str:
    """Traffic-light by how much of the window is left."""
    if remaining_pct > 50:
        return "🟢"
    if remaining_pct > 20:
        return "🟡"
    if remaining_pct > 5:
        return "🟠"
    return "🔴"


def render_segment(usage: dict, now: datetime) -> str:
    """Build the status-line segment from parsed usage. "" if no 5h window."""
    five = usage.get("five_hour")
    if not five:
        return ""
    rem5 = five["remaining_pct"]
    parts = [f"{session_emoji(rem5)} {round(rem5)}%"]
    left = format_time_left(five.get("resets_at"), now)
    if left:
        parts.append(left)
    seg = " ".join(parts)
    seven = usage.get("seven_day")
    if seven:
        seg += f" · 7d {round(seven['remaining_pct'])}%"
    return seg


# ----------------------------------------------------------------------
# Token retrieval (side-effecting)
# ----------------------------------------------------------------------

def _token_from_keychain() -> str | None:
    try:
        out = subprocess.run(
            ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return extract_token_from_blob(out.stdout.strip())


def get_oauth_token() -> str | None:
    """Resolve the OAuth access token across platforms (see module docstring)."""
    env = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "").strip()
    if env:
        return env
    if sys.platform == "darwin":
        tok = _token_from_keychain()
        if tok:
            return tok
    cred = Path.home() / ".claude" / ".credentials.json"
    if cred.is_file():
        try:
            return extract_token_from_blob(cred.read_text(encoding="utf-8"))
        except OSError:
            return None
    return None


# ----------------------------------------------------------------------
# Network + cache
# ----------------------------------------------------------------------

def fetch_usage(token: str, timeout: float = 6.0) -> dict | None:
    req = urllib.request.Request(
        USAGE_URL,
        headers={
            "Authorization": f"Bearer {token}",
            "anthropic-beta": BETA_HEADER,
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.load(resp)
    except Exception:
        return None


def _cache_dir() -> Path:
    return _common.data_dir() / "cache"


def cache_path() -> Path:
    return _cache_dir() / "oauth-usage.json"


def _lock_path() -> Path:
    return _cache_dir() / ".usage-refresh.lock"


def write_cache(data: dict) -> None:
    d = _cache_dir()
    d.mkdir(parents=True, exist_ok=True)
    cache_path().write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def read_cache() -> tuple[dict | None, float | None]:
    """Return ``(data, age_seconds)`` for the cache, or ``(None, None)``."""
    p = cache_path()
    if not p.is_file():
        return None, None
    try:
        age = time.time() - p.stat().st_mtime
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, None
    return data, age


def _ttl() -> int:
    try:
        return int(os.environ.get("CC_WORKFLOW_USAGE_TTL", str(DEFAULT_TTL)))
    except ValueError:
        return DEFAULT_TTL


def _should_spawn_refresh(ttl: int) -> bool:
    """Throttle refresh spawns so frequent renders don't stampede the API."""
    lock = _lock_path()
    if lock.exists():
        try:
            age = time.time() - lock.stat().st_mtime
        except OSError:
            return True
        if age < min(ttl, 30):
            return False
    return True


def _spawn_refresh() -> None:
    d = _cache_dir()
    d.mkdir(parents=True, exist_ok=True)
    try:
        _lock_path().write_text(str(time.time()), encoding="utf-8")
    except OSError:
        pass
    _common.spawn_detached([_common.python_executable(), str(Path(__file__)), "--refresh"])


def refresh() -> int:
    """``--refresh`` worker: fetch usage and rewrite the cache. Silent."""
    token = get_oauth_token()
    if not token:
        return 0
    data = fetch_usage(token)
    if data is None:
        return 0
    write_cache(data)
    return 0


def load_segment(now: datetime | None = None) -> str:
    """Status-line entry point: render from cache, refresh in the background.

    Never raises and never blocks on the network. Returns "" when the
    feature is disabled, no token/cache exists yet, or rendering fails.
    """
    if os.environ.get("CC_WORKFLOW_SESSION_USAGE", "1") == "0":
        return ""
    try:
        now = now or datetime.now(timezone.utc)
        ttl = _ttl()
        data, age = read_cache()
        if (data is None or age is None or age > ttl) and _should_spawn_refresh(ttl):
            _spawn_refresh()
        if data is None:
            return ""
        return render_segment(parse_usage(data), now)
    except Exception:
        return ""


def main() -> int:
    if "--refresh" in sys.argv[1:]:
        return refresh()
    # Direct invocation prints the segment (handy for debugging). Force UTF-8
    # so the emoji glyphs don't crash on legacy Windows code pages (cp932).
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    print(load_segment())
    return 0


if __name__ == "__main__":
    sys.exit(main())
