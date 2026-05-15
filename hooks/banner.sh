#!/bin/bash
# jtfrom9-cc-workflow/hooks/banner.sh
#
# SessionStart フックから呼ばれる:
#  1. プラグインが有効化されていることを起動時に表示
#  2. セッション開始時の cwd を state/<sid>/cwd に記録
#     後段のフック (Stop / PostToolUse 等) はこの記録を優先して project_root
#     を決めるため、セッション中に cwd が変わっても影響を受けない。

set -uo pipefail

DATA_DIR="${JTFROM9_CC_WORKFLOW_DIR:-$HOME/.jtfrom9-cc-workflow}"

INPUT=$(cat 2>/dev/null || true)
SID=$(printf '%s' "$INPUT" | jq -r '.session_id // empty' 2>/dev/null || true)
if [ -n "$SID" ]; then
  mkdir -p "$DATA_DIR/state/$SID"
  pwd > "$DATA_DIR/state/$SID/cwd"
fi

printf '%s' '{"systemMessage":"jtfrom9-cc-workflow"}'
