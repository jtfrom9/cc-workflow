#!/bin/bash
# jtfrom9-cc-workflow/hooks/banner.sh
#
# SessionStart フックから呼ばれる。
# このプラグインが有効化されていることをセッション開始時に表示する。

set -euo pipefail

printf '%s' '{"systemMessage":"jtfrom9-cc-workflow"}'
