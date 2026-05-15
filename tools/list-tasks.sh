#!/bin/bash
# cc-workflow/tools/list-tasks.sh
#
# /cc-workflow:tasks から呼ばれる。
# 現在のプロジェクトの task 一覧を Markdown テーブルで出力する。

set -uo pipefail

DATA_DIR="${CC_WORKFLOW_DIR:-$HOME/.cc-workflow}"

PROJECT=$(basename "$PWD")

PROJECT_TASKS="$DATA_DIR/tasks/$PROJECT"

echo "## プロジェクト: \`$PROJECT\`"
echo

if [ ! -d "$PROJECT_TASKS" ] || [ -z "$(ls "$PROJECT_TASKS" 2>/dev/null)" ]; then
  echo "(まだ task はありません)"
  exit 0
fi

extract_field() {
  # $1 = file, $2 = key (例: created_at)
  grep "^$2:" "$1" 2>/dev/null \
    | head -1 \
    | sed -E "s/^$2:[[:space:]]*//;s/^\"//;s/\"$//"
}

echo "| taskId | created | source | status |"
echo "|---|---|---|---|"

for d in "$PROJECT_TASKS"/*/; do
  [ -d "$d" ] || continue
  TID=$(basename "$d")
  TM="$d/task.md"
  CREATED=$(extract_field "$TM" "created_at")
  SOURCE=$(extract_field "$TM" "source")
  STATUS=$(extract_field "$TM" "status")
  printf '| `%s` | %s | %s | %s |\n' "$TID" "${CREATED:--}" "${SOURCE:--}" "${STATUS:--}"
done
