#!/usr/bin/env python3
"""CLI wrapper around ``_common.maybe_spawn_summary``.

Usage:
    maybe_spawn_summary.py <plan_md_path>

Intended to be invoked from slash command bodies (e.g. ``/cc-workflow:checkpoint``
after the user-supplied plan.md has been written) when the script needs to
trigger the same size-based summary rule that the Python hooks use.

The actual logic lives in :func:`_common.maybe_spawn_summary` so every
task-creation path (auto checkpoint, manual checkpoint, plan relocation,
this CLI) shares one implementation.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _common  # noqa: E402


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: maybe_spawn_summary.py <plan_md_path>", file=sys.stderr)
        return 1
    plan_path = Path(sys.argv[1])
    if not plan_path.is_file():
        print(f"not a file: {plan_path}", file=sys.stderr)
        return 1
    launched = _common.maybe_spawn_summary(plan_path)
    if launched:
        print(f"spawned summary worker → {plan_path.parent / 'summary.md'}")
    else:
        print("plan.md is within threshold; skipping summary.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
