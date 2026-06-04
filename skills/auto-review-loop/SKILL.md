---
name: auto-review-loop
description: >-
  TDD ベースで「実装 → レビュー →（必要なら）修正 → 再レビュー」を有限回（最大2往復）
  自動で回すワークフロー。**ユーザの実装指示文中にキーワード「自動レビューで」または
  「auto review」が明示的に含まれているときだけ** 起動する。例：「では実装して、自動レビューで」。
  キーワードを含まない通常の「実装して」では起動しない。起動時に「誰にレビューさせるか」
  「どの観点で見るか」を問いかけ、選択されたレビュアー×観点で並列レビューし、Claude が
  トリアージして妥当な must-fix のみ修正する。
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, Agent, AskUserQuestion, Skill
---

# auto-review-loop

ユーザが **「自動レビューで」/「auto review」を実装指示に明示** したときに限り、TDD で実装し、
選択されたレビュアー×観点でレビューし、Claude のトリアージを挟んで有限回だけ修正ループを回す。
ループ・使用量の消費はユーザ了解済みの前提（NFR-4）。

このスキルは **状態管理** を `tools/review_loop.py`（決定的な bookkeeping）に委ね、
**判断**（トリアージ・修正）は自分で行う。レビュアーの呼び出し方と共通指摘スキーマは
[`reviewers.md`](reviewers.md) を参照。

ヘルパは `${CLAUDE_PLUGIN_ROOT}/tools/review_loop.py` にある。以下のコマンド例の
`tools/review_loop.py` は実際にはこの絶対パスで呼ぶこと。

---

## 0. トリガ確認（TR-1 / TR-2）

ユーザの**実装指示文中に**「自動レビューで」「auto review」等が含まれているか確認する。
含まれていなければこのスキルは起動しない（通常実装に戻る）。規模では判定しない（TR-4）。

## 1. 起動時の問いかけ（FR-1）

コードを書く前に、`AskUserQuestion` で **2問** を問う（両方とも複数選択可）。

1. **誰にレビューさせるか**（reviewers）。選択肢は [`reviewers.md`](reviewers.md) の登録分。
   既定・推奨は単一の **Claude サブエージェント**（先頭に置く）。Codex も選べる。
2. **どの観点で見るか**（perspectives）。例：正確性 / 要件適合 / セキュリティ /
   パフォーマンス / 規約 / 文体 / テストカバレッジ。

並列レビューは観点の分業と独立した第二意見が目的だが、使用量と指摘総量（偽陽性含む）が
増える。既定は単一レビュアーで、並列はユーザが明示的に選んだときだけ（§5 of spec）。

### Codex 可用性チェック（FR-1.5）

reviewers に Codex が含まれるなら、レビューに入る前に **導入・ログインを確認** する。
`codex:setup` スキル（`Skill` ツール）で Codex CLI が ready か確かめる。未導入／未ログインなら
**黙ってスキップせず**、その旨をユーザに伝えて別レビュアーを選ばせる（問い 1 を再提示）。

## 2. 状態の初期化（FR-8）

選択を記録し run を作る。`reviewers` / `perspectives` は問いの回答をカンマ区切りの
**安定した id**（例：`claude,codex` / `correctness,security`）に正規化して渡す。

```sh
python3 "${CLAUDE_PLUGIN_ROOT}/tools/review_loop.py" init \
  --reviewers <r1,r2,...> --perspectives <p1,p2,...> --title "<実装の短い題>"
```

出力の `run_dir` / `state_path` / `max_review_rounds`（=3）を控える。以降のヘルパ呼び出しは
セッションの「open run」を自動で参照するので `--run` は通常不要。

## 3. 実装（FR-2・TDD）

CLAUDE.md の TDD（Red → Green → Refactor）で実装する。各編集後に **決定的チェック**
（プロジェクトのテスト・リンタ・型）を実行し、緑にしてからレビューへ進む（FR-2.2）。
決定的チェックは判断系レビューとは層が違う。これは機械的に必ず通す。

## 4. レビューループ

以下を 1 ラウンドとして回す。

### 4.1 ラウンド開始（FR-3 / FR-7）

```sh
python3 "${CLAUDE_PLUGIN_ROOT}/tools/review_loop.py" start-round
```

- `round` … 今のラウンド番号、`round_dir` … 全文の保存先、`pairs` …
  **今ラウンドで回す reviewer×perspective**（`reviewer::perspective,...` 形式）。
