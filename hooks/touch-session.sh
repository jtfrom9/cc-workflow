#!/bin/bash
# Keep the current Claude Code session identifiable for slash commands.

set -uo pipefail

DATA_DIR="${CC_WORKFLOW_DIR:-$HOME/.cc-workflow}"
INPUT=$(cat 2>/dev/null || true)
SID=$(printf '%s' "$INPUT" | jq -r '.session_id // empty' 2>/dev/null || true)

if [ -n "$SID" ]; then
  mkdir -p "$DATA_DIR/state/$SID"
  touch "$DATA_DIR/state/$SID"
fi
