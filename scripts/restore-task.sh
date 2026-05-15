#!/bin/bash
# jtfrom9-cc-workflow/scripts/restore-task.sh
#
# /jtfrom9-restore <taskId> から呼ばれる。
# プロジェクト名を判定して該当 taskId フォルダ配下の
# plan.md / task.md / summary.md を 1 つの出力にまとめて返す。
#
# 引数: $1 = taskId
# 出力: stdout に Markdown 形式でまとめる (失敗時はエラーメッセージ + 候補一覧)

set -uo pipefail

DATA_DIR="${JTFROM9_CC_WORKFLOW_DIR:-$HOME/.jtfrom9-cc-workflow}"
TASKID="${1:-}"

if PROJECT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null); then
  PROJECT=$(basename "$PROJECT_ROOT")
else
  PROJECT=$(basename "$PWD")
fi

PROJECT_TASKS="$DATA_DIR/tasks/$PROJECT"

list_available() {
  echo
  echo "### このプロジェクト ($PROJECT) で利用可能な taskId"
  echo
  # 隠しファイル (.last_index など) は除外する
  if [ -d "$PROJECT_TASKS" ] && [ -n "$(ls "$PROJECT_TASKS" 2>/dev/null)" ]; then
    ls -1 "$PROJECT_TASKS" | sed 's/^/- /'
  else
    echo "(まだ 1 件もありません)"
  fi
}

if [ -z "$TASKID" ]; then
  echo "**エラー: taskId が指定されていません。**"
  echo
  echo "使い方: コマンドの引数に taskId を 1 つ指定してください。"
  list_available
  exit 0
fi

TASK_DIR="$PROJECT_TASKS/$TASKID"
if [ ! -d "$TASK_DIR" ]; then
  echo "**エラー: taskId \`$TASKID\` がプロジェクト \`$PROJECT\` に見つかりません。**"
  list_available
  exit 0
fi

echo "## taskId: \`$TASKID\` (project: \`$PROJECT\`)"
echo
echo "### task.md"
echo
if [ -f "$TASK_DIR/task.md" ]; then
  cat "$TASK_DIR/task.md"
else
  echo "(task.md がありません)"
fi
echo
echo "### plan.md"
echo
if [ -f "$TASK_DIR/plan.md" ]; then
  cat "$TASK_DIR/plan.md"
else
  echo "(plan.md がありません)"
fi
if [ -f "$TASK_DIR/summary.md" ]; then
  echo
  echo "### summary.md"
  echo
  cat "$TASK_DIR/summary.md"
fi
