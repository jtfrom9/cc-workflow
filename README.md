# cc-workflow

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Claude Code](https://img.shields.io/badge/Claude%20Code-Plugin-D97757)](https://claude.com/code)

Claude Code の作業を支援する設定プラグイン。同梱 `CLAUDE.md` のセッション注入、自動レビュー・自動開発ループ、直近セッションの日報、コンテキスト窓とレート制限を表示するステータスラインを提供する。

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

### CLAUDE.md の注入

`SessionStart` フックでプラグイン同梱の [`CLAUDE.md`](CLAUDE.md) を `additionalContext` として注入する。質問への回答順、指摘への対応、コメント言語、ブランチ確認、TDD などの作業ルールが毎セッション適用される。

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
コンテキスト窓の使用量・推定コスト・**レート制限ウィンドウの残量** を1行で表示する。

```
📁 cc-workflow · 🧠 ██████░░░░ 562k/1M (56%) · claude-opus-5-5 · 💰$1.23 · 🟢 85% 2h21m · 7d 96%
└ フォルダ ┘   └─ コンテキスト窓使用量 ──────────────────┘   └ 推定コスト ┘ └ 5時間窓の残量＋リセット ┘ └ 7日 ┘
```

```json
{
  "statusLine": {
    "type": "command",
    "command": "python3 /<plugin-root>/tools/status_line.py"
  }
}
```

表示内容はすべて Claude Code が stdin に渡す JSON（[公式 docs](https://code.claude.com/docs/en/statusline)）
から描画し、transcript の解析やネットワークアクセスは行わない。

- 🧠: `context_window`（`used_percentage` / `context_window_size`）。初回応答前と `/compact` 直後は `—`
- 💰: `cost.total_cost_usd`。Claude Code がクライアント側で定価から見積もった値で、実請求額ではない
- 🟢/🟡/🟠/🔴: `rate_limits.five_hour` / `seven_day` の残量。Pro/Max サブスクリプションのみ表示

## 保存されるデータ

このプラグインは `~/.cc-workflow/` にランタイム状態を保存する。`auto-review-loop` の run 状態（`reviews/`）、セッション毎の sentinel（`state/`）が対象。詳細は [ストレージレイアウト](docs/storage-layout.md) を参照。

## ドキュメント

- [ストレージレイアウト](docs/storage-layout.md) — `~/.cc-workflow/` 配下のディレクトリ構造、project の決定方法、状態のクリーンアップ

## License

[MIT](LICENSE)
