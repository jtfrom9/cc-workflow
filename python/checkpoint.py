#!/usr/bin/env python3
"""checkpoint — unified entry for both auto and manual checkpoint.

The only thing that differs between the two paths is the trigger:

- **auto**:  ``--auto`` flag, called from the ``Stop`` hook with hook JSON on
  stdin. Decides whether to fire based on token-usage growth from the
  most recent task. The slug is auto-generated from the timestamp.
- **manual**: positional slug arg, called from
  ``commands/checkpoint.md``. Always fires; the slug comes from the
  caller (Claude derives it from the conversation content).

Both produce the same kind of task folder with the same ``source: checkpoint``,
the same plan.md / task.md layout, and the same "previous task" semantics
(= the highest-index task in this project, regardless of how it was
created). The manual path additionally has Claude overwrite plan.md with
detailed diff content via the Write tool after this script returns.

Usage:
    python3 checkpoint.py [slug]          # manual mode
    python3 checkpoint.py --auto          # auto mode (Stop hook)
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _common  # noqa: E402


# ----------------------------------------------------------------------
# Decision (auto mode only)
# ----------------------------------------------------------------------

def _should_save_auto(
    sid: str,
    current_tokens: int,
    prev_taskid: str,
    prev_sid: str,
    prev_tokens: int,
    threshold_pct: float,
    max_tokens: int,
) -> tuple[bool, str]:
    """Return (should_save, reason)."""
    if not prev_taskid:
        if current_tokens > threshold_pct * max_tokens:
            return (
                True,
                f"no previous task; {current_tokens} > {int(threshold_pct * max_tokens)} "
                f"({int(threshold_pct * 100)}% of {max_tokens})",
            )
        return (False, "")
    if prev_sid == sid:
        bound = int(prev_tokens * (1 + threshold_pct))
        if current_tokens > bound:
            return (
                True,
                f"same session; {current_tokens} > {bound} "
                f"(prev {prev_tokens} + {int(threshold_pct * 100)}%)",
            )
        return (False, "")
    bound = int(threshold_pct * max_tokens)
    if current_tokens > bound:
        return (
            True,
            f"different session; {current_tokens} > {bound} "
            f"({int(threshold_pct * 100)}% of {max_tokens})",
        )
    return (False, "")


# ----------------------------------------------------------------------
# File writing
# ----------------------------------------------------------------------

def _write_plan_md(
    plan_path: Path,
    task_id: str,
    trigger: str,
    trigger_reason: str,
    transcript: Path,
) -> None:
    """Write the initial plan.md template.

    - auto trigger: ends here. The file stays as a concise pointer.
    - manual trigger: Claude overwrites this file with detailed content
      after the script returns (the script's output is just a fallback).

    Detailed per-task metadata (sid, tokens, prev_*) lives in task.md
    frontmatter so we don't duplicate it here.
    """
    if trigger == "auto":
        body = (
            f"# {task_id}\n\n"
            f"自動 checkpoint。トリガ: {trigger_reason}\n\n"
            f"メタ情報は `task.md` の frontmatter を、"
            f"会話本文はセッショントランスクリプト `{transcript}` を参照してください。\n"
            f"要約が必要なら `/jtfrom9-cc-workflow:summarise` を実行。\n"
        )
    else:
        body = (
            f"# {task_id}\n\n"
            f"_(/jtfrom9-cc-workflow:checkpoint の雛形。"
            f" Claude が直後にこのファイルを詳細内容で上書きします。"
            f" 上書きされていなければエラー。)_\n"
        )
    plan_path.write_text(body, encoding="utf-8")


def _write_task_md(
    task_md_path: Path,
    task_id: str,
    now_iso: str,
    project: str,
    project_root: Path,
    sid: str,
    trigger: str,
    trigger_reason: str,
    current_tokens: int,
    prev_taskid: str,
    prev_tokens: int,
    prev_sid: str,
) -> None:
    body = (
        "ExitPlanMode・自動 Stop フック・/checkpoint コマンドのいずれかから"
        " jtfrom9-cc-workflow が採取した checkpoint。"
    )
    fm_lines = [
        "---",
        f'taskId: "{task_id}"',
        f'created_at: "{now_iso}"',
        f'project: "{project}"',
        f'project_root: "{project_root}"',
        f'session_id: "{sid}"',
        "source: checkpoint",
        f"trigger: {trigger}",
        f"tokens: {current_tokens}",
        f'prev_task_id: "{prev_taskid}"',
        f"prev_tokens: {prev_tokens}",
        f'prev_session_id: "{prev_sid}"',
    ]
    if trigger_reason:
        fm_lines.append(f'trigger_reason: "{trigger_reason}"')
    fm_lines += [
        "status: pending",
        "---",
        "",
        f"# {task_id}",
        "",
        body,
        "",
    ]
    task_md_path.write_text("\n".join(fm_lines), encoding="utf-8")


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------

def main() -> int:
    args = sys.argv[1:]
    auto_mode = "--auto" in args
    args = [a for a in args if a != "--auto"]
    slug_arg = args[0] if args else ""

    threshold_pct = float(os.environ.get("JTFROM9_CC_WORKFLOW_CHECKPOINT_PCT", "30")) / 100.0
    max_tokens = int(os.environ.get("JTFROM9_CC_WORKFLOW_MAX_CONTEXT_TOKENS", "200000"))

    # Resolve session id
    if auto_mode:
        if os.environ.get("JTFROM9_CC_WORKFLOW_AUTO_CHECKPOINT", "1") != "1":
            return 0
        data = _common.read_hook_input()
        sid = data.get("session_id") or ""
        if not sid:
            return 0
    else:
        sid = _common.detect_current_session_id()

    project, project_root = _common.get_project_info()

    # Look up the most recent task in this project (max index)
    prev_task = _common.latest_task_in_project(project)
    prev_taskid = prev_task.name if prev_task else ""
    prev_plan_path = str(prev_task / "plan.md") if prev_task else ""
    prev_fm = _common.parse_frontmatter(prev_task / "task.md") if prev_task else {}
    try:
        prev_tokens = int(prev_fm.get("tokens", "0") or "0")
    except ValueError:
        prev_tokens = 0
    prev_sid = prev_fm.get("session_id", "")
    prev_created = prev_fm.get("created_at", "")

    current_tokens = _common.current_context_tokens(sid, project_root) if sid else 0

    if auto_mode:
        if current_tokens <= 0:
            return 0
        should_save, reason = _should_save_auto(
            sid=sid,
            current_tokens=current_tokens,
            prev_taskid=prev_taskid,
            prev_sid=prev_sid,
            prev_tokens=prev_tokens,
            threshold_pct=threshold_pct,
            max_tokens=max_tokens,
        )
        if not should_save:
            return 0
        slug = f"auto-{datetime.now().strftime('%H%M%S')}"
        trigger = "auto"
        trigger_reason = reason
    else:
        slug = _common.slugify(slug_arg) or "checkpoint"
        trigger = "manual"
        trigger_reason = ""

    # Create task dir + files
    project_tasks = _common.project_tasks_dir(project)
    project_tasks.mkdir(parents=True, exist_ok=True)
    next_index = _common.compute_next_index(project_tasks)
    task_id = _common.make_taskid(next_index, slug)
    task_dir = project_tasks / task_id
    task_dir.mkdir(parents=True, exist_ok=True)

    now_iso = _common.now_iso()
    transcript = _common.session_transcript_path(sid, project_root) if sid else Path("")

    _write_plan_md(
        plan_path=task_dir / "plan.md",
        task_id=task_id,
        trigger=trigger,
        trigger_reason=trigger_reason,
        transcript=transcript,
    )
    _write_task_md(
        task_md_path=task_dir / "task.md",
        task_id=task_id,
        now_iso=now_iso,
        project=project,
        project_root=project_root,
        sid=sid,
        trigger=trigger,
        trigger_reason=trigger_reason,
        current_tokens=current_tokens,
        prev_taskid=prev_taskid,
        prev_tokens=prev_tokens,
        prev_sid=prev_sid,
    )

    # Mark this task as the "open" one (both modes)
    if sid:
        _common.mark_task_open(task_id, session_id=sid)

    # Manual mode: print key=value so the slash command body can consume
    if not auto_mode:
        print(f"taskId={task_id}")
        print(f"task_dir={task_dir}")
        print(f"plan_path={task_dir / 'plan.md'}")
        print(f"task_md_path={task_dir / 'task.md'}")
        print(f"project={project}")
        print(f"project_root={project_root}")
        print(f"created_at={now_iso}")
        print(f"session_id={sid}")
        print(f"prev_taskid={prev_taskid}")
        print(f"prev_plan_path={prev_plan_path}")
        print(f"prev_created={prev_created}")
        print(f"current_tokens={current_tokens}")
        print(f"prev_tokens={prev_tokens}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
