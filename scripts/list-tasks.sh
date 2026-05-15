#!/bin/bash
# jtfrom9-cc-workflow/scripts/list-tasks.sh
#
# /jtfrom9-cc-workflow:tasks から呼ばれる。
# 現在のプロジェクトの task 一覧を Markdown テーブルで出力する。

set -uo pipefail

DATA_DIR="${JTFROM9_CC_WORKFLOW_DIR:-$HOME/.jtfrom9-cc-workflow}"

if PROJECT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null); then
  PROJECT=$(basename "$PROJECT_ROOT")
else
  PROJECT=$(basename "$PWD")
fi

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