- ラウンド1は選択した全 pair。**ラウンド2以降は前ラウンドで指摘を出した pair のみ**に
  自動で絞られる（FR-7）。クリーンだった pair は再レビューしない。
- `over_cap=1` が返ったら上限超過。§4.5 の打ち切りへ（通常はここに来る前に circuit-check で止める）。

### 4.2 レビュー実行（FR-3.2）

`pairs` の各組を [`reviewers.md`](reviewers.md) の方法で **並列に** 走らせる
（Claude=`Agent` ツール、Codex=`codex:` runtime）。**全結果が出揃うまで次工程に進まない。**
部分的な結果で行動しない。各レビューは共通指摘スキーマ（`reviewers.md`）で結果を返す。

各レビューの **全文を保存** する（FR-8.4）。`round_dir` 配下に
`<reviewer>-<perspective>.md` として `Write` で書く。作業コンテキストには要約のみ載せる。

### 4.3 トリアージ（FR-4）

全結果が揃ったら **自分で統合・吟味** する。修正可否はユーザに問わない（自動判定）。

- 各指摘の妥当性を判断。偽陽性（コードベースに合わない好み・意図的箇所・観点外）は
  **理由を簡潔に付して退ける**。
- 妥当な **must-fix** が残るかを決める。残った must-fix を出した reviewer×perspective の組を
  `with_findings` とする（次ラウンドの絞り込みに使う）。

ラウンド結果を JSON で書き、記録する。JSON の形：

```json
{
  "n": <round>,
  "ran": [{"reviewer":"claude","perspective":"correctness"}, ...],
  "findings": [
    {"id":"r1-1","reviewer":"claude","perspective":"correctness",
     "severity":"must-fix","file":"x.py","line":42,"title":"...","detail":"...",
     "triage":"accepted","triage_reason":""}
  ],
  "with_findings": [{"reviewer":"claude","perspective":"correctness"}],
  "resolved": false
}
```

`with_findings` には **accepted な must-fix を出した組だけ** を入れる（退けた指摘しか
無かった組は入れない）。書いたら：

```sh
python3 "${CLAUDE_PLUGIN_ROOT}/tools/review_loop.py" record-round --json <path-to-json>
```

### 4.4 完了判定（FR-4.3 / FR-6.4）

`record-round` の `with_findings_count=0`（＝妥当な must-fix が残らない）なら **完了**。
上限前でも終了する。

```sh
python3 "${CLAUDE_PLUGIN_ROOT}/tools/review_loop.py" finish --status completed
```

完了をユーザに簡潔に報告（ラウンド数・退けた指摘の要約・最終状態）。**終了。**

### 4.5 サーキットブレーカー判定（FR-6）

must-fix が残るなら、修正に入る前に上限を確認する。

```sh
python3 "${CLAUDE_PLUGIN_ROOT}/tools/review_loop.py" circuit-check
```

- `should_break=1`（= 3 ラウンド目相当でなお must-fix）なら **打ち切り**。
  ループを失敗として中断するのではなく、**ユーザへ差し戻す**（FR-6.3）：

  ```sh
  python3 "${CLAUDE_PLUGIN_ROOT}/tools/review_loop.py" finish --status handed_back
  ```

  未解決の must-fix を要約して提示し、判断を委ねる。**終了。**
- `should_break=0` なら次の修正へ進む。

### 4.6 修正（FR-5）

`with_findings` の妥当な指摘を **TDD で修正** する（再現する失敗テスト → 最小実装 → refactor）。
修正後、決定的チェックを緑にする。

### 4.7 解消検証 → 次ラウンド（FR-8.3）

次の `start-round` の前に、**前ラウンドの指摘が実際に解消したか** を確認する
（修正がテストで担保され、当該箇所が変わっていること）。確認できたら §4.1 に戻り次ラウンドへ。
次ラウンドは前ラウンドの `with_findings` の組だけが自動で対象になる。

---

## 中断可能性（NFR-3）

ユーザはいつでもループを中断できる。中断要求が来たら即座にループを止め、現状
（ラウンド数・未解決指摘）を要約して制御を返す。`finish --status handed_back` を打ってよい。

## 可観測性（NFR-2）

各ラウンドの実行 pair・指摘・トリアージ・解消状況は `state.json` に、全文は
`round-<n>/*.md` に残る。`status` でいつでも現在地を確認できる：

```sh
python3 "${CLAUDE_PLUGIN_ROOT}/tools/review_loop.py" status
```
