#!/bin/bash
# jtfrom9-cc-workflow/hooks/suggest-rename.sh
#
# UserPromptSubmit フックから呼ばれる。
# 長めのユーザ入力が一定回数続いたら 1 度だけ `/rename` を提案する。
#
# stdin: Claude Code が JSON で渡す。`.session_id` と `.prompt` を見る。
# stdout: 提案するときだけ {"systemMessage": "..."} を出力する。それ以外は無音。

set -euo pipefail

THRESHOLD_CHARS=${JTFROM9_CC_WORKFLOW_RENAME_THRESHOLD_CHARS:-100}
THRESHOLD_COUNT=${JTFROM9_CC_WORKFLOW_RENAME_THRESHOLD_COUNT:-4}
DATA_DIR="${JTFROM9_CC_WORKFLOW_DIR:-$HOME/.jtfrom9-cc-workflow}"

INPUT=$(cat)
SID=$(printf '%s' "$INPUT" | jq -r '.session_id // empty')
PROMPT=$(printf '%s' "$INPUT" | jq -r '.prompt // .user_prompt // ""')

[ -z "$SID" ] && exit 0

DIR="$DATA_DIR/state/$SID"
mkdir -p "$DIR"

# 1. /rename が叩かれた → 以後は追跡しない
case "$PROMPT" in
  /rename*) touch "$DIR/renamed"; exit 0 ;;
esac

# 2. すでに提案済み or rename 済みなら何もしない
[ -f "$DIR/suggested" ] && exit 0
[ -f "$DIR/renamed" ]   && exit 0

# 3. 「大きな指示」フィルタ: 文字数 (バイト数) で判定
LEN=${#PROMPT}
[ "$LEN" -lt "$THRESHOLD_CHARS" ] && exit 0

# 4. カウント更新
COUNT_FILE="$DIR/count"
count=$(cat "$COUNT_FILE" 2>/dev/null || echo 0)
count=$((count + 1))
printf '%s\n' "$count" > "$COUNT_FILE"

# 5. 閾値到達で 1 度だけ提案
if [ "$count" -ge "$THRESHOLD_COUNT" ]; then
  touch "$DIR/suggested"
  jq -nc --arg msg "💡 内容のある指示が ${count} 回続いています。/rename でセッションに名前を付けておくと、後で見返しやすくなります。" \
    '{systemMessage: $msg}'
fi
