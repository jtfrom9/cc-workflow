# cc-workflow

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Claude Code](https://img.shields.io/badge/Claude%20Code-Plugin-D97757)](https://claude.com/code)

セッション管理を意識しない独自ワークフローを実現するための、Claude Code の設定プラグイン。対話の自動保存、理解負債やコンテキストスイッチの認知負荷を下げる要約の自動生成、対話履歴の管理を行う。

## 動作要件

- [Claude Code](https://claude.com/code) CLI
- Python 3.9 以上（標準ライブラリのみ）
- bash + [`jq`](https://jqlang.org/)
- Windows で使う場合は Git for Windows（bash 提供）と Python 3 の両方が必要

## 使い方

### このセッションだけで試す

```sh
git clone https://github.com/<owner>/cc-workflow.git <plugin-root>
claude --plugin-dir <plugin-root>
```

### マーケットプレース経由で永続インストール

```sh
claude plugin marketplace add <plugin-root>
claude plugin install cc-workflow
```

（`.claude-plugin/marketplace.json` を別途用意した上で）

## 機能

### 自動 checkpoint

Claude の応答が終わるたびに、それまでの会話を新しい task として `~/.cc-workflow/tasks/<project>/<taskId>/` に保存する。`Stop` フックでセッショントランスクリプトのトークン消費を見て、前回採取時より閾値（既定 30%）以上トークンが増えていれば発火する。

保存されるファイル（詳細は [`docs/saved-files.md`](docs/saved-files.md) 参照）:

- `task.md`: frontmatter にトリガ情報・前回タスク参照・トークン数
- `plan.md`: 採取時のメタ情報のみ。会話本文は転記しない
- `summary.md`: 長ければ生成。後から `/cc-workflow:summarise` で再生成も可

| 環境変数 | デフォルト | 意味 |
|---|---|---|
| `CC_WORKFLOW_AUTO_CHECKPOINT` | `1` | `0` で自動採取を無効化 |
| `CC_WORKFLOW_CHECKPOINT_PCT` | `30` | 採取の閾値パーセント |
| `CC_WORKFLOW_MAX_CONTEXT_TOKENS` | `200000` | 別セッション判定の母数。Opus 1M variant 利用時は `1000000` に |

### プランファイルの保管場所変更と自動要約

プランモードで承認されたプランは、通常 Claude Code が `~/.claude/plans/` にフラットに書き出す。`PostToolUse(ExitPlanMode)` フックでこれを `~/.cc-workflow/tasks/<project>/<taskId>/` に移し替える。デフォルトでは承認後に一旦ターン停止し、ユーザにプラン確認の猶予を作る。

保存されるファイル（詳細は [`docs/saved-files.md`](docs/saved-files.md) 参照）:

- `task.md`: メタ情報（`source: plan`）
- `plan.md`: 承認されたプラン本体（`~/.claude/plans/` から移動）
- `summary.md`: `plan.md` が閾値行数を超えていれば `claude -p` で非同期生成

| 環境変数 | デフォルト | 意味 |
|---|---|---|
| `CC_WORKFLOW_PAUSE_AFTER_PLAN` | `1` | `0` で「承認後にターン停止」を無効化 |
| `CC_WORKFLOW_SUMMARY_THRESHOLD_LINES` | `50` | `plan.md` がこれより長ければ `summary.md` を生成 |
| `CC_WORKFLOW_SOURCE_PLANS` | `~/.claude/plans` | 移動元。Claude Code の `plansDirectory` を変更している場合に合わせる |
| `CC_WORKFLOW_CLAUDE_CMD` | `claude` | summary 生成で叩く `claude` バイナリの上書き |

### CLAUDE.md の注入

`SessionStart` フックでプラグイン同梱の [`CLAUDE.md`](CLAUDE.md)（対話ルール、コメント言語、ブランチ確認、TDD 等）を `additionalContext` として注入する。Claude Code 仕様上、プラグインルートの `CLAUDE.md` は自動ロードされないので、フックで自前で流し込む方式。

### カスタムコマンド

#### `/cc-workflow:checkpoint`

これまでの会話を詳細に拾って checkpoint task として明示的に保存する。前回 checkpoint 以降の差分を対象にするインクリメンタル方式。タイトルは Claude が会話内容に合わせて自分で決めるので、ユーザは引数を渡さない。

#### `/cc-workflow:summarise`

引数なしで、現在開いている task の `summary.md` を再生成する。最大 3 項目の箇条書きに整形される。自動 checkpoint の task に対しては JSONL から会話履歴を抜き出して `plan.md` を会話入りに書き換えてから要約する。

#### `/cc-workflow:restore <taskId>`

指定 taskId の `task.md` / `plan.md` / `summary.md` をコンテキストに展開し、続きから作業を再開する。`restore` した task が「開いている task」として記録され、その後の `/summarise` の対象になる。

#### `/cc-workflow:tasks`

現在のプロジェクトの task 一覧（taskId、作成日時、`source`、`status`）を Markdown テーブルで表示する。

### ステータスライン

ステータスラインに使用量を表示するなどの修飾を加える。

## ドキュメント

- [ストレージレイアウト](docs/storage-layout.md) — `~/.cc-workflow/` 配下のディレクトリ構造、`taskId` の形式、index 採番ルール
- [保存ファイルの中身](docs/saved-files.md) — `plan.md` / `task.md` / `summary.md` の構造、各起動経路での書き分け

## License

[MIT](LICENSE)
