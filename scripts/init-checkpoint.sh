#!/bin/bash
# jtfrom9-cc-workflow/scripts/init-checkpoint.sh
#
# /jtfrom9-cc-workflow:checkpoint から呼ばれる。
# 新しい checkpoint task のディレクトリを掘って、各種 path と
# 「直前の checkpoint (同一セッション内)」の情報を key=value で出力する。
#
# Claude (slash command 側) は出力をパースし、prev_checkpoint_plan が
# 非空ならその plan.md を読んで「前回 checkpoint 以降」を抽出する。
#
# 引数: $1 = 任意のスラグ文字列 (省略時 "checkpoint")

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
STATE_BASE="$DATA_DIR/state"
mkdir -p "$PROJECT_TASKS" "$STATE_BASE"

# 現セッション ID の推定:
#   UserPromptSubmit フック群が state/<sid>/ を毎ターン触るため、
#   mtime が最も新しいサブディレクトリ名を「今のセッション」とみなす。
CURRENT_SID=""
if [ -d "$STATE_BASE" ]; then
  CANDIDATE=$(ls -1t "$STATE_BASE" 2>/dev/null | head -n 1)
  if [ -n "$CANDIDATE" ] && [ -d "$STATE_BASE/$CANDIDATE" ]; then
    CURRENT_SID="$CANDIDATE"
  fi
fi

# 直前 checkpoint の参照 (同セッション内)
PREV_CHECKPOINT_TASKID=""
PREV_CHECKPOINT_PLAN=""
PREV_CHECKPOINT_CREATED=""
if [ -n "$CURRENT_SID" ]; then
  PREV_FILE="$STATE_BASE/$CURRENT_SID/last_checkpoint_taskid"
  if [ -f "$PREV_FILE" ]; then
    CAND=$(cat "$PREV_FILE" 2>/dev/null)
    if [ -n "$CAND" ] && [ -d "$PROJECT_TASKS/$CAND" ]; then
      PREV_CHECKPOINT_TASKID="$CAND"
      PREV_CHECKPOINT_PLAN="$PROJECT_TASKS/$CAND/plan.md"
      if [ -f "$PROJECT_TASKS/$CAND/task.md" ]; then
        PREV_CHECKPOINT_CREATED=$(grep '^created_at:' "$PROJECT_TASKS/$CAND/task.md" 2>/dev/null \
          | head -1 \
          | sed -E 's/^created_at:[[:space:]]*//;s/^"//;s/"$//')
      fi
    fi
  fi
fi

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

# 新 taskId を「このセッションの直近 checkpoint」として記録
if [ -n "$CURRENT_SID" ]; then
  mkdir -p "$STATE_BASE/$CURRENT_SID"
  printf '%s\n' "$TASK_ID" > "$STATE_BASE/$CURRENT_SID/last_checkpoint_taskid"
fi

cat <<EOF
taskId=$TASK_ID
task_dir=$TASK_DIR
plan_path=$TASK_DIR/plan.md
task_md_path=$TASK_DIR/task.md
project=$PROJECT
project_root=$PROJECT_ROOT
created_at=$(date +%Y-%m-%dT%H:%M:%S%z)
session_id=$CURRENT_SID
prev_checkpoint_taskid=$PREV_CHECKPOINT_TASKID
prev_checkpoint_plan=$PREV_CHECKPOINT_PLAN
prev_checkpoint_created=$PREV_CHECKPOINT_CREATED
EOF
