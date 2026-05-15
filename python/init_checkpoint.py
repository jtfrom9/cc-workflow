#!/usr/bin/env python3
"""Helper for /jtfrom9-cc-workflow:checkpoint.

Creates a new checkpoint task directory, picks the next taskId, locates the
previous checkpoint of this session (if any), and prints key=value lines for
the slash command body to consume.

The slash command (commands/checkpoint.md) then has Claude write plan.md and
task.md via the Write tool.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _common  # noqa: E402


def main() -> int:
    name_arg = sys.argv[1] if len(sys.argv) > 1 else ""
    name_arg = name_arg or "checkpoint"

    project, project_root = _common.get_project_info()
    project_tasks = _common.project_tasks_dir(project)
    state_base = _common.data_dir() / "state"
    state_base.mkdir(parents=True, exist_ok=True)
    project_tasks.mkdir(parents=True, exist_ok=True)

    current_sid = _common.detect_current_session_id()

    # Lookup previous checkpoint of this session
    prev_taskid = ""
    prev_plan = ""
    prev_created = ""
    if current_sid:
        marker = state_base / current_sid / "last_checkpoint_taskid"
        if marker.exists():
            cand = marker.read_text().strip()
            cand_dir = project_tasks / cand
            if cand and cand_dir.is_dir():
                prev_taskid = cand
                prev_plan = str(cand_dir / "plan.md")
                fm = _common.parse_frontmatter(cand_dir / "task.md")
                prev_created = fm.get("created_at", "")

    slug = _common.slugify(name_arg) or "checkpoint"
    next_index = _common.compute_next_index(project_tasks)
    task_id = _common.make_taskid(next_index, slug)
    task_dir = project_tasks / task_id
    task_dir.mkdir(parents=True, exist_ok=True)

    # Record new checkpoint as the latest for this session
    if current_sid:
        sdir = state_base / current_sid
        sdir.mkdir(parents=True, exist_ok=True)
        (sdir / "last_checkpoint_taskid").write_text(f"{task_id}\n")

    lines = [
        f"taskId={task_id}",
        f"task_dir={task_dir}",
        f"plan_path={task_dir / 'plan.md'}",
        f"task_md_path={task_dir / 'task.md'}",
        f"project={project}",
        f"project_root={project_root}",
        f"created_at={_common.now_iso()}",
        f"session_id={current_sid}",
        f"prev_checkpoint_taskid={prev_taskid}",
        f"prev_checkpoint_plan={prev_plan}",
        f"prev_checkpoint_created={prev_created}",
    ]
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
