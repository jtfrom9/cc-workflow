#!/usr/bin/env python3
"""checkpoint — single entry point for both the auto-checkpoint Stop hook
and the manual /jtfrom9-cc-workflow:checkpoint helper.

Usage:
    python3 checkpoint.py hook
        Called from the ``Stop`` hook (after Claude finishes a response).
        Reads stdin JSON, inspects the session transcript's token usage,
        and creates a task folder if the threshold rules below are met.

    python3 checkpoint.py init [slug]
        Called from the slash command body (commands/checkpoint.md).
        Allocates a new taskId and prints key=value paths for the slash
        command (= Claude) to write plan.md / task.md into.

Trigger rules for ``hook`` mode:
    - "Previous task" = the task with the highest 4-digit index in
      ``~/.jtfrom9-cc-workflow/tasks/<project>/`` (regardless of source).
    - If previous task is in the SAME session_id → save when current
      context tokens > prev tokens × (1 + threshold_pct).
    - If previous task is in a DIFFERENT session → save when current
      context tokens > max_context × threshold_pct.
    - If no previous task → save when current context tokens >
      max_context × threshold_pct.

Env vars:
    JTFROM9_CC_WORKFLOW_AUTO_CHECKPOINT (default 1) — 0 disables hook mode.
    JTFROM9_CC_WORKFLOW_CHECKPOINT_PCT (default 30) — threshold percent.
    JTFROM9_CC_WORKFLOW_MAX_CONTEXT_TOKENS (default 200000) — context window
        size used for the "different session" rule. Set to 1000000 for the
        Opus 1M variant.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _common  # noqa: E402


# ----------------------------------------------------------------------
# Hook mode (Stop event)
# ----------------------------------------------------------------------

def _decide_save(
    project: str,
    sid: str,
    current_tokens: int,
    threshold_pct: float,
    max_tokens: int,
) -> tuple[bool, str, dict]:
    """Returns (should_save, reason, prev_info).

    ``prev_info`` is a small dict with prev_task_id, prev_tokens, prev_sid
    suitable for stamping into task.md frontmatter.
    """
    prev_info = {"prev_task_id": "", "prev_tokens": 0, "prev_sid": ""}
    last_task = _common.latest_task_in_project(project)

    if last_task is None:
        if current_tokens > threshold_pct * max_tokens:
            return (
                True,
                f"no previous task; {current_tokens} > {int(threshold_pct * max_tokens)} "
                f"({int(threshold_pct * 100)}% of {max_tokens})",
                prev_info,
            )
        return (False, "", prev_info)

    fm = _common.parse_frontmatter(last_task / "task.md")
    prev_sid = fm.get("session_id", "")
    try:
        prev_tokens = int(fm.get("tokens", "0") or "0")
    except ValueError:
        prev_tokens = 0
    prev_info.update(
        prev_task_id=last_task.name,
        prev_tokens=prev_tokens,
        prev_sid=prev_sid,
    )

    if prev_sid == sid:
        # Same session: % growth from last save
        bound = int(prev_tokens * (1 + threshold_pct))
        if current_tokens > bound:
            return (
                True,
                f"same session; {current_tokens} > {bound} "
                f"(prev {prev_tokens} + {int(threshold_pct * 100)}%)",
                prev_info,
            )
    else:
        # Different session: % of max
        bound = int(threshold_pct * max_tokens)
        if current_tokens > bound:
            return (
                True,
                f"different session; {current_tokens} > {bound} "
                f"({int(threshold_pct * 100)}% of {max_tokens})",
                prev_info,
            )
    return (False, "", prev_info)


def _write_auto_task(
    project: str,
    project_root: Path,
    sid: str,
    current_tokens: int,
    reason: str,
    prev_info: dict,
) -> str:
    """Create the task dir + plan.md + task.md for an auto checkpoint.
    Returns the new taskId."""
    from datetime import datetime

    project_tasks = _common.project_tasks_dir(project)
    project_tasks.mkdir(parents=True, exist_ok=True)

    now_dt = datetime.now()
    slug = f"auto-{now_dt.strftime('%H%M%S')}"
    next_index = _common.compute_next_index(project_tasks)
    task_id = _common.make_taskid(next_index, slug, today=now_dt)
    task_dir = project_tasks / task_id
    task_dir.mkdir(parents=True, exist_ok=True)

    now_iso = _common.now_iso()
    transcript = _common.session_transcript_path(sid, project_root)

    plan_md = (
        f"# Auto-checkpoint {now_iso}\n\n"
        f"_(Stop フックで自動採取された checkpoint。トリガ: {reason})_\n\n"
        f"- 採取時刻: `{now_iso}`\n"
        f"- セッション ID: `{sid}`\n"
        f"- 現在のコンテキスト使用量: `{current_tokens:,}` tokens\n"
        f"- 前回タスク: `{prev_info['prev_task_id'] or '(なし)'}`\n"
        f"- 前回タスク時のトークン: `{prev_info['prev_tokens']:,}`\n"
        f"- 前回セッション ID: `{prev_info['prev_sid'] or '(なし)'}`\n\n"
        f"会話の中身はセッショントランスクリプトを参照: `{transcript}`\n"
    )
    (task_dir / "plan.md").write_text(plan_md, encoding="utf-8")

    task_md = (
        "---\n"
        f'taskId: "{task_id}"\n'
        f'created_at: "{now_iso}"\n'
        f'project: "{project}"\n'
        f'project_root: "{project_root}"\n'
        f'session_id: "{sid}"\n'
        "source: checkpoint-auto\n"
        f"tokens: {current_tokens}\n"
        f'prev_task_id: "{prev_info["prev_task_id"]}"\n'
        f"prev_tokens: {prev_info['prev_tokens']}\n"
        f'prev_session_id: "{prev_info["prev_sid"]}"\n'
        f'trigger_reason: "{reason}"\n'
        "status: pending\n"
        "---\n\n"
        f"# {task_id}\n\n"
        "Stop フックでトークン使用量の閾値を超えたため自動採取された checkpoint。\n"
    )
    (task_dir / "task.md").write_text(task_md, encoding="utf-8")

    return task_id


def run_hook() -> int:
    if os.environ.get("JTFROM9_CC_WORKFLOW_AUTO_CHECKPOINT", "1") != "1":
        return 0
    threshold_pct = float(os.environ.get("JTFROM9_CC_WORKFLOW_CHECKPOINT_PCT", "30")) / 100.0
    max_tokens = int(os.environ.get("JTFROM9_CC_WORKFLOW_MAX_CONTEXT_TOKENS", "200000"))

    data = _common.read_hook_input()
    sid = data.get("session_id") or ""
    if not sid:
        return 0

    project, project_root = _common.get_project_info()

    current_tokens = _common.current_context_tokens(sid, project_root)
    if current_tokens <= 0:
        return 0

    should_save, reason, prev_info = _decide_save(
        project=project,
        sid=sid,
        current_tokens=current_tokens,
        threshold_pct=threshold_pct,
        max_tokens=max_tokens,
    )
    if not should_save:
        return 0

    _write_auto_task(
        project=project,
        project_root=project_root,
        sid=sid,
        current_tokens=current_tokens,
        reason=reason,
        prev_info=prev_info,
    )
    return 0


# ----------------------------------------------------------------------
# Init mode (called from the manual /checkpoint slash command body)
# ----------------------------------------------------------------------

def run_init(name_arg: str) -> int:
    name_arg = name_arg or "checkpoint"

    project, project_root = _common.get_project_info()
    project_tasks = _common.project_tasks_dir(project)
    state_base = _common.data_dir() / "state"
    state_base.mkdir(parents=True, exist_ok=True)
    project_tasks.mkdir(parents=True, exist_ok=True)

    current_sid = _common.detect_current_session_id()

    # Lookup previous checkpoint of this session (only manual /checkpoint chain)
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

    # Update sentinels
    if current_sid:
        sdir = state_base / current_sid
        sdir.mkdir(parents=True, exist_ok=True)
        (sdir / "last_checkpoint_taskid").write_text(f"{task_id}\n")
        _common.mark_task_open(task_id, session_id=current_sid)

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


# ----------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------

def main() -> int:
    if len(sys.argv) < 2:
        print("usage: checkpoint.py {hook|init [slug]}", file=sys.stderr)
        return 1
    mode = sys.argv[1]
    if mode == "hook":
        return run_hook()
    if mode == "init":
        slug = sys.argv[2] if len(sys.argv) > 2 else ""
        return run_init(slug)
    print(f"unknown mode: {mode}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
