# ストレージレイアウト

プラグインのランタイム状態はすべてホーム配下の `~/.cc-workflow/` に置かれる。リポジトリ側には書き込まない。

```
~/.cc-workflow/
├── reviews/<project>/<run-id>/ ← auto-review-loop の run 状態
│   ├── state.json              ← ラウンド・reviewer×perspective・指摘・解消状況
│   └── round-<n>/              ← 各ラウンドのレビュー全文（<reviewer>-<perspective>.md）
├── cache/                      ← グローバルキャッシュ（セッション非依存）
│   └── oauth-usage.json        ← OAuth usage API のレスポンス（ステータスライン用・TTL付き）
├── state/<session-id>/         ← セッション毎の sentinel
│   ├── cwd                     ← セッション起動時の cwd（SessionStart で記録）
│   └── open_review_run         ← 現在「開いている」auto-review-loop の run-id
└── log/                        ← 任意のデバッグログ置き場（現状未使用）
```

## auto-review-loop の run 状態

`auto-review-loop` スキルは run ごとに `reviews/<project>/<run-id>/` を作る。`<run-id>` は
`<yymmdd>-<HHMMSS>-<title-slug>`。`state.json` にラウンド数・選択した reviewer×perspective・
各ラウンドで指摘を出した組（次ラウンドの絞り込み用）・トリアージ結果・解消状況が入り、
レビュー全文は `round-<n>/<reviewer>-<perspective>.md` に保存される。作業コンテキストには
要約だけを載せ、全文はこのファイル群を参照する。現在進行中の run は
`state/<sid>/open_review_run` が指す。run の `<project>` 解決は起動時 cwd のベース名。

`~/.cc-workflow/` 配下は実行時に自動で作成される。`state/` はセッション状態なので次の起動で再作成される。

MSYS2 で起動した場合も、シェルと Python の両方で起動シェルの `$HOME` を基準にする。Windows Python の `Path.home()` と MSYS2 の `$HOME` が異なる環境でも保存先は分岐しない。

## project の決定

`<project>` 部分は **Claude Code を起動した cwd のベース名** で決まる。git は参照しない。

- `SessionStart` フック (`hooks/session-start.sh`) が `pwd` を `state/<sid>/cwd` に記録する
- `UserPromptSubmit` フック (`hooks/touch-session.sh`) が `state/<sid>/` の更新日時を進め、後段のスクリプトが現在のセッションを識別できるようにする
- 以降のフック・コマンドはその `cwd` を `project_root` として固定する
- セッション中に Claude Code の cwd がサブディレクトリにシフトしても、project 名は変わらない

たとえば `~/work/foo/` で起動したセッションの run はすべて `reviews/foo/` 配下に積まれる。同じ親リポでも `~/work/foo/sub-a/` で起動した場合は `reviews/sub-a/` という別 project として独立する。

## 状態のクリーンアップ

`state/` のセッション ID ディレクトリは時間経過で増えていくので、必要なら以下のような操作で古いものを掃除する:

```sh
# 30 日以上前の state/<sid>/ を消す
find ~/.cc-workflow/state -mindepth 1 -maxdepth 1 -type d -mtime +30 -exec rm -rf {} +
```
