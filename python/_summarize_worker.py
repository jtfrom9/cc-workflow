#!/usr/bin/env python3
"""Background worker invoked by relocate_plan.py / save_prompt_as_task.py.

Calls ``claude -p`` to generate a Japanese summary of plan.md and overwrites
summary.md. Failures are caught and a graceful failure note is written.

Usage:
    _summarize_worker.py <plan_md_path> <summary_md_path>
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


FAILURE_MD = "# Summary\n\n(要約の自動生成に失敗しました。手動で plan.md を確認してください。)\n"


def main() -> int:
    if len(sys.argv) < 3:
        return 1
    plan_path = Path(sys.argv[1])
    summary_path = Path(sys.argv[2])

    try:
        plan_text = plan_path.read_text(encoding="utf-8")
    except OSError:
        summary_path.write_text(FAILURE_MD, encoding="utf-8")
        return 0

    prompt = (
        "次のプランを日本語で簡潔に要約してください。出力は要約本文のみで、見出しや前置きは不要です。\n\n"
        + plan_text
    )
    try:
        r = subprocess.run(
            ["claude", "-p", prompt],
            capture_output=True,
            text=True,
            timeout=180,
        )
        summary = (r.stdout or "").strip()
    except Exception:
        summary = ""

    if summary:
        summary_path.write_text(f"# Summary\n\n{summary}\n", encoding="utf-8")
    else:
        summary_path.write_text(FAILURE_MD, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
