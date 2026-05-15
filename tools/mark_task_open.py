#!/usr/bin/env python3
"""Record a taskId as the currently-open task for the current session.

Usage:
    mark_task_open.py <taskId>

Designed to be invoked from slash commands (e.g. /restore) where the
session id isn't directly available; falls back to the mtime-heuristic
session detection in _common.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _common  # noqa: E402


def main() -> int:
    if len(sys.argv) < 2 or not sys.argv[1].strip():
        return 0
    taskid = sys.argv[1].strip()
    _common.mark_task_open(taskid)
    return 0


if __name__ == "__main__":
    sys.exit(main())
