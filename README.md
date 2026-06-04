# cc-workflow

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Claude Code](https://img.shields.io/badge/Claude%20Code-Plugin-D97757)](https://claude.com/code)

Claude Code の作業セッションを task として記録し、あとから復元・要約しやすくする設定プラグイン。承認済みプランの整理、自動 checkpoint、会話履歴を使った要約、同梱 `CLAUDE.md` のセッション注入を行う。

## 動作要件

- [Claude Code](https://claude.com/code) CLI
- Python 3.9 以上（標準ライブラリのみ）
- bash + [`jq`](https://jqlang.org/)
- Windows で使う場合は Git for Windows（bash 提供）と Python 3 の両方が必要

## 使い方

### このセッションだけで試す

```sh
git clone https://github.com/jtfrom9/cc-workflow.git <plugin-root>
claude --plugin-dir <plugin-root>
```

### 永続インストール

`.claude-plugin/marketplace.json` を用意した上で、このリポジトリをローカル marketplace として登録する。

```sh
claude plugin marketplace add <plugin-root>
claude plugin install cc-workflow
```

## 機能

### 自動 checkpoint

Claude の応答が終わるたびに、それまでの会話を参照できる checkpoint task を `~/.cc-workflow/tasks/<project>/<taskId>/` に作成する。`Stop` フックでセッショントランスクリプトのトークン消費を見て、同プロジェクトの直前 task より閾値（既定 30%）以上トークンが増えていれば発火する。

保存されるファイル（詳細は [`docs/saved-files.md`](docs/saved-files.md) 参照）:

- `task.md`: frontmatter にトリガ情報・前回タスク参照・トークン数
- `plan.md`: 採取時のメタ情報のみ。会話本文は転記しない
- `summary.md`: `plan.md` が閾値行数を超えていれば生成。自動 checkpoint は `plan.md` がメタ情報だけで通常は閾値未満なので作られないが、その判定は他の経路と同じ size ベースの統一ルール。長い `plan.md` が欲しい場合は後から `/cc-workflow:summarise` で会話履歴を抜き出して再生成できる

| 環境変数 | デフォルト | 意味 |
|---|---|---|
| `CC_WORKFLOW_AUTO_CHECKPOINT` | `1` | `0` で自動採取を無効化 |
| `CC_WORKFLOW_CHECKPOINT_PCT` | `30` | 採取の閾値パーセント |
| `CC_WORKFLOW_MAX_CONTEXT_TOKENS` | `200000` | 別セッション判定の母数。Opus 1M variant 利用時は `1000000` に |

### プランファイルの保管場所変更と自動要約

プランモードで承認されたプランは、通常 Claude Code が `~/.claude/plans/` にフラットに書き出す。`PostToolUse(ExitPlanMode)` フックでこれを `~/.cc-workflow/tasks/<project>/<taskId>/` に移し替える。デフォルトでは承認後すぐに実装へ進まず、いったん応答を止める。

保存されるファイル（詳細は [`docs/saved-files.md`](docs/saved-files.md) 参照）:

- `task.md`: メタ情報（`source: plan`）
- `plan.md`: 承認されたプラン本体（`~/.claude/plans/` から移動）
- `summary.md`: `plan.md` が閾値行数を超えていれば `claude -p` で非同期生成

| 環境変数 | デフォルト | 意味 |
|---|---|---|
| `CC_WORKFLOW_PAUSE_AFTER_PLAN` | `1` | `0` で「承認後にターン停止」を無効化 |
| `CC_WORKFLOW_SUMMARY_THRESHOLD_LINES` | `50` | `plan.md` がこれより長ければ `summary.md` を生成 |
| `CC_WORKFLOW_SOURCE_PLANS` | `~/.claude/plans` | 移動元。Claude Code の `plansDirectory` を変更している場合に合わせる |
| `CC_WORKFLOW_CLAUDE_CMD` | `claude` | summary 生成で実行する `claude` バイナリの上書き |

### CLAUDE.md の注入

`SessionStart` フックでプラグイン同梱の [`CLAUDE.md`](CLAUDE.md) を `additionalContext` として注入する。質問への回答順、指摘への対応、コメント言語、ブランチ確認、TDD などの作業ルールが毎セッション適用される。

### カスタムコマンド

#### `/cc-workflow:checkpoint`

これまでの会話を詳細に拾って checkpoint task として明示的に保存する。同プロジェクトの直前 task 以降の差分を対象にするインクリメンタル方式。タイトルは Claude が会話内容に合わせて自分で決めるので、ユーザは引数を渡さない。

#### `/cc-workflow:summarise`

引数なしで、現在開いている task の `summary.md` を再生成する。最大 3 項目の箇条書きに整形される。自動 checkpoint の task に対しては JSONL から会話履歴を抜き出して `plan.md` を会話入りに書き換えてから要約する。

#### `/cc-workflow:restore <taskId>`

指定 taskId の `task.md` / `plan.md` / `summary.md` をコンテキストに展開し、続きから作業を再開する。引数には **full taskId**（`0001-260516-プラン設計`）でも **shortId**（`0001-260516`）でも渡せる。shortId のときは同プロジェクト内で一意にマッチしたディレクトリに解決する。`restore` した task が「開いている task」として記録され、その後の `/summarise` の対象になる。

#### `/cc-workflow:tasks`

現在のプロジェクトの task 一覧を Markdown テーブルで表示する。列は `shortId` / `name` / `created` / `source` / `status`。`shortId` を `/cc-workflow:restore` の引数にそのまま渡せる。

### 自動レビュー・修正ループ（`auto-review-loop` スキル）

ユーザが **実装指示文中にキーワード「自動レビューで」/「auto review」を明示** したときだけ
起動するモデル起動スキル。通常の「実装して」では起動しない。TDD で実装し、選択された
レビュアー×観点でレビューし、Claude のトリアージを挟んで有限回だけ修正ループを回す。

- 起動時に **2問**（誰にレビューさせるか／どの観点で見るか、ともに複数選択可）を問いかける。
  既定は単一の Claude サブエージェント。Codex を選んだ場合は導入・ログインを確認し、
  未導入なら黙ってスキップせず別レビュアーを選ばせる。
- レビュアーは共通インターフェース（入力＝変更＋観点、出力＝指摘リスト）の背後にあり、
  ループ制御を変えずに追加できる（[`skills/auto-review-loop/reviewers.md`](skills/auto-review-loop/reviewers.md)）。
- 全レビュー結果が出揃ってから Claude が **自動でトリアージ**（修正可否はユーザに問わない）。
  偽陽性は理由付きで退け、妥当な must-fix のみ TDD で修正する。
- 「修正 → 再レビュー」の往復は **最大2回**。再レビューは前ラウンドで指摘を出した
  レビュアー×観点のみに絞る。3回目相当でなお must-fix が残れば打ち切り、未解決を要約して
  ユーザへ差し戻す。
- run 状態は `~/.cc-workflow/reviews/<project>/<run-id>/`（`state.json` ＋ ラウンド毎の
  レビュー全文）に保存し、リポジトリは汚さない。詳細は
  [ストレージレイアウト](docs/storage-layout.md) を参照。

Codex をレビュアーに使う場合は Codex CLI のインストールとログインが必要。

### ステータスライン

`tools/status_line.py` を `~/.claude/settings.json` の `statusLine` に設定すると、
コンテキスト窓の使用量と **レート制限ウィンドウの残量** を1行で表示する。

```
📁 cc-workflow · 🧠 ██████░░░░ 562k/1M (56%) · claude-opus-4-8 · 🟢 85% 2h21m · 7d 96%
└ フォルダ ┘   └─ コンテキスト窓使用量 ──────────────────┘   └ 5時間窓の残量＋リセット ┘ └ 7日 ┘
```

```json
{
  "statusLine": {
    "type": "command",
    "command": "python3 /<plugin-root>/tools/status_line.py"
  }
}
```

セッション残量は **ccusage を使わず**、Anthropic の OAuth usage エンドポイント
（`/api/oauth/usage`）から 5時間／7日ウィンドウの `utilization` と `resets_at` を直接取得する。
アクセストークンの取得は **macOS=Keychain（`Claude Code-credentials`）／ Windows・Linux=
`~/.claude/.credentials.json`** の両対応。ステータスラインはネットワークでブロックしないよう、
キャッシュを即描画し TTL 超過時のみバックグラウンドで更新する（stale-while-revalidate）。
残量に応じて 🟢 / 🟡 / 🟠 / 🔴 を出し分ける。

| 環境変数 | デフォルト | 意味 |
|---|---|---|
| `CC_WORKFLOW_SESSION_USAGE` | `1` | `0` でセッション残量セグメントを無効化（ネットワーク呼び出しなし） |
| `CC_WORKFLOW_USAGE_TTL` | `60` | usage キャッシュの鮮度（秒）。超過でバックグラウンド更新 |
| `CLAUDE_CODE_OAUTH_TOKEN` | （未設定） | トークンの上書き。設定時は Keychain／ファイル探索をスキップ |

## 保存されるデータ

このプラグインは `~/.cc-workflow/` に task 情報を保存する。`plan.md` には承認済みプランや手動 checkpoint の詳細、`/cc-workflow:summarise` 実行後の自動 checkpoint には会話抜粋が入ることがある。保存内容と削除方針は [保存ファイルの中身](docs/saved-files.md) と [ストレージレイアウト](docs/storage-layout.md) を参照。

## ドキュメント

- [ストレージレイアウト](docs/storage-layout.md) — `~/.cc-workflow/` 配下のディレクトリ構造、`taskId` の形式、index 採番ルール
- [保存ファイルの中身](docs/saved-files.md) — `plan.md` / `task.md` / `summary.md` の構造、各起動経路での書き分け

## License

[MIT](LICENSE)
