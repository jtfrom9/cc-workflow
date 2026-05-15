#!/usr/bin/env python3
"""Record a taskId as the currently-open task for the current session.

Usage:
    mark_task_open.py <taskId-or-shortId>

Accepts either the full taskId (``0001-260516-foo-bar``) or the shortId
(``0001-260516``). The shortId is resolved against the current project's
task directory; if exactly one directory matches, that full taskId is
stored. Designed to be invoked from slash commands (e.g. /restore) where
the session id isn't directly available; falls back to the
mtime-heuristic session detection in _common.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _common  # noqa: E402


def main() -> int:
    if len(sys.argv) < 2 or not sys.argv[1].strip():
        return 0
    arg = sys.argv[1].strip()
    project, _root = _common.get_project_info()
    full = _common.resolve_taskid(project, arg)
    if not full:
        # Argument didn't resolve to a known task; nothing to mark.
        return 0
    _common.mark_task_open(full)
    return 0


if __name__ == "__main__":
    sys.exit(main())
