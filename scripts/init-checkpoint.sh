#!/bin/bash
# jtfrom9-cc-workflow/scripts/init-checkpoint.sh
#
# /jtfrom9-cc-workflow:checkpoint から呼ばれる。
# 新しい checkpoint task のディレクトリを掘って、各種 path を key=value で出力する。
# Claude (slash command 側) は出力をパースして、plan.md / task.md を Write ツールで書く。
#
# 引数: $1 = 任意のスラグ用文字列 (省略時は "checkpoint")
# 出力: stdout に key=value 形式 (taskId, task_dir, plan_path, task_md_path, project,
#       project_root, created_at)

set -uo pipefail

DATA_DIR="${JTFROM9_CC_WORKFLOW_DIR:-$HOME/.jtfrom9-cc-workflow}"
NAME_ARG="${1:-checkpoint}"

if PROJECT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null); then
  PROJECT=$(basename "$PROJECT_ROOT")
else
  PROJECT_ROOT="$PWD"
  PROJECT=$(basename "$PWD")
fi

PROJECT_TASKS="$DATA_DIR/tasks/$PROJECT"
mkdir -p "$PROJECT_TASKS"

# スラグ化 (UTF-8 セーフに sed をバイトモードで動かす)
ORIG_NAME=$(
  LC_ALL=C printf '%s' "$NAME_ARG" \
    | LC_ALL=C tr -d '[:cntrl:]' \
    | LC_ALL=C sed -E 's|[[:space:]/\\:*?"<>|]+|-|g' \
    | LC_ALL=C sed -E 's/-+/-/g; s/^-+//; s/-+$//'
)
[ -z "$ORIG_NAME" ] && ORIG_NAME="checkpoint"

# index 採番 (relocate-plan.sh と同じロジック)
YMD=$(date +%y%m%d)
COUNTER_FILE="$PROJECT_TASKS/.last_index"
LAST_FROM_FILE=$(cat "$COUNTER_FILE" 2>/dev/null || echo 0)
case "$LAST_FROM_FILE" in
  ''|*[!0-9]*) LAST_FROM_FILE=0 ;;
esac
LAST_FROM_DIRS=$(ls "$PROJECT_TASKS" 2>/dev/null | grep -oE '^[0-9]{4}' | sort -n | tail -1 || true)
LAST_FROM_DIRS=${LAST_FROM_DIRS:-0}
LAST_USED=$LAST_FROM_FILE
if [ "$((10#$LAST_FROM_DIRS))" -gt "$LAST_USED" ]; then
  LAST_USED=$((10#$LAST_FROM_DIRS))
fi
NEXT_INDEX=$((LAST_USED + 1))
INDEX_PADDED=$(printf '%04d' "$NEXT_INDEX")
printf '%s\n' "$NEXT_INDEX" > "$COUNTER_FILE"

TASK_ID="${INDEX_PADDED}-${YMD}-${ORIG_NAME}"
TASK_DIR="$PROJECT_TASKS/$TASK_ID"
mkdir -p "$TASK_DIR"

cat <<EOF
taskId=$TASK_ID
task_dir=$TASK_DIR
plan_path=$TASK_DIR/plan.md
task_md_path=$TASK_DIR/task.md
project=$PROJECT
project_root=$PROJECT_ROOT
created_at=$(date +%Y-%m-%dT%H:%M:%S%z)
EOF
