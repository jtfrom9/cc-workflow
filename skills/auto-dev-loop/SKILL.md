---
name: auto-dev-loop
description: >-
  GitHub issue から「いま対応できるもの」を選び出し、worktree 上で並行実装し、
  auto-review-loop でレビューしてから PR を作り、issue/PR コメントを常時監視して
  指示（追加・修正・取りやめ・マージ）に従い続ける**自走開発ループ**。状態は
  `auto-dev-loop` ラベルの**トラッキング issue の description**（進捗テーブル + fenced JSON）で
  管理し、issue を眺めれば進捗が分かる。明確な停止指示が来るまで PR/issue の確認を回し続ける。
  **ユーザの指示文に「自走で」「auto dev」が明示的に含まれているとき、または
  `/cc-workflow:auto-dev-loop` が明示起動されたときだけ**起動する。キーワードを含まない通常の
  「実装して」では起動しない。重量級・長時間・GitHub への副作用（issue/ブランチ/PR/条件付き
  マージ）を伴うため、起動時に必ず方針を確認する。
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, Agent, AskUserQuestion, Skill, ScheduleWakeup, TodoWrite
---

# auto-dev-loop

GitHub issue を起点に **分析 → 計画 → 並行実装（auto-review-loop 込み）→ PR → 監視 → 指示反映**
を、明確な停止指示が来るまで自走で回す。`auto-review-loop` と同じ思想で、**決定的な計算**
（依存ゲート・並行枠、テーブル⇄状態の変換）は `tools/auto_dev_loop.py` に委ね、**判断と GitHub
への副作用**（実現可能性・依存検出・実装・コメントのトリアージ・マージ、`gh` 操作）は自分で行う。

詳細手順は [`references/playbook.md`](references/playbook.md) を参照。

## 状態モデル（重要）

**ローカルにファイル状態は持たない。**唯一の真実は **`auto-dev-loop` ラベルが付いた
トラッキング issue の description**。description には人間向けの**進捗テーブル**と、機械可読な
**fenced JSON**（全状態）が並ぶ。JSON は **HTML コメントで囲って非表示**にしてあり、GitHub の
レンダリングでは見えないが生の body には残る（`load-body` がそこから復元する）。これにより:

- issue を眺めれば進捗が分かる（テーブル）。ターミナルでも remote control でも `gh` で同じものを読める。
- 状態が GitHub 上にあるので、別マシン／別セッションからでも再開できる。

役割分担:
- **メインエージェント（このループの統括）だけ**がトラッキング issue の description を更新する
  （書き手が 1 人なので競合しない）。
- **サブエージェント**（各 issue の実装担当）は、自分が作る **PR と担当作業 issue に詳細な
  状況をコメント**する。トラッキング issue には書かない。

ヘルパは `gh` を呼ばない純粋ツール。1 パスの流れは「issue body を `gh` で取得 → `load-body` で
作業用 JSON に展開 → `upsert/update/...` で更新 → `render` で body を再生成 → `gh issue edit` で
書き戻す」。作業用 JSON は **そのパス限りの一時ファイル**で、永続状態ではない。

---

## 0. トリガ確認

ユーザの**指示文に「自走で」「auto dev」が含まれる**か、`/cc-workflow:auto-dev-loop` が
明示起動されたときだけ起動する。含まれなければ起動しない。規模では判定しない。

## 1. 起動時シングルトンチェック（FR-0）

**最初に必ず**、open な `auto-dev-loop` トラッキング issue があるか確認する:

```sh
gh issue list --label auto-dev-loop --state open --json number,title
```

- **在る** → 既に走っている扱い。**新規作成しない**。その issue の body を取得して状態を読み込み、
  §4 の監視ループに合流して再開する（下記「再開」）。複数 open があるのは異常なので、片方を
  選んで継続し、その旨を報告する。
- **無い** → §2 で新規トラッキング issue を作って開始する。

### 再開

```sh
gh issue view <tracking#> --json body --jq .body > /tmp/adl-body.md
python3 "${CLAUDE_PLUGIN_ROOT}/tools/auto_dev_loop.py" load-body \
  --body-file /tmp/adl-body.md --state /tmp/adl-state.json
```

以降このパスは `/tmp/adl-state.json` を作業用に使い、最後に §3.5 で書き戻す。

## 2. 起動時の確認とトラッキング issue 作成（FR-1）

新規起動時のみ。実装に入る前に `AskUserQuestion` で方針を確定する。文脈から明確なものは推測を
明示して省いてよいが、**ブランチ系は CLAUDE.md の規約上必ず明示する**。

