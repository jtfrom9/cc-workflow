#!/bin/bash
# jtfrom9-cc-workflow/hooks/save-prompt-as-task.sh
#
# UserPromptSubmit フックから呼ばれる。
# プランモードに入り忘れた指示でも、内容が「一定規模のコード変更要求」であれば
# task として保存する。
#
# 仕組み:
#   1. 表面的なフィルタ (スラッシュコマンド除外、ごく短いプロンプト除外、重複除外)
#   2. バックグラウンドで claude -p (haiku) に YES/NO 分類を依頼
#   3. YES なら通常の task フォルダ構造 (plan.md / task.md / summary.md) を生成
#
# フック自体は即時 return し、ユーザの体感遅延ゼロ。
# 子 claude -p が再帰的にこのフックを発火しないよう環境変数で保護する。
#
# 制約:
#   分類器のレスポンスがブレるので、保守的に判定 (不明確なら NO)。
#   同一プロンプトの完全重複は last_prompt_hash で skip。

set -uo pipefail

# 再帰防止: 子 claude -p からの呼び出しは無視
if [ "${_JTFROM9_CC_WORKFLOW_HOOK_RUNNING:-}" = "1" ]; then
  exit 0
fi

DATA_DIR="${JTFROM9_CC_WORKFLOW_DIR:-$HOME/.jtfrom9-cc-workflow}"
ENABLED="${JTFROM9_CC_WORKFLOW_SAVE_PROMPT_AS_TASK:-1}"
CLASSIFIER_MODEL="${JTFROM9_CC_WORKFLOW_CLASSIFIER_MODEL:-haiku}"
MIN_LEN_FOR_CLASSIFY="${JTFROM9_CC_WORKFLOW_MIN_LEN_FOR_CLASSIFY:-20}"
CLASSIFIER_INPUT_BYTES="${JTFROM9_CC_WORKFLOW_CLASSIFIER_INPUT_BYTES:-2000}"

[ "$ENABLED" = "1" ] || exit 0

INPUT=$(cat)
SID=$(printf '%s' "$INPUT" | jq -r '.session_id // ""')
PROMPT=$(printf '%s' "$INPUT" | jq -r '.prompt // .user_prompt // ""')

[ -z "$SID" ]    && exit 0
[ -z "$PROMPT" ] && exit 0

# スラッシュコマンドは除外
case "$PROMPT" in
  /*) exit 0 ;;
esac

# 物理的に短すぎるプロンプトは分類するまでもなくスキップ
if [ "${#PROMPT}" -lt "$MIN_LEN_FOR_CLASSIFY" ]; then
  exit 0
fi

# 直前のプロンプトと完全一致なら無視
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

# バックグラウンドで分類 → YES なら task 作成
(
  export _JTFROM9_CC_WORKFLOW_HOOK_RUNNING=1

  PROMPT_FOR_CLASSIFIER=$(printf '%s' "$PROMPT" | head -c "$CLASSIFIER_INPUT_BYTES")
  CLASSIFIER_PROMPT="次のユーザ指示は、Claude Code に「複数ファイル編集、新機能の実装、リファクタリング、まとまったコード修正」など、一定規模のコード変更を要求していますか？

判定基準:
- コードを書き換える明確な要求がある → YES
- 質問・説明・調査依頼・1 行レベルの瑣末な修正 → NO
- どちらか判断つかない、もしくは雑談的 → NO に倒す

回答は YES または NO の 1 単語のみ。それ以外は出力しないこと。

【ユーザ指示】
$PROMPT_FOR_CLASSIFIER"

  DECISION=$(claude -p --model "$CLASSIFIER_MODEL" "$CLASSIFIER_PROMPT" 2>/dev/null \
    | tr -d ' \r\n' \
    | tr '[:lower:]' '[:upper:]')

  case "$DECISION" in
    YES*) ;;
    *) exit 0 ;;
  esac

  PROJECT_TASKS="$DATA_DIR/tasks/$PROJECT"
  mkdir -p "$PROJECT_TASKS"

  # 名前: プロンプトの最初の H1、無ければ最初の非空行
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

  # plan.md
  {
    printf '# %s\n\n' "$ORIG_NAME"
    printf '_(プランモード外でユーザプロンプトから自動採取された task。分類器判定: %s)_\n\n' "$DECISION"
    printf '## 原文プロンプト\n\n%s\n' "$PROMPT"
  } > "$TASK_DIR/plan.md"

  # task.md (frontmatter)
  NOW=$(date +%Y-%m-%dT%H:%M:%S%z)
  cat > "$TASK_DIR/task.md" <<TASKEOF
---
taskId: "$TASK_ID"
created_at: "$NOW"
project: "$PROJECT"
project_root: "$PROJECT_ROOT"
session_id: "$SID"
original_plan_name: "$ORIG_NAME"
source: prompt
classifier_decision: "$DECISION"
status: pending
---

# $TASK_ID

ユーザがプランモードに入らずに送信した指示文 (\`source: prompt\`)。
分類器が「一定規模のコード変更を要求している」と判定したため task として保存。
TASKEOF

  # summary.md は plan.md が長いときだけ生成
  SUMMARY_THRESHOLD_LINES="${JTFROM9_CC_WORKFLOW_SUMMARY_THRESHOLD_LINES:-50}"
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
) >/dev/null 2>&1 </dev/null &
disown 2>/dev/null || true
