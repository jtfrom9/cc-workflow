---
description: 保存済みプランを taskId で復元してコンテキストに読み込む
argument-hint: <taskId>
allowed-tools: Bash, Read
---

taskId `$ARGUMENTS` の保存済みプランを復元します。以下にそのプランの task.md / plan.md / summary.md を展開しました。
内容を踏まえて、ユーザからの次の指示（例: 「続きから実装して」「修正したい点がある」）を待ってください。

---

!`bash "${CLAUDE_PLUGIN_ROOT}/tools/restore-task.sh" "$ARGUMENTS"`

!`python3 "${CLAUDE_PLUGIN_ROOT}/tools/mark_task_open.py" "$ARGUMENTS"`
