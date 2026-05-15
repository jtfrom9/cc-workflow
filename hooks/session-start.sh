#!/bin/bash
# cc-workflow/hooks/session-start.sh
#
# SessionStart フックから呼ばれる。やること:
#   1. systemMessage `cc-workflow` を表示 (プラグイン有効化の確認)
#   2. 現在の pwd を state/<sid>/cwd に記録
#      → 後段のフックが「セッション起動時 cwd」を project_root として固定できる
#   3. プラグイン同梱の CLAUDE.md (対話ルール) を読んで additionalContext として注入
#      → プラグイン仕様上、プラグインルートの CLAUDE.md は Claude Code が自動ロード
#        しないため、ここで自前で流し込む
#
# CLAUDE_PLUGIN_ROOT はプラグインが --plugin-dir 等で読み込まれたときに
# Claude Code が自動で渡してくる環境変数。

set -uo pipefail

DATA_DIR="${CC_WORKFLOW_DIR:-$HOME/.cc-workflow}"
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-}"

INPUT=$(cat 2>/dev/null || true)
SID=$(printf '%s' "$INPUT" | jq -r '.session_id // empty' 2>/dev/null || true)
if [ -n "$SID" ]; then
  mkdir -p "$DATA_DIR/state/$SID"
  pwd > "$DATA_DIR/state/$SID/cwd"
fi

# CLAUDE.md を取得 (無ければ空のまま)
ADDITIONAL_CONTEXT=""
if [ -n "$PLUGIN_ROOT" ] && [ -f "$PLUGIN_ROOT/CLAUDE.md" ]; then
  ADDITIONAL_CONTEXT=$(cat "$PLUGIN_ROOT/CLAUDE.md")
fi

jq -nc \
  --arg msg "cc-workflow" \
  --arg ctx "$ADDITIONAL_CONTEXT" \
  '
  if ($ctx | length) > 0 then
    {systemMessage: $msg,
     hookSpecificOutput: {hookEventName: "SessionStart", additionalContext: $ctx}}
  else
    {systemMessage: $msg}
  end
  '