確定項目: ①ベースブランチ / ②マージ先ブランチ（別になり得る）/ ③対象ラベル（一次フィルタ）/
④並行枠（既定 3）/ ⑤自動マージ方針 `off|conditional|green` / ⑥レビュー既定（無人なので
auto-review-loop に渡すプリセット。既定 reviewers=`claude`、perspectives=全観点）。

トラッキング issue を作る（タイトルは `AutoDevLoop: YYYY/MM/DD`、ラベル `auto-dev-loop`）:

```sh
DATE=$(date +%Y/%m/%d)
# gh issue create prints the new issue URL; the trailing path segment is its number.
URL=$(gh issue create --label auto-dev-loop --title "AutoDevLoop: $DATE" --body "(initializing…)")
TN=${URL##*/}
python3 "${CLAUDE_PLUGIN_ROOT}/tools/auto_dev_loop.py" new-state \
  --state /tmp/adl-state.json --base <base> --merge-target <target> \
  --labels <target-labels> --concurrency <N> --auto-merge <off|conditional|green> \
  --reviewers claude --perspectives correctness,requirements,security,performance,conventions,tests \
  --tracking-issue "$TN" --title "AutoDevLoop: $DATE" --created "$DATE"
```

`auto-dev-loop` ラベルが無ければ先に `gh label create auto-dev-loop` で作る。

## 3. 1 監視パスの本体

§1 で状態を読み込んだら、以下を順に行う。すべて作業用 `/tmp/adl-state.json` に対して更新し、
最後に §3.5 で description へ書き戻す。

### 3.1 発見と分析（FR-2）

対象ラベルの open issue を取得し、**Claude が実現可能性と依存関係を判定**する。

```sh
gh issue list --label <target-label> --state open --json number,title,body,labels,updatedAt
```

issue が多い／重いときは **複数のサブエージェント**（`Agent`）に分担させ、各 issue について
[`references/playbook.md`](references/playbook.md) の基準で「いま実装可能か」「依存」を構造化で
返させる。結果を統合し、依存があれば解決順序を含む計画を立てる。状態へ記録:

```sh
python3 "${CLAUDE_PLUGIN_ROOT}/tools/auto_dev_loop.py" upsert-issues \
  --state /tmp/adl-state.json --json <payload>
```

ペイロードは `[{"number":123,"title":"...","status":"analyzed","deps":[120],"note":"..."}]`。
実装可能なら `analyzed`、情報不足・スコープ不明・要設計判断は `blocked`、無効・重複は `cancelled`。

**`blocked` にした issue には、何が曖昧／不足で着手できないかを当該 issue にコメントする**
（人間が補足すれば `analyzed` に進める）。ただし**冪等**にする: 同じ blocker を毎パス、あるいは
別トラッキング issue になっても重複コメントしない。状況に変化がなければコメントしない。詳細は
[`references/playbook.md`](references/playbook.md) の「blocked 理由の通知」を参照。

### 3.2 ディスパッチと実装（FR-3）

**いま着手してよい issue** はヘルパが決定的に算出する（依存が全て merged、かつ並行枠に空き）:

```sh
python3 "${CLAUDE_PLUGIN_ROOT}/tools/auto_dev_loop.py" next-ready --state /tmp/adl-state.json
```

`ready=` の各 issue について [`references/playbook.md`](references/playbook.md) の手順で:

1. **worktree を作る**（issue ごとに隔離、ベースブランチから新ブランチ）。
   `update-issue --number N --status implementing --branch <b> --worktree <path>`。
2. **auto-review-loop で実装する**（`Skill` で `cc-workflow:auto-review-loop`、§2 のプリセットを
   渡す）。**全ての実装は必ず auto-review-loop を通す**（直接コミットしない）。
3. **PR を作る**（マージ先 `merge_target`、本文に `Closes #N`）。グローバル CLAUDE.md に従い
   レビュアー/アサインを設定。`update-issue --number N --status pr_open --pr <pr#>`。
4. 実装担当**サブエージェントは、担当 issue と作った PR に詳細な状況コメント**を残す（何をした
   か・テスト・残課題）。メインはそれを要約してテーブルに反映する。

並行枠の範囲で複数 issue を worktree を分けて並行実装してよい。超過分は次パスに回る。

### 3.3 issue / PR コメント監視（FR-4）

各管理 issue・各 PR の watermark 以降の新規コメント/レビューを `gh` で取得し、§5 でトリアージ。
読み終えたら watermark を更新:

```sh
python3 "${CLAUDE_PLUGIN_ROOT}/tools/auto_dev_loop.py" watermark \
  --state /tmp/adl-state.json --kind issue|pr --number N --ts <最新コメント時刻>
```

