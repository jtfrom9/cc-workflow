#!/usr/bin/env python3
"""UserPromptSubmit hook.

Classify the prompt via a background Haiku call. If the prompt is judged
as a meaningful code-change request, create a task folder under
~/.jtfrom9-cc-workflow/tasks/<project>/<taskId>/ with plan.md (the raw prompt)
and task.md (frontmatter). summary.md is generated only when plan.md exceeds
the line threshold.

The hook itself returns immediately so the user sees no latency. All real
work happens in a detached child Python process.
"""

from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _common  # noqa: E402


# ----------------------------------------------------------------------
# Worker-mode entry (re-entry guarded; runs in a detached subprocess)
# ----------------------------------------------------------------------

def _run_worker(params_path: Path) -> int:
    """Background worker: do the classifier call + task creation."""
    import json
    import subprocess

    try:
        params = json.loads(params_path.read_text(encoding="utf-8"))
    finally:
        try:
            params_path.unlink()
        except OSError:
            pass

    prompt: str = params["prompt"]
    sid: str = params["sid"]
    project: str = params["project"]
    project_root: str = params["project_root"]
    classifier_model: str = params["classifier_model"]
    classifier_input_bytes: int = params["classifier_input_bytes"]
    summary_threshold_lines: int = params["summary_threshold_lines"]

    # Classifier input: cap by bytes, decode safely
    snippet_bytes = prompt.encode("utf-8")[:classifier_input_bytes]
    snippet = snippet_bytes.decode("utf-8", errors="ignore")

    classifier_prompt = (
        "次のユーザ指示は、Claude Code に「複数ファイル編集、新機能の実装、"
        "リファクタリング、まとまったコード修正」など、一定規模のコード変更を要求していますか？\n\n"
        "判定基準:\n"
        "- コードを書き換える明確な要求がある → YES\n"
        "- 質問・説明・調査依頼・1 行レベルの瑣末な修正 → NO\n"
        "- どちらか判断つかない、もしくは雑談的 → NO に倒す\n\n"
        "回答は YES または NO の 1 単語のみ。それ以外は出力しないこと。\n\n"
        "【ユーザ指示】\n" + snippet
    )

    try:
        r = subprocess.run(
            ["claude", "-p", "--model", classifier_model, classifier_prompt],
            capture_output=True,
            text=True,
            timeout=120,
        )
        decision = (r.stdout or "").strip().upper()
    except Exception:
        decision = ""

    if not decision.startswith("YES"):
        return 0

    # Create the task
    project_tasks = _common.project_tasks_dir(project)
    project_tasks.mkdir(parents=True, exist_ok=True)

    derived = _common.extract_h1(prompt) or _common.first_non_empty_line(prompt)
    slug = _common.slugify(derived) or "prompt"

    next_index = _common.compute_next_index(project_tasks)
    task_id = _common.make_taskid(next_index, slug)
    task_dir = project_tasks / task_id
    task_dir.mkdir(parents=True, exist_ok=True)

    plan_md = task_dir / "plan.md"
    plan_md.write_text(
        f"# {slug}\n\n"
        f"_(プランモード外でユーザプロンプトから自動採取された task。分類器判定: {decision})_\n\n"
        f"## 原文プロンプト\n\n{prompt}\n",
        encoding="utf-8",
    )

    task_md = task_dir / "task.md"
    task_md.write_text(
        "---\n"
        f'taskId: "{task_id}"\n'
        f'created_at: "{_common.now_iso()}"\n'
        f'project: "{project}"\n'
        f'project_root: "{project_root}"\n'
        f'session_id: "{sid}"\n'
        f'original_plan_name: "{slug}"\n'
        "source: prompt\n"
        f'classifier_decision: "{decision}"\n'
        "status: pending\n"
        "---\n\n"
        f"# {task_id}\n\n"
        "ユーザがプランモードに入らずに送信した指示文 (`source: prompt`)。\n"
        "分類器が「一定規模のコード変更を要求している」と判定したため task として保存。\n",
        encoding="utf-8",
    )

    # Async summary if long
    lines = plan_md.read_text(encoding="utf-8").count("\n")
    if lines > summary_threshold_lines:
        (task_dir / "summary.md").write_text("_(要約を生成中…)_\n", encoding="utf-8")
        _common.spawn_detached(
            [
                _common.python_executable(),
                str(Path(__file__).parent / "_summarize_worker.py"),
                str(plan_md),
                str(task_dir / "summary.md"),
            ]
        )

    return 0


# ----------------------------------------------------------------------
# Hook-mode entry (called by Claude Code with hook JSON on stdin)
# ----------------------------------------------------------------------

def _run_hook() -> int:
    # Recursion guard
    if os.environ.get("_JTFROM9_CC_WORKFLOW_HOOK_RUNNING") == "1":
        return 0

    enabled = os.environ.get("JTFROM9_CC_WORKFLOW_SAVE_PROMPT_AS_TASK", "1")
    if enabled != "1":
        return 0

    min_len = int(os.environ.get("JTFROM9_CC_WORKFLOW_MIN_LEN_FOR_CLASSIFY", "20"))
    classifier_model = os.environ.get("JTFROM9_CC_WORKFLOW_CLASSIFIER_MODEL", "haiku")
    classifier_input_bytes = int(
        os.environ.get("JTFROM9_CC_WORKFLOW_CLASSIFIER_INPUT_BYTES", "2000")
    )
    summary_threshold_lines = int(
        os.environ.get("JTFROM9_CC_WORKFLOW_SUMMARY_THRESHOLD_LINES", "50")
    )

    data = _common.read_hook_input()
    sid = data.get("session_id", "")
    prompt = data.get("prompt") or data.get("user_prompt") or ""

    if not sid or not prompt or prompt.startswith("/"):
        return 0
    if len(prompt) < min_len:
        return 0

    # Dedup: skip exact-duplicate of previous prompt
    sdir = _common.state_dir_for(sid)
    sdir.mkdir(parents=True, exist_ok=True)
    hash_file = sdir / "last_prompt_hash"
    cur_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    if hash_file.exists() and hash_file.read_text().strip() == cur_hash:
        return 0
    hash_file.write_text(f"{cur_hash}\n")

    project, project_root = _common.get_project_info()

    # Drop the work into a detached child process to keep the hook fast
    params = {
        "prompt": prompt,
        "sid": sid,
        "project": project,
        "project_root": str(project_root),
        "classifier_model": classifier_model,
        "classifier_input_bytes": classifier_input_bytes,
        "summary_threshold_lines": summary_threshold_lines,
    }
    params_path = _common.write_temp_json(params)

    _common.spawn_detached(
        [
            _common.python_executable(),
            str(Path(__file__).resolve()),
            "--worker",
            str(params_path),
        ],
        extra_env={"_JTFROM9_CC_WORKFLOW_HOOK_RUNNING": "1"},
    )
    return 0


# ----------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------

def main() -> int:
    if len(sys.argv) >= 3 and sys.argv[1] == "--worker":
        return _run_worker(Path(sys.argv[2]))
    return _run_hook()


if __name__ == "__main__":
    sys.exit(main())
