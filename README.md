# jtfrom9-cc-workflow

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.9%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Claude Code](https://img.shields.io/badge/Claude%20Code-Plugin-D97757)](https://claude.com/code)

Claude Code 用のプラグイン。会話の自動 checkpoint、`ExitPlanMode` プランのタスク化、`/restore`・`/summarise` などのスラッシュコマンド、`CLAUDE.md` のセッション注入を 1 つにまとめている。

## 動作要件

- [Claude Code](https://claude.com/code) CLI
- Python 3.9 以上（標準ライブラリのみ）
- bash + [`jq`](https://jqlang.org/)
- Windows で使う場合は Git for Windows（bash 提供）と Python 3 の両方が必要

## 使い方

### このセッションだけで試す

```sh
git clone https://github.com/<owner>/jtfrom9-cc-workflow.git ~/src/jtfrom9-cc-workflow
claude --plugin-dir ~/src/jtfrom9-cc-workflow
```

### マーケットプレース経由で永続インストール

```sh
claude plugin marketplace add ~/src/jtfrom9-cc-workflow
claude plugin install jtfrom9-cc-workflow
```

（`.claude-plugin/marketplace.json` を別途用意した上で）

### ステータスライン

`tools/status_line.py` を `statusLine` に登録すると、現在のコンテキスト使用量がバーで表示される。`~/.claude/settings.json`（または `--settings` で読ませる任意の JSON）に追加:

```json
{
  "statusLine": {
    "type": "command",
    "command": "python3 /<absolute path>/jtfrom9-cc-workflow/tools/status_line.py"
  }
}
```

## 機能

### 自動 checkpoint

`Stop` フックで Claude の応答が終わるたびに、現在のコンテキスト使用量を確認する。前回採取時より閾値（既定 30%）以上トークンが増えていれば、新しい task として `~/.jtfrom9-cc-workflow/tasks/<project>/<taskId>/` に自動採取する（メタ情報のみ、会話本文は転記せずトランスクリプトを参照する設計）。判定は LLM を介さない決定論的なロジック。

実体: [`tools/checkpoint.py`](tools/checkpoint.py) を `--auto` で起動。閾値・最大コンテキストは `JTFROM9_CC_WORKFLOW_CHECKPOINT_PCT` / `JTFROM9_CC_WORKFLOW_MAX_CONTEXT_TOKENS` で調整。

### プランファイルの task 化

プランモードで承認された `ExitPlanMode` の plan は、本来 `~/.claude/plans/` 配下にフラットに溜まっていく。`PostToolUse` フックでこれを `~/.jtfrom9-cc-workflow/tasks/<project>/<taskId>/plan.md` に移動し、`task.md` と必要なら `summary.md` を生成する。デフォルトでは「承認後に一旦ターン停止」してユーザがプランを確認できる猶予を作る（`JTFROM9_CC_WORKFLOW_PAUSE_AFTER_PLAN=0` で無効化可）。

実体: [`tools/relocate_plan.py`](tools/relocate_plan.py)

### `/jtfrom9-cc-workflow:checkpoint`

これまでの会話を **詳細に**（甘くまとめずに）拾って、checkpoint task として明示的に保存する。前回 checkpoint 以降の差分を対象にするインクリメンタル方式。タイトルは Claude が会話内容に合わせて自分で決めるので、ユーザは引数を渡さない。

### `/jtfrom9-cc-workflow:summarise`

引数なしで、現在開いている task の `summary.md` を再生成する。最大 3 項目の箇条書きに整形される。自動 checkpoint の task に対しては JSONL から会話履歴を抜き出して `plan.md` を会話入りに書き換えてから要約する。

### `/jtfrom9-cc-workflow:restore <taskId>`

指定 taskId の `task.md` / `plan.md` / `summary.md` をコンテキストに展開し、続きから作業を再開する。`restore` した task が「開いている task」として記録され、その後の `/summarise` の対象になる。

### `/jtfrom9-cc-workflow:tasks`

現在のプロジェクトの task 一覧（taskId、作成日時、`source`、`status`）を Markdown テーブルで表示する。

### CLAUDE.md の注入

`SessionStart` フックでプラグイン同梱の [`CLAUDE.md`](CLAUDE.md)（対話ルール、コメント言語、ブランチ確認、TDD 等）を `additionalContext` として注入する。Claude Code 仕様上、プラグインルートの `CLAUDE.md` は自動ロードされないので、フックで自前で流し込む方式。

### 起動時 cwd の固定

`SessionStart` フックが `pwd` を `~/.jtfrom9-cc-workflow/state/<sid>/cwd` に記録する。後段のフック・コマンドはこれを優先して `project_root` を決めるので、セッション中に Claude Code の cwd がサブディレクトリにシフトしても、task の保存先 project は化けない。

### 状態のクリーンアップ

`tasks/<project>/` の各 task はそのまま履歴として残し続ける想定。`state/<sid>/` のセッション sentinel は時間経過で増えるので、必要に応じて掃除する:

```sh
find ~/.jtfrom9-cc-workflow/state -mindepth 1 -maxdepth 1 -type d -mtime +30 -exec rm -rf {} +
```

## ドキュメント

- [ストレージレイアウト](docs/storage-layout.md) — `~/.jtfrom9-cc-workflow/` 配下のディレクトリ構造、`taskId` の形式、index 採番ルール
- [保存ファイルの中身](docs/saved-files.md) — `plan.md` / `task.md` / `summary.md` の構造、各起動経路での書き分け

## License

[MIT](LICENSE)
