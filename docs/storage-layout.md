# ストレージレイアウト

プラグインのランタイム状態はすべてホーム配下の `~/.jtfrom9-cc-workflow/` に置かれる。リポジトリ側には書き込まない。

```
~/.jtfrom9-cc-workflow/
├── tasks/<project>/<taskId>/   ← 保存済み task の本体（plan.md / task.md / summary.md）
│   └── .last_index             ← プロジェクト内 index カウンタ（隠しファイル）
├── state/<session-id>/         ← セッション毎の sentinel
│   ├── cwd                     ← セッション起動時の cwd（SessionStart で記録）
│   ├── open_task_id            ← 現在「開いている」taskId
│   └── last_checkpoint_taskid  ← 直近の手動 checkpoint taskId（インクリメンタル用）
└── log/                        ← 任意のデバッグログ置き場（現状未使用）
```

`~/.jtfrom9-cc-workflow/` 配下は実行時に自動で作成される。途中で消したり書き換えても、必要なものは次の起動で再生成される。

## project の決定

`<project>` 部分は **Claude Code を起動した cwd のベース名** で決まる。git は参照しない。

- `SessionStart` フック (`hooks/session-start.sh`) が `pwd` を `state/<sid>/cwd` に記録する
- 以降のフック・コマンドはその `cwd` を `project_root` として固定する
- セッション中に Claude Code の cwd がサブディレクトリにシフトしても、project 名は化けない

たとえば `~/work/foo/` で起動したセッションのタスクはすべて `tasks/foo/` 配下に積まれる。同じ親リポでも `~/work/foo/sub-a/` で起動した場合は `tasks/sub-a/` という別 project として独立する。

## taskId の形式

```
<index>-<yymmdd>-<original-name>
```

| 部分 | 例 | 説明 |
|---|---|---|
| `<index>` | `0042` | プロジェクト内のローカル通し番号。4 桁 0 埋め |
| `<yymmdd>` | `260516` | 採取日（ローカルタイム） |
| `<original-name>` | `pure-pondering-crystal` | プラン本文の H1 から抽出した slug、または Claude が決めたタイトル、または `auto-HHMMSS`（自動 checkpoint の場合） |

`<original-name>` は UTF-8 セーフに slug 化されるので、日本語タイトルも `ユーザ認証機能の追加` のようにそのまま入る。`/` `\` `:` `*` `?` `"` `<>` `|` などパス禁則文字と ASCII 空白は `-` に潰される。

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

- `/jtfrom9-cc-workflow:restore <taskId>` 実行時
- `/jtfrom9-cc-workflow:checkpoint` で新 task を作った時
- `ExitPlanMode` のプラン承認で task になった時

`/jtfrom9-cc-workflow:summarise` はこのファイルを読んで再要約対象を決める。

## 状態のクリーンアップ

タスク本体 (`tasks/`) は履歴として残し続ける想定。`state/` のセッション ID ディレクトリだけは時間経過で増えていくので、必要なら以下のような操作で古いものを掃除する:

```sh
# 30 日以上前の state/<sid>/ を消す
find ~/.jtfrom9-cc-workflow/state -mindepth 1 -maxdepth 1 -type d -mtime +30 -exec rm -rf {} +
```

`tasks/` 配下を消すか残すかは判断次第。プラン本文 + 採取時のメタ情報がすべて入っているので、長期保存しても 1 件 1 KB 程度に収まる。
