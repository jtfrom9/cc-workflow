---
description: これまでの議論を要約して checkpoint task として明示的に保存する（インクリメンタル）
allowed-tools: Bash, Read, Write
---

これまでの会話を **詳細に**（甘くまとめずに）拾って、jtfrom9-cc-workflow の **checkpoint task** として保存してください。
ユーザは追加の引数を渡さない。タイトル（taskId のスラグ部分）は **これから保存する内容に合わせて Claude が自分で決める**。

## 実装手順

### 1. このチェックポイントの「タイトル」を決める

これから保存する内容を反映する **短い日本語タイトル** (10〜30 字程度) をまず決める。
このタイトルが taskId のスラグ部分（`<index>-<yymmdd>-<TITLE>`）になり、後から `/tasks` で一覧した時に内容が一目で分かるものにする。

例: 「プラグインの Python 移行」「summarise コマンド設計」「自動 checkpoint の閾値判定実装」

### 2. task ディレクトリを初期化

Bash ツールで以下を実行し、出力 (key=value 形式) をパースして次のキーを取得する:

- `taskId`
- `task_dir`
- `plan_path`
- `task_md_path`
- `project`
- `project_root`
- `created_at`
- `session_id`
- `prev_taskid`  (このプロジェクトで一つ前のタスクがある場合のみ非空。auto/manual を問わず最大 index のもの)
- `prev_plan_path`
- `prev_created`
- `current_tokens`
- `prev_tokens`

```sh
python3 "${CLAUDE_PLUGIN_ROOT}/tools/checkpoint.py" "<手順 1 で決めたタイトル>"
```

このコマンドが既に **plan.md と task.md の雛形** をその task ディレクトリに書き込んでいる（メタ情報のみ）。次の手順で plan.md を中身入りで上書きする。

### 3. 前回タスク以降を特定する

`prev_plan_path` が空でなければ、Read ツールでその plan.md を読み、**何が既に記録済みか** を把握する。
`prev_plan_path` が空の場合は、セッションの最初から現時点までが対象。

### 4. plan.md を書く（**甘くまとめないこと**）

Write ツールで `plan_path` を上書きする。冒頭に `# <手順 1 で決めたタイトル>` を入れる。
対象範囲は **前回タスク以降から現時点までの差分**（前回が無ければセッション全体）。

**「詳細に拾う」とは具体的に**:

- **採用した方針・決定事項**を全部書き出す。却下した案も「なぜダメだったか」を含めて残す
- **触ったファイル**を漏らさず列挙（追加・変更・削除）
- **コミット**があれば SHA + メッセージを書く
- **走らせたコマンド** で結果が重要なもの（テスト、validate、bash の出力）を記録
- **未解決の課題・次に着手すべきこと** を箇条書きで残す
- **議論の中で出てきたトレードオフ・制約・参考情報** を文脈ごと残す
- **失敗・やり直し**も書く（同じことを後で繰り返さないため）
- **関連する taskId** があれば相互リンクとして書く

要約ではなく「後でこの plan.md だけ読めば作業を完全に再開できる」レベルの情報量を保つこと。短くしようと頑張らない。長くなって良い。

### 5. summary.md の生成判定（plan.md が長い場合のみ）

Bash で以下を実行する。`plan.md` が閾値（`JTFROM9_CC_WORKFLOW_SUMMARY_THRESHOLD_LINES`、デフォルト 50 行）を超えていれば、ヘルパが裏で `claude -p` を呼んで `summary.md` を生成する。短ければ何も起きない。

```sh
python3 "${CLAUDE_PLUGIN_ROOT}/tools/maybe_spawn_summary.py" "<plan_path>"
```

### 6. 完了報告

1〜2 行で、taskId と保存先 path、前回タスクからの差分範囲、summary 生成中かどうかをユーザに報告。
