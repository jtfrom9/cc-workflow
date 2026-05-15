#!/bin/bash
# jtfrom9-cc-workflow/hooks/save-prompt-as-task.sh
#
# UserPromptSubmit フックから呼ばれる。
# プランモードに入り忘れた指示でも task として保存するための補完的な仕組み。
# 一定文字数以上のプロンプトを受けたとき、~/.jtfrom9-cc-workflow/tasks/<project>/<taskId>/
# に plan.md (= プロンプト本文) / task.md / summary.md を作成する。
#
# 制約:
#   - / で始まるスラッシュコマンドは対象外
#   - 同一プロンプトの連続入力で重複しないよう、直前と完全一致するプロンプトはスキップ
#   - プランモードで ExitPlanMode が走る場合は別途 relocate-plan.sh が task を作るため、
#     1 つの論理タスクに対して 2 つの task フォルダが生まれることがある (許容)
#
# 設計上、relocate-plan.sh と index 採番・命名規則は揃える。

set -uo pipefail

DATA_DIR="${JTFROM9_CC_WORKFLOW_DIR:-$HOME/.jtfrom9-cc-workflow}"
PROMPT_THRESHOLD_CHARS=${JTFROM9_CC_WORKFLOW_PROMPT_TASK_THRESHOLD_CHARS:-100}
ENABLED="${JTFROM9_CC_WORKFLOW_SAVE_PROMPT_AS_TASK:-1}"

[ "$ENABLED" = "1" ] || exit 0

INPUT=$(cat)
SID=$(printf '%s' "$INPUT" | jq -r '.session_id // ""')
PROMPT=$(printf '%s' "$INPUT" | jq -r '.prompt // .user_prompt // ""')

[ -z "$SID" ]    && exit 0
[ -z "$PROMPT" ] && exit 0

# スラッシュコマンドはスキップ
case "$PROMPT" in
  /*) exit 0 ;;
esac

# 長さチェック
LEN=${#PROMPT}
[ "$LEN" -lt "$PROMPT_THRESHOLD_CHARS" ] && exit 0

# 直前のプロンプトと完全一致なら重複なのでスキップ
STATE_DIR="$DATA_DIR/state/$SID"
mkdir -p "$STATE_DIR"
LAST_HASH_FILE="$STATE_DIR/last_prompt_hash"
CUR_HASH=$(printf '%s' "$PROMPT" | shasum -a 256 | cut -c1-64)
if [ -f "$LAST_HASH_FILE" ] && [ "$(cat "$LAST_HASH_FILE")" = "$CUR_HASH" ]; then
  exit 0
fi
printf '%s\n' "$CUR_HASH" > "$LAST_HASH_FILE"

# プロジェクト
if PROJECT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null); then
  PROJECT=$(basename "$PROJECT_ROOT")
else
  PROJECT_ROOT="$PWD"
  PROJECT=$(basename "$PWD")
fi

PROJECT_TASKS="$DATA_DIR/tasks/$PROJECT"
mkdir -p "$PROJECT_TASKS"

# 名前: プロンプトの最初の H1 (なければ最初の非空行)
DERIVED_NAME=$(
  LC_ALL=C awk '
    BEGIN { in_fm = 0 }
    NR == 1 && /^---$/ { in_fm = 1; next }
    in_fm && /^---$/   { in_fm = 0; next }
    in_fm              { next }
    /^# +/             { sub(/^# +/, ""); print; exit }
  ' <<<"$PROMPT" \
    | LC_ALL=C tr -d '[:cntrl:]' \
    | LC_ALL=C sed -E 's|[[:space:]/\\:*?"<>|]+|-|g' \
    | LC_ALL=C sed -E 's/-+/-/g; s/^-+//; s/-+$//'
)
if [ -z "$DERIVED_NAME" ]; then
  DERIVED_NAME=$(
    LC_ALL=C awk 'NF { print; exit }' <<<"$PROMPT" \
      | LC_ALL=C tr -d '[:cntrl:]' \
      | LC_ALL=C sed -E 's|[[:space:]/\\:*?"<>|]+|-|g' \
      | LC_ALL=C sed -E 's/-+/-/g; s/^-+//; s/-+$//'
  )
fi
ORIG_NAME="${DERIVED_NAME:-prompt}"

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

# plan.md = プロンプトそのまま (見出しを付けて視認性を上げる)
{
  printf '# %s\n\n' "$ORIG_NAME"
  printf '_(プランモード外でユーザプロンプトから自動採取された task)_\n\n'
  printf '## 原文プロンプト\n\n%s\n' "$PROMPT"
} > "$TASK_DIR/plan.md"

# task.md (frontmatter に source: prompt)
NOW=$(date +%Y-%m-%dT%H:%M:%S%z)
cat > "$TASK_DIR/task.md" <<EOF
---
taskId: "$TASK_ID"
created_at: "$NOW"
project: "$PROJECT"
project_root: "$PROJECT_ROOT"
session_id: "$SID"
original_plan_name: "$ORIG_NAME"
source: prompt
status: pending
---

# $TASK_ID

ユーザがプランモードに入らずに送信した指示文 (\`source: prompt\`)。
plan.md は Claude が組み立てたプランではなく、ユーザの原文プロンプトそのもの。
EOF

# summary.md は plan.md が長いときだけ生成する (claude -p で非同期)。短いときは作らない。
SUMMARY_THRESHOLD_LINES="${JTFROM9_CC_WORKFLOW_SUMMARY_THRESHOLD_LINES:-200}"
LINES=$(wc -l < "$TASK_DIR/plan.md" | tr -d ' ')
if [ "$LINES" -gt "$SUMMARY_THRESHOLD_LINES" ]; then
  echo "_(要約を生成中…)_" > "$TASK_DIR/summary.md"
  (
    SUM_PROMPT="次のプロンプト由来 task を日本語で簡潔に要約してください。出力は要約本文のみで、見出しや前置きは不要です。

$(cat "$TASK_DIR/plan.md")"
    if SUMMARY=$(claude -p "$SUM_PROMPT" 2>/dev/null) && [ -n "$SUMMARY" ]; then
      printf '# Summary\n\n%s\n' "$SUMMARY" > "$TASK_DIR/summary.md"
    else
      printf '# Summary\n\n(要約の自動生成に失敗しました。)\n' > "$TASK_DIR/summary.md"
    fi
  ) >/dev/null 2>&1 </dev/null &
  disown 2>/dev/null || true
fi
