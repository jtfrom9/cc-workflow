#!/usr/bin/env python3
"""Conditionally start the summary background worker for a plan.md.

Usage:
    maybe_spawn_summary.py <plan_md_path>

Reads CC_WORKFLOW_SUMMARY_THRESHOLD_LINES (default 50). If plan.md
exceeds that line count, writes a placeholder summary.md in the same
directory and spawns ``_summarize_worker.py`` detached. Otherwise no-op.

Intended to be invoked from the /checkpoint slash command after the
plan.md has been written, but it's safe to call from anywhere.
"""

from __future__ import annotations

import os
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

    threshold = int(os.environ.get("CC_WORKFLOW_SUMMARY_THRESHOLD_LINES", "50"))

    try:
        lines = plan_path.read_text(encoding="utf-8").count("\n")
    except OSError as e:
        print(f"read failed: {e}", file=sys.stderr)
        return 1

    if lines <= threshold:
        print(f"plan.md is {lines} lines (≤ {threshold}); skipping summary.")
        return 0

    summary_path = plan_path.parent / "summary.md"
    summary_path.write_text("_(要約を生成中…)_\n", encoding="utf-8")

    _common.spawn_detached(
        [
            _common.python_executable(),
            str(Path(__file__).parent / "_summarize_worker.py"),
            str(plan_path),
            str(summary_path),
        ]
    )
    print(f"plan.md is {lines} lines; spawned summary worker → {summary_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
