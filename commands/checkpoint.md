---
description: これまでの議論を要約して checkpoint task として明示的に保存する
argument-hint: [短いスラグ名]
allowed-tools: Bash, Write
---

これまでの会話の内容を要約して、jtfrom9-cc-workflow の **checkpoint task** として保存してください。
ユーザの引数 `$ARGUMENTS` がある場合はそれを taskId のスラグ部分にも反映する（省略可、省略時は "checkpoint"）。

## 実装手順

### 1. task ディレクトリを初期化

以下を Bash で実行し、出力 (key=value 形式) をパースして `taskId`, `task_dir`, `plan_path`, `task_md_path`, `project`, `project_root`, `created_at` を取得する:

```sh
"${CLAUDE_PLUGIN_ROOT}"/scripts/init-checkpoint.sh "$ARGUMENTS"
```

### 2. plan.md を書き込む

これまでの会話全体を **十分な情報量で** 要約し、Write ツールで `plan_path` に書き込む。
要約は後で `/jtfrom9-cc-workflow:restore <taskId>` で読み戻し、別セッションでも文脈を取り戻せる粒度で書くこと。

含めるべき内容:

- **目的・コンテキスト**: 何をやろうとしているか、なぜか
- **採用した方針・決定事項**: 設計選択、却下した案も簡潔に
- **完了した変更**: 編集／追加／削除したファイル、コミットがあればコミットハッシュ
- **未解決の課題・次のステップ**: 続きから何をすればよいか
- **参考になる情報**: 関連する taskId、ファイルパス、議論のキーポイント

形式は Markdown。冒頭に `# <タスクのタイトル>` を入れる（後の機械処理で利用される）。

### 3. task.md を書き込む

Write ツールで `task_md_path` に以下のフォーマットで書き込む。`<...>` は手順 1 で取得した値で埋める:

```markdown
---
taskId: "<taskId>"
created_at: "<created_at>"
project: "<project>"
project_root: "<project_root>"
source: checkpoint
status: pending
---

# <taskId>

`/jtfrom9-cc-workflow:checkpoint` で明示的に保存された会話のスナップショット。
plan.md にこの時点までの議論の要約を残してある。
```

### 4. 完了報告

成功したら 1〜2 行で、保存先 path と taskId をユーザに報告する。
