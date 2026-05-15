#!/bin/bash
# jtfrom9-cc-workflow/hooks/relocate-plan.sh
#
# PostToolUse フック（matcher: ExitPlanMode）から呼ばれる。
#
# 動作:
#   1. ExitPlanMode が plansDirectory に書き出したばかりのプランファイルを特定する
#   2. taskId = <0001..>-<YYMMDD>-<元ファイル名> を採番
#   3. ~/.jtfrom9-cc-workflow/tasks/<project>/<taskId>/ を掘って:
#        - plan.md   : 移動したプランファイル
#        - task.md   : メタ情報 (frontmatter に taskId)
#        - summary.md: plan.md が長ければ claude -p で非同期生成
#   4. JTFROM9_CC_WORKFLOW_PAUSE_AFTER_PLAN=1 (デフォルト) なら
#      `continue: false` を返して実装開始前にユーザに制御を戻す
#
# 制約:
#   フック入力には書かれたプランファイルのパスが含まれないため、
#   plansDirectory 内の直近 5 分以内に変更された最新の .md を移動対象とする。

set -uo pipefail

DATA_DIR="${JTFROM9_CC_WORKFLOW_DIR:-$HOME/.jtfrom9-cc-workflow}"
SOURCE_PLANS="${JTFROM9_CC_WORKFLOW_SOURCE_PLANS:-$HOME/.claude/plans}"
PAUSE_AFTER_PLAN="${JTFROM9_CC_WORKFLOW_PAUSE_AFTER_PLAN:-1}"
SUMMARY_THRESHOLD_LINES="${JTFROM9_CC_WORKFLOW_SUMMARY_THRESHOLD_LINES:-200}"

INPUT=$(cat)
SID=$(printf '%s' "$INPUT" | jq -r '.session_id // ""')

# プロジェクト名
if PROJECT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null); then
  PROJECT=$(basename "$PROJECT_ROOT")
else
  PROJECT_ROOT="$PWD"
  PROJECT=$(basename "$PWD")
fi

PROJECT_TASKS="$DATA_DIR/tasks/$PROJECT"
mkdir -p "$PROJECT_TASKS"

# 直近 5 分以内に書かれた .md を探す
LATEST=""
RECENT=$(find "$SOURCE_PLANS" -maxdepth 1 -name '*.md' -type f -mmin -5 2>/dev/null || true)
if [ -n "$RECENT" ]; then
  LATEST=$(printf '%s\n' "$RECENT" | xargs ls -t 2>/dev/null | head -n 1 || true)
fi

# プランファイルが見つからない場合は、必要に応じて pause だけして終わる
if [ -z "$LATEST" ] || [ ! -f "$LATEST" ]; then
  if [ "$PAUSE_AFTER_PLAN" = "1" ]; then
    jq -nc --arg msg "📋 プラン承認を検知しましたが、対応するプランファイルを見つけられませんでした。続行する場合は再度指示してください。" \
      '{continue: false, stopReason: $msg}'
  fi
  exit 0
fi

# taskId の "name" 部分: プラン本文の最初の H1 見出しから派生させる。
# 取れなければ Claude Code が付けた元スラグ (ランダム単語) にフォールバック。
# 日本語タイトルのために LC_ALL=C をつけて sed/tr/awk をバイト単位扱いにする
# (ASCII の空白とパス禁則文字だけ - に潰し、マルチバイト文字はそのまま通す)。
DERIVED_NAME=$(
  LC_ALL=C awk '
    BEGIN { in_fm = 0 }
    NR == 1 && /^---$/ { in_fm = 1; next }
    in_fm && /^---$/   { in_fm = 0; next }
    in_fm              { next }
    /^# +/             { sub(/^# +/, ""); print; exit }
  ' "$LATEST" 2>/dev/null \
    | LC_ALL=C tr -d '[:cntrl:]' \
    | LC_ALL=C sed -E 's|[[:space:]/\\:*?"<>|]+|-|g' \
    | LC_ALL=C sed -E 's/-+/-/g; s/^-+//; s/-+$//'
)
ORIG_NAME="${DERIVED_NAME:-$(basename "$LATEST" .md)}"

# taskId 採番
#   - <project>/.last_index に「これまでに使った最大インデックス」を保持
#   - 既存フォルダの最大値とのうち大きい方 + 1 を新しいインデックスとする
#   - これにより、最大番号のフォルダを削除しても次のインデックスを再利用しない
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
mv "$LATEST" "$TASK_DIR/plan.md"

# task.md (メタ情報)
NOW=$(date +%Y-%m-%dT%H:%M:%S%z)
cat > "$TASK_DIR/task.md" <<EOF
---
taskId: "$TASK_ID"
created_at: "$NOW"
project: "$PROJECT"
project_root: "$PROJECT_ROOT"
session_id: "$SID"
original_plan_name: "$ORIG_NAME"
status: pending
---

# $TASK_ID

タスクのメタ情報。承認直後にプラグインが生成する。
実装過程で得られた知見や決定事項、参照リンクなどはこのファイルに追記する想定。

## Notes

<!-- 自由記述 -->
EOF

# summary.md は plan.md が長いときだけ生成する (claude -p で非同期)。短いときは作らない。
LINES=$(wc -l < "$TASK_DIR/plan.md" | tr -d ' ')
SUMMARY_NOTE=""
if [ "$LINES" -gt "$SUMMARY_THRESHOLD_LINES" ]; then
  echo "_(要約を生成中…)_" > "$TASK_DIR/summary.md"
  (
    PROMPT="次のプランを日本語で簡潔に要約してください。出力は要約本文のみで、見出しや前置きは不要です。

$(cat "$TASK_DIR/plan.md")"
    if SUMMARY=$(claude -p "$PROMPT" 2>/dev/null) && [ -n "$SUMMARY" ]; then
      printf '# Summary\n\n%s\n' "$SUMMARY" > "$TASK_DIR/summary.md"
    else
      printf '# Summary\n\n(要約の自動生成に失敗しました。手動で plan.md を確認してください。)\n' > "$TASK_DIR/summary.md"
    fi
  ) >/dev/null 2>&1 </dev/null &
  disown 2>/dev/null || true
  SUMMARY_NOTE=" plan.md が ${LINES} 行と長いため、要約を別途生成中（summary.md）。"
fi

# ターン停止 (デフォルト)
if [ "$PAUSE_AFTER_PLAN" = "1" ]; then
  REASON="📋 プランを承認し、$TASK_DIR/plan.md に保存しました (taskId: $TASK_ID)。${SUMMARY_NOTE} 内容を確認・編集してから、改めて「進めて」などと指示してください。"
  jq -nc --arg msg "$REASON" '{continue: false, stopReason: $msg}'
fi
