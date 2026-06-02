# ストレージレイアウト

プラグインのランタイム状態はすべてホーム配下の `~/.cc-workflow/` に置かれる。リポジトリ側には書き込まない。

```
~/.cc-workflow/
├── tasks/<project>/<taskId>/   ← 保存済み task の本体（plan.md / task.md / summary.md）
│   └── .last_index             ← プロジェクト内 index カウンタ（隠しファイル）
├── state/<session-id>/         ← セッション毎の sentinel
│   ├── cwd                     ← セッション起動時の cwd（SessionStart で記録）
│   ├── open_task_id            ← 現在「開いている」taskId
│   └── last_checkpoint_taskid  ← 直近の手動 checkpoint taskId（インクリメンタル用）
└── log/                        ← 任意のデバッグログ置き場（現状未使用）
```

`~/.cc-workflow/` 配下は実行時に自動で作成される。`state/` はセッション状態なので次の起動で再作成されるが、`tasks/` は保存済み task の本体なので、削除するとその履歴は復元できない。

MSYS2 で起動した場合も、シェルと Python の両方で起動シェルの `$HOME` を基準にする。Windows Python の `Path.home()` と MSYS2 の `$HOME` が異なる環境でも保存先は分岐しない。

## project の決定

`<project>` 部分は **Claude Code を起動した cwd のベース名** で決まる。git は参照しない。

- `SessionStart` フック (`hooks/session-start.sh`) が `pwd` を `state/<sid>/cwd` に記録する
- `UserPromptSubmit` フック (`hooks/touch-session.sh`) が `state/<sid>/` の更新日時を進め、slash command が現在のセッションを識別できるようにする
- 以降のフック・コマンドはその `cwd` を `project_root` として固定する
- セッション中に Claude Code の cwd がサブディレクトリにシフトしても、project 名は変わらない

たとえば `~/work/foo/` で起動したセッションのタスクはすべて `tasks/foo/` 配下に積まれる。同じ親リポでも `~/work/foo/sub-a/` で起動した場合は `tasks/sub-a/` という別 project として独立する。

## taskId の形式

タスクディレクトリ名は **full taskId** で、以下の構造を持つ:

```
<index>-<yymmdd>-<name>
└── shortId ──┘
└────── full taskId ──────┘
```

| 部分 | 例 | 説明 |
|---|---|---|
| `<index>` | `0042` | プロジェクト内のローカル通し番号。4 桁 0 埋め |
| `<yymmdd>` | `260516` | 採取日（ローカルタイム） |
| `<name>` | `pure-pondering-crystal` | プラン本文の H1 から抽出した slug、または Claude が決めたタイトル、または `auto-HHMMSS`（自動 checkpoint の場合） |

### full / short

| 呼び方 | 範囲 | 例 |
|---|---|---|
| **full taskId** | 上記 3 部品すべて。ディレクトリ名そのもの | `0042-260516-pure-pondering-crystal` |
| **shortId** | `<index>-<yymmdd>` の 11 文字固定 prefix | `0042-260516` |

shortId は `<index>` が同プロジェクト内で一意に振られるため、shortId だけで一意にタスクを特定できる。`/cc-workflow:tasks` は表に `shortId` と `name` を別列で表示し、`/cc-workflow:restore` は full / short どちらでも引数として受け取れる（shortId のときは `tools/resolve-taskid.py` がプロジェクト配下を glob して full に変換する）。

`<name>` は UTF-8 セーフに slug 化されるので、日本語タイトルも `ユーザ認証機能の追加` のようにそのまま入る。`/` `\` `:` `*` `?` `"` `<>` `|` などパス禁則文字と ASCII 空白は `-` に置換される。

## index の採番

プロジェクト直下に隠しファイル `.last_index` を置き、「これまでに使った最大 index」を記録する。新しい index は:

```
next_index = max(.last_index の値, 既存フォルダ名から抽出した最大番号) + 1
```

これにより:

- フォルダを個別に削除しても、削除した番号が再利用されない（最大番号の削除を含む）
- 万一 `.last_index` を失っても、「既存フォルダの最大値 + 1」にフォールバックする
- フォルダ・カウンタの両方が消えれば 0001 から再開する

## 「現在開いている task」

`state/<sid>/open_task_id` に taskId を 1 行で記録している。更新タイミング:

- `/cc-workflow:restore <taskId>` 実行時
- `/cc-workflow:checkpoint` で新 task を作った時
- `ExitPlanMode` のプラン承認で task になった時

`/cc-workflow:summarise` はこのファイルを読んで再要約対象を決める。

## 状態のクリーンアップ

タスク本体 (`tasks/`) は履歴として残し続ける想定。`state/` のセッション ID ディレクトリだけは時間経過で増えていくので、必要なら以下のような操作で古いものを掃除する:

```sh
# 30 日以上前の state/<sid>/ を消す
find ~/.cc-workflow/state -mindepth 1 -maxdepth 1 -type d -mtime +30 -exec rm -rf {} +
```

`tasks/` 配下を消すか残すかは判断次第。手動 checkpoint や `/cc-workflow:summarise` 実行後の自動 checkpoint には詳細な作業記録や会話抜粋が入ることがあるため、長期保存する場合は内容を確認しておく。
