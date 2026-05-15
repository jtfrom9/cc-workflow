---
description: これまでの議論を要約して checkpoint task として明示的に保存する
argument-hint: [短いスラグ名]
allowed-tools: Bash, Read, Write
---

これまでの会話を **詳細に**（甘くまとめずに）拾って、jtfrom9-cc-workflow の **checkpoint task** として保存してください。
ユーザの引数 `$ARGUMENTS` がある場合は taskId のスラグ部分にも反映する（省略時は "checkpoint"）。

## 実装手順

### 1. task ディレクトリを初期化

以下を Bash で実行し、出力 (key=value 形式) をパースして次のキーを取得する:

- `taskId`
- `task_dir`
- `plan_path`
- `task_md_path`
- `project`
- `project_root`
- `created_at`
- `session_id`
- `prev_checkpoint_taskid`  (このセッション内で直前に保存した checkpoint がある場合のみ非空)
- `prev_checkpoint_plan`
- `prev_checkpoint_created`

```sh
python3 "${CLAUDE_PLUGIN_ROOT}/python/init_checkpoint.py" "$ARGUMENTS"
```

### 2. 前回チェックポイント以降を特定する

`prev_checkpoint_plan` が空でなければ、Read ツールでその plan.md を読み、**何が既に記録済みか** を把握する。
`prev_checkpoint_plan` が空の場合は、セッションの最初から現時点までが対象。

### 3. plan.md を書く（**甘くまとめないこと**）

Write ツールで `plan_path` に書き込む。冒頭に `# <タスクのタイトル>` を入れる。
対象範囲は **前回 checkpoint 以降から現時点まで**（前回が無ければセッション全体）。

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

### 4. task.md を書く

Write ツールで `task_md_path` に書き込む。`<...>` は手順 1 で取得した値で埋める。`prev_checkpoint_taskid` が空でない場合は frontmatter にも書く。

```markdown
---
taskId: "<taskId>"
created_at: "<created_at>"
project: "<project>"
project_root: "<project_root>"
session_id: "<session_id>"
source: checkpoint
status: pending
prev_checkpoint_taskid: "<prev_checkpoint_taskid>"   # ← 前回 checkpoint がある場合のみ
---

# <taskId>

`/jtfrom9-cc-workflow:checkpoint` で明示的に保存された会話のスナップショット。
`<prev_checkpoint_created>` 以降〜現時点までの作業内容を plan.md に記録した。
```

`prev_checkpoint_taskid` が空のときは frontmatter の該当行を省く。

### 5. 完了報告

1〜2 行で、taskId と保存先 path、（あれば）前回 checkpoint からの差分範囲をユーザに報告。
