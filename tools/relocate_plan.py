#!/usr/bin/env python3
"""PostToolUse(ExitPlanMode) hook.

1. Find the just-written plan file in the default plansDirectory.
2. Move it to ~/.cc-workflow/tasks/<project>/<taskId>/plan.md
   with a content-derived taskId.
3. Write task.md (frontmatter + body).
4. Generate summary.md asynchronously when plan.md exceeds the line threshold.
5. Optionally emit `{continue: false, stopReason: ...}` to stop the turn so the
   user can review the plan before implementation starts (controlled by
   CC_WORKFLOW_PAUSE_AFTER_PLAN, default on).
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _common  # noqa: E402


SOURCE_PLANS = Path(
    os.environ.get("CC_WORKFLOW_SOURCE_PLANS")
    or (Path.home() / ".claude" / "plans")
)
PAUSE_AFTER_PLAN = os.environ.get("CC_WORKFLOW_PAUSE_AFTER_PLAN", "1") == "1"


def find_latest_plan_md(within_seconds: int = 300) -> Path | None:
    """Latest *.md under SOURCE_PLANS (top-level only) modified within the
    last ``within_seconds``."""
    if not SOURCE_PLANS.exists():
        return None
    cutoff = time.time() - within_seconds
    candidates: list[Path] = []
    try:
        for p in SOURCE_PLANS.iterdir():
            if p.is_file() and p.suffix == ".md":
                try:
                    if p.stat().st_mtime >= cutoff:
                        candidates.append(p)
                except OSError:
                    continue
    except OSError:
        return None
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def derive_name(plan_text: str, fallback: str) -> str:
    """Slug for the taskId: first H1 → first non-empty line → fallback."""
    cand = _common.extract_h1(plan_text)
    slug = _common.slugify(cand) if cand else ""
    if slug:
        return slug
    cand = _common.first_non_empty_line(plan_text)
    slug = _common.slugify(cand) if cand else ""
    return slug or fallback


def main() -> int:
    data = _common.read_hook_input()
    sid = data.get("session_id", "")

    project, project_root = _common.get_project_info(session_id=sid)
    project_tasks = _common.project_tasks_dir(project)
    project_tasks.mkdir(parents=True, exist_ok=True)

    latest = find_latest_plan_md()
    if latest is None:
        if PAUSE_AFTER_PLAN:
            _common.write_continue_false(
                "📋 プラン承認を検知しましたが、対応するプランファイルを見つけられませんでした。続行する場合は再度指示してください。"
            )
        return 0

    plan_text = ""
    try:
        plan_text = latest.read_text(encoding="utf-8")
    except OSError:
        pass

    fallback = latest.stem
    slug = derive_name(plan_text, fallback)
    next_index = _common.compute_next_index(project_tasks)
    task_id = _common.make_taskid(next_index, slug)
    task_dir = project_tasks / task_id
    task_dir.mkdir(parents=True, exist_ok=True)

    # Move plan
    plan_dest = task_dir / "plan.md"
    try:
        latest.replace(plan_dest)
    except OSError:
        # Fallback to copy + remove
        plan_dest.write_text(plan_text, encoding="utf-8")
        try:
            latest.unlink()
        except OSError:
            pass

    # task.md
    fm = (
        "---\n"
        f'taskId: "{task_id}"\n'
        f'created_at: "{_common.now_iso()}"\n'
        f'project: "{project}"\n'
        f'project_root: "{project_root}"\n'
        f'session_id: "{sid}"\n'
        f'original_plan_name: "{slug}"\n'
        "source: plan\n"
        "status: pending\n"
        "---\n\n"
        f"# {task_id}\n\n"
        "ExitPlanMode で承認されたプラン本体を `plan.md` に保存し、メタ情報をこのファイルに残している。\n"
    )
    (task_dir / "task.md").write_text(fm, encoding="utf-8")

    if sid:
        _common.mark_task_open(task_id, session_id=sid)

    summary_launched = _common.maybe_spawn_summary(task_dir / "plan.md")

    if PAUSE_AFTER_PLAN:
        note = ""
        if summary_launched:
            note = " plan.md が長いため、要約を別途生成中（summary.md）。"
        reason = (
            f"📋 プランを承認し、{plan_dest} に保存しました (taskId: {task_id})。"
            f"{note} 内容を確認・編集してから、改めて「進めて」などと指示してください。"
        )
        _common.write_continue_false(reason)

    return 0


if __name__ == "__main__":
    sys.exit(main())
