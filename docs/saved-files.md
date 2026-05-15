# 保存ファイルの中身

`~/.cc-workflow/tasks/<project>/<taskId>/` の各ファイルが、どの起動経路でどう書かれるかをまとめる。ストレージ全体の構造は [storage-layout.md](storage-layout.md) を参照。

## 起動経路と `source` / `trigger` 区別

`task.md` の frontmatter に `source:` と `trigger:` を埋めて区別する:

| `source` | `trigger` | 経路 |
|---|---|---|
| `plan` | (なし) | プランモードで承認された ExitPlanMode の plan (`tools/relocate_plan.py`) |
| `checkpoint` | `manual` | `/cc-workflow:checkpoint` から手動採取 (`tools/checkpoint.py`) |
| `checkpoint` | `auto` | Stop フックでトークン閾値を超えて自動採取 (`tools/checkpoint.py --auto`) |

`checkpoint` の `manual` / `auto` は **同じスクリプト・同じ task 構造** を持つ。違いは「起動経路」と「plan.md にどこまで内容を書くか」だけ。

## `plan.md`

### 自動 checkpoint (`trigger: auto`)

メタ情報のみで、会話本文は転記しない:

```markdown
# <taskId>

自動 checkpoint。トリガ: <発火理由文>

メタ情報は task.md を、会話本文はセッショントランスクリプト `<transcript path>` を参照してください。
要約が必要なら `/cc-workflow:summarise` を実行。
```

採取時に本文を書き込まないのは、コスト・遅延・サンドボックス制約を避けるため。あとから `/summarise` を叩くと、`tools/regenerate_summary.py` が JSONL から会話履歴を抜き出してこの `plan.md` を上書きする（自動 checkpoint 限定の挙動）。

### 手動 checkpoint (`trigger: manual`)

スクリプトはまず雛形だけ書き込み、その直後に Claude が `/cc-workflow:checkpoint` の slash command 本文に従って **詳細な差分内容で plan.md を上書きする**:

- 採用した方針・却下案（理由つき）
- 触ったファイル（追加・変更・削除）
- コミット SHA + メッセージ
- 走らせたコマンドの結果
- 未解決の課題・次のステップ
- トレードオフ・参考情報
- 失敗・やり直し
- 関連 taskId

「後でこの plan.md だけ読めば作業を完全に再開できる」レベルの情報量を目指す。短くまとめない。

### `source: plan` (ExitPlanMode 由来)

Claude Code が `~/.claude/plans/<slug>.md` に書き出した **承認済みプラン本体** をそのまま `plan.md` として移してくる。中身は Claude が組み立てた実装プラン。

## `task.md`

すべての経路で同じ frontmatter スキーマ。任意の本文をその下に書ける。

```yaml
---
taskId: "<taskId>"
created_at: "<ISO 時刻>"
project: "<project name>"
project_root: "<absolute path>"
session_id: "<sid>"
source: checkpoint            # plan | checkpoint
trigger: auto                 # auto | manual  (source = checkpoint のときのみ)
tokens: 562973                # 採取時点のコンテキスト使用量（auto のときが代表的、manual も埋まる）
prev_task_id: "<前回 taskId>"  # 同プロジェクトの直前 task。最大 index 基準
prev_tokens: 432110
prev_session_id: "<前回 sid>"
trigger_reason: "same session; ... > ..."   # auto trigger 時のみ
status: pending
---

# <taskId>

(本文。プラグインが入れる説明 + ユーザ／Claude の追記用)
```

### 主要フィールドの意味

- `prev_task_id`: **このプロジェクトで最大 index の前 task**。`source` も `trigger` も問わない（直前が auto でも manual でも plan でも、最大 index のものが入る）
- `prev_session_id`: 前 task と同セッションだったかの判定に使う
- `trigger_reason`: 自動 checkpoint が発火した理由を平文で記録（例: `same session; 562973 > 561743 (prev 431841 + 30%)`）
- `status`: `pending` で始まる。実装が完了したらユーザ／Claude が手で `done` 等に書き換える運用

## `summary.md`

`plan.md` が閾値 (`CC_WORKFLOW_SUMMARY_THRESHOLD_LINES`、デフォルト 50 行) を超えたときだけ生成される。生成は `tools/_summarize_worker.py` がバックグラウンドで `claude -p` を呼ぶ非同期処理。

### 成功時

```markdown
# Summary

- <重要度順 1 番目の項目（60〜100 字）>
- <2 番目>
- <3 番目>
```

最大 3 項目の箇条書きで、ぱっと読んで「何をしているか」「何が重要か」が分かる粒度に強制してある。

### 失敗時（診断モード）

`claude -p` がエラーで戻ったり、出力が空だった場合、診断情報が代わりに書き込まれる:

```markdown
# Summary

(要約の自動生成に失敗しました。)

- 例外: `<例外クラス名>`: <メッセージ>
- `claude -p` 終了コード: `<exit code>`
- `claude -p` stderr (先頭 1000 字):

  ```
  <stderr 内容>
  ```

再生成: `/cc-workflow:summarise <taskId>`
```

これが書かれていたら、`claude` バイナリが見えない／ラッパー越しで TTY を要求している／タイムアウト等の原因がここから特定できる。回避策は環境変数 `CC_WORKFLOW_CLAUDE_CMD` で直接の `claude` バイナリパスを指定するか、`false` を渡して要約呼び出し自体を抑制する。

### 短い `plan.md` の場合

`summary.md` は作成されない。3 行で足りる内容ならわざわざ要約する必要が無いため。

## ファイルが増減するタイミング

| 発火条件 | 作られるファイル |
|---|---|
| ExitPlanMode を承認 | `plan.md`（移動）, `task.md` |
| Stop フックでトークン閾値超え | `plan.md`（メタ情報のみ）, `task.md` |
| `/checkpoint` 手動実行 | `plan.md`（Claude が詳細記述）, `task.md` |
| 上記いずれかで `plan.md` が長い | `summary.md` も追加 |
| `/summarise` 実行 | 既存 `summary.md` を上書き（自動 checkpoint の場合は `plan.md` も会話履歴で上書き） |