自分（メイン/サブ）が書いたコメントは無視する。

### 3.4 CI / 自動マージゲート（FR-6）

PR の CI 状態を確認し、§6 のゲートを評価。条件を満たせばマージし
`update-issue --number N --status merged --pr <pr#>`。

### 3.5 description へ書き戻す

このパスの更新をテーブル + JSON として再生成し、トラッキング issue に反映する:

```sh
python3 "${CLAUDE_PLUGIN_ROOT}/tools/auto_dev_loop.py" render --state /tmp/adl-state.json > /tmp/adl-body.md
gh issue edit <tracking#> --body-file /tmp/adl-body.md
```

## 4. 監視ループの駆動（heartbeat）

このスキルは `/loop` 自己ペースで駆動する。**1 起床 = §3 の 1 パス**:

```
/loop /cc-workflow:auto-dev-loop
```

各起床で §1（body 読み込み）→ §3（分析・ディスパッチ・コメント監視・マージ・書き戻し）を実行し、
§7 の停止条件に当たらない限り `ScheduleWakeup` で同じ `/loop` 入力を再投入して継続する。アイドル時は
長め（1200–1800s）、CI 待ち等の外部状態を待つときは短め（〜270s）に。ターミナルでの追加指示は
起床間の通常メッセージとして届くので自然に反映する。

## 5. コメントのトリアージ（FR-5）

種別を判定して反映する（詳細は [`references/playbook.md`](references/playbook.md)）:

- **追加・変更指示** → 仕様反映 → auto-review-loop で再実装。必要なら計画/依存を更新。
- **PR 説明が不明瞭** → PR 本文を書き直す。
- **修正指示** → 当該 worktree で auto-review-loop により修正し push。
- **取りやめ** → PR クローズ・worktree 片付け → `update-issue --status cancelled`。
- **issue 記述の誤り** → 正しい理解で再計画。影響する依存も見直す。
- **承認 / マージ指示** → §6 のゲートを評価。

曖昧・矛盾・破壊的なコメントは**勝手に進めず**、要約して人間に確認を促す。

## 6. 自動マージゲート（FR-6）

`auto_merge` 方針に応じてのみマージ（不可逆操作なので条件を厳密に満たすときだけ）:

- `off`: 自動マージしない（常に人間承認待ち）。
- `conditional`（推奨）: **auto-review-loop completed** かつ **CI green** かつ
  **PR に承認・マージ指示がある**の 3 条件で初めてマージ。
- `green`: auto-review-loop completed かつ CI green でマージ（人間承認不要）。

マージ後 `update-issue --status merged` により、依存していた issue が `next-ready` で着手可能になる。

## 7. 停止条件と継続（NFR-1 / NFR-3）

ループを**終了する**ときは必ず「最後の状況を description に書き戻してから、トラッキング issue を
close する」。書き戻す前に close すると最終状態が残らないので、順序を守る:

1. `set-run-status --status <stopped|done>`
2. §3.5（`render` → `gh issue edit`）で最後の状況を description に反映する。
3. `gh issue close <tracking#>`（必要なら `--comment` で終了理由を残す）。
4. 現状を要約し、`ScheduleWakeup` を予約せず終了する。

終了経路:

- **明確な停止指示**（「止めて」「stop」）→ `status=stopped` で上記 1–4。
- **自然収束**（全 issue が merged/cancelled で新規も無い ＝ `summary` の `active_issues=0`）→
  `status=done` で上記 1–4。**確認は求めず自動で close する**。
- **トラッキング issue が人手で close された**のを検知 → 既に閉じているので 3 は不要。`status=stopped`
  を書き戻し（closed issue でも `gh issue edit` は可能）、要約して終了する。

継続と中断（終了ではない）:

- 上記以外は、**全 PR が確認待ちになっても止めない**。停止指示が無い限り §3 のパスを継続予約し、
  PR/issue の確認を回し続ける（「自走」の要件）。
- **中断**（「ちょっと待って」等、指示を与えるための一時停止）は *終了ではない*。即座に予約を止め、
  現状を要約して制御を返すが、トラッキング issue は **open のまま**残す（§1 の再開を効かせるため）。
  ユーザが続けて停止を指示したら、上の「明確な停止指示」経路で close する。

## 可観測性（NFR-2）

進捗はトラッキング issue を見れば分かる。ターミナルからは:

```sh
gh issue view <tracking#>                          # テーブルを直接見る
python3 "${CLAUDE_PLUGIN_ROOT}/tools/auto_dev_loop.py" summary --state /tmp/adl-state.json
```

各実装の詳細はその PR/作業 issue のコメントに、auto-review-loop の各 run はそのスキル側の state に残る。
