#!/usr/bin/env python3
"""Regenerate summary.md for the currently-open task.

The "open task" is whichever taskId was most recently passed to /restore,
created by /checkpoint, or created by the ExitPlanMode hook
(``state/<sid>/open_task_id``). If no task is open, print instructions
pointing the user at /restore.

Usage:
    regenerate_summary.py   (no arguments)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _common  # noqa: E402


def _hint_when_no_open_task(project: str) -> None:
    print("**現在開いている task はありません。**")
    print()
    print("先に `/jtfrom9-cc-workflow:restore <taskId>` で task を読み込んでから、")
    print("`/jtfrom9-cc-workflow:summarise` を実行してください。")
    print()
    print(f"プロジェクト `{project}` の taskId は `/jtfrom9-cc-workflow:tasks` で確認できます。")


def main() -> int:
    project, _ = _common.get_project_info()

    sid = _common.detect_current_session_id()
    if not sid:
        _hint_when_no_open_task(project)
        return 0

    taskid = _common.read_open_task(session_id=sid)
    if not taskid:
        _hint_when_no_open_task(project)
        return 0

    project_tasks = _common.project_tasks_dir(project)
    task_dir = project_tasks / taskid
    if not task_dir.is_dir():
        print(
            f"開いていた taskId `{taskid}` がプロジェクト `{project}` に見つかりません。"
        )
        print("`/jtfrom9-cc-workflow:tasks` で一覧を見て、改めて `/jtfrom9-cc-workflow:restore <taskId>` してください。")
        return 0

    plan_path = task_dir / "plan.md"
    if not plan_path.is_file():
        print(f"plan.md が見つかりません: `{plan_path}`")
        return 0

    summary_path = task_dir / "summary.md"
    summary_path.write_text("_(要約を再生成中…)_\n", encoding="utf-8")

    _common.spawn_detached(
        [
            _common.python_executable(),
            str(Path(__file__).parent / "_summarize_worker.py"),
            str(plan_path),
            str(summary_path),
        ]
    )

    print(
        f"taskId `{taskid}` の要約ワーカーをバックグラウンド起動しました。\n"
        f"- 数十秒で更新されます: `{summary_path}`"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
