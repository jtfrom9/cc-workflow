#!/bin/bash
# cc-workflow/tools/list-tasks.sh
#
# /cc-workflow:tasks から呼ばれる。
# 現在のプロジェクトの task 一覧を Markdown テーブルで出力する。

set -uo pipefail

DATA_DIR="${CC_WORKFLOW_DIR:-$HOME/.cc-workflow}"

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT=$(python3 "$SCRIPT_DIR/project-info.py")

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

echo "| shortId | name | created | source | status |"
echo "|---|---|---|---|---|"

for d in "$PROJECT_TASKS"/*/; do
  [ -d "$d" ] || continue
  TID=$(basename "$d")
  # full taskId = "NNNN-YYMMDD-name" → shortId は先頭 11 文字、name はそれ以降 (`-` を 1 文字飛ばす)
  SHORT="${TID:0:11}"
  NAME="${TID:12}"
  TM="$d/task.md"
  CREATED=$(extract_field "$TM" "created_at")
  SOURCE=$(extract_field "$TM" "source")
  STATUS=$(extract_field "$TM" "status")
  printf '| `%s` | %s | %s | %s | %s |\n' "$SHORT" "${NAME:--}" "${CREATED:--}" "${SOURCE:--}" "${STATUS:--}"
done
