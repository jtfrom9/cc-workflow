#!/usr/bin/env python3
"""Resolve a user-supplied taskId argument to a full taskId for the
current project.

Usage:
    resolve-taskid.py <arg>

The argument may be either the full taskId (``0001-260516-foo-bar``) or
the shortId prefix (``0001-260516``). On success the full taskId is
printed to stdout and exit code 0. If the argument cannot be resolved to
a unique task directory, nothing is printed and exit code 1 is returned.

Intended to be called from shell scripts that need the same resolution
behavior as the Python tooling.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _common  # noqa: E402


def main() -> int:
    if len(sys.argv) < 2 or not sys.argv[1].strip():
        return 1
    arg = sys.argv[1].strip()
    project, _root = _common.get_project_info()
    full = _common.resolve_taskid(project, arg)
    if not full:
        return 1
    print(full)
    return 0


if __name__ == "__main__":
    sys.exit(main())
