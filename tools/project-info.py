#!/usr/bin/env python3
"""Print the current cc-workflow project name.

Used by shell commands that need the same project resolution as the Python
hooks: prefer the SessionStart-recorded cwd for the current session, then fall
back to the process cwd.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _common  # noqa: E402


def main() -> int:
    project, _project_root = _common.get_project_info()
    print(project)
    return 0


if __name__ == "__main__":
    sys.exit(main())
