# auto-dev-loop プレイブック

SKILL.md のフェーズを実行するときの具体手順。SKILL.md が「いつ・なぜ」を、ここが「どうやって」を持つ。

## 目次

- [issue 分析の基準](#issue-分析の基準)
- [依存関係の検出と計画](#依存関係の検出と計画)
- [worktree 運用](#worktree-運用)
- [auto-review-loop の起動（無人）](#auto-review-loop-の起動無人)
- [PR の作成とレビュアー割り当て](#pr-の作成とレビュアー割り当て)
- [コメント監視の実装](#コメント監視の実装)
- [コメントのトリアージ分類](#コメントのトリアージ分類)
- [自動マージゲートの判定](#自動マージゲートの判定)
- [issue 状態の遷移表](#issue-状態の遷移表)

---

## issue 分析の基準

各 issue について「**いま実装可能か**」を判定する。`analyzed`（着手可）にできるのは、人間の
追加説明なしに着手できると確信できるとき。次のいずれかに当たれば `blocked` か `cancelled`:

- **スコープが不明確**: 何を作れば「完了」かが本文から読み取れない。
- **情報不足**: 必要な仕様・受け入れ条件・参照先が欠けている。
- **未解決の依存**: 別 issue / 別 PR の完了が前提（→ `deps` に記録して `analyzed` のまま、
  依存が merged になるまでヘルパが自動で着手を保留する）。
- **要設計判断**: アーキテクチャの選択など、人間の意思決定が要る。
- **既に対応済み / 重複 / 無効**: → `cancelled` とし、理由を `note` に。

判定は保守的に。曖昧なら `analyzed` にせず `blocked` にして、§コメント監視で人間の補足を待つ。

複数 issue を分析するときは `Agent` サブエージェントに分担させ、各々に以下を構造化で返させる:

```json
{"number": 123, "feasible": true, "status": "analyzed",
 "deps": [120], "reason": "...", "plan_sketch": "..."}
```

## 依存関係の検出と計画

依存の手がかり: issue 本文の「#NNN が前提」「blocked by」記述、同一ファイル/モジュールを触る
issue 同士、データモデル → それを使う機能、という層の関係。検出したら依存元の issue 番号を
`deps` に入れる。

`deps` はヘルパの `compute_ready` が解釈する。**依存先が `merged` になるまで着手は保留**され、
並行枠の空きと合わせて `next-ready` が「いま着手してよい集合」を返す。循環依存を見つけたら
着手せず人間に報告する（ヘルパは循環を解かない）。

「A と、A を使う B」のように分割実装が妥当なら、A を先に `analyzed`、B を `deps:[A]` にする。
A の PR が merged になると B が自動で ready になる。

## worktree 運用

issue ごとに作業を隔離する。並行実装でも互いのツリーを汚さない。

```sh
# ベースブランチを最新化してから worktree を作る
git fetch origin
git worktree add -b auto/issue-<N>-<slug> <worktreesDir>/issue-<N> origin/<base>
```

- `<worktreesDir>` はリポジトリ外（例: `../.cc-worktrees/<project>/`）が安全。リポジトリ内に作る
  場合は `.gitignore` 済みのパスにする。
- ブランチ名は `auto/issue-<N>-<slug>` 等で衝突を避ける。`update-issue --branch --worktree` で記録。
- 完了（merged）または取りやめ（cancelled）したら片付ける:
  `git worktree remove <path>`（未コミット変更が無いことを確認）、必要ならローカルブランチ削除。
- `Agent` の `isolation: worktree` を使う場合はそのエージェント内で実装が完結する。永続的に
  worktree を保持して PR 監視で再修正したいなら、明示的な `git worktree` の方が扱いやすい。

## auto-review-loop の起動（無人）

**全ての実装は `cc-workflow:auto-review-loop` を通す**（直接コミット禁止）。`Skill` ツールで起動し、
当該 worktree を作業対象にする。auto-review-loop は通常レビュアー/観点を対話で問うが、自走中は
§1 で確定したプリセット（既定: reviewers=`claude`、perspectives=全観点）で進める。

auto-review-loop は内部で TDD（Red→Green→Refactor）と有限回の修正ループを回し、
`completed` か `handed_back` で終わる。`handed_back`（上限まで回しても must-fix が残る）になったら、
その issue は自動では PR にせず、要約して人間に委ねる（`failed` か `blocked`）。

**コメントの分担**: 実装担当のサブエージェントは、自分が触る**作業 issue と作った PR に詳細な
状況をコメント**で残す（着手・実装内容・テスト結果・残課題）。トラッキング issue には書かない。
メインエージェントはその詳細を**要約して**トラッキング issue の description（テーブル + JSON）に
反映する。description を書くのはメインだけ（単一書き手で競合を避ける）。

## PR の作成とレビュアー割り当て

```sh
gh pr create --base <merge_target> --head auto/issue-<N>-<slug> \
  --title "<簡潔な題>" --body "$(cat <<'EOF'
## 概要
...

Closes #<N>
EOF
)"
```

PR 作成後、**グローバル CLAUDE.md の規約**に従う:
- 原則 reviewer に `jtfrom9` を追加: `gh pr edit <pr#> --add-reviewer jtfrom9`。
- ただし **PR 作者が `jtfrom9` 自身**の場合（このリポジトリの git user は `jtfrom9`）、作者は
  自分をレビュアーにできないので **assignee** にする。`--add-assignee` が Projects classic の
  GraphQL エラーで反映されないことがあるため、その場合は REST API:
  ```sh
  gh api repos/<owner>/<repo>/issues/<pr#>/assignees -X POST -f "assignees[]=jtfrom9"
  ```

PR 番号を `update-issue --state /tmp/adl-state.json --number N --status pr_open --pr <pr#>` で記録する
（このパス限りの作業用 state。最終的に `render` → `gh issue edit` で description へ書き戻す）。

## コメント監視の実装

watermark（最後に見たコメント時刻）以降の新規だけを拾う。

```sh
# issue コメント（作成時刻つき）
gh issue view <N> --json comments --jq \
  '.comments[] | {created: .createdAt, author: .author.login, body: .body}'

# PR コメント + レビュー
gh pr view <pr#> --json comments,reviews,statusCheckRollup
```

取得したコメントのうち `created > watermark` のものだけをトリアージ対象にする。処理後、最新
コメントの時刻で `watermark --state /tmp/adl-state.json --kind issue|pr --number N --ts <iso>` を
更新する。これにより次の wake-up は新規ぶんだけを見る。自分（メイン/サブの bot/Claude）が
書いたコメントは無視する。watermark も含め、このパスの更新は最後に `render` → `gh issue edit` で
トラッキング issue の description へ書き戻して初めて永続化される（ローカルには残らない）。

## コメントのトリアージ分類

| 種別 | 兆候 | 対応 |
|---|---|---|
| 追加・変更指示 | 「〜も対応して」「仕様変更」 | 仕様反映 → auto-review-loop で再実装。必要なら計画/依存更新 |
| 説明が不明瞭 | 「PR の説明が分からない」 | PR 本文を書き直す（実装は変えない） |
| 修正指示 | 「ここがバグ」「この観点で直して」 | 当該 worktree で auto-review-loop により修正 → push |
| 取りやめ | 「これは要らない」「close して」 | PR close・worktree 片付け → `status cancelled` |
| issue 記述の誤り | 「issue の前提が間違ってた」 | 正しい理解で再計画。影響する deps も見直し |
| 承認・マージ | 「LGTM」「approve」「マージして」 | 自動マージゲート（下記）を評価 |
| 質問・雑談 | 情報を尋ねている | 簡潔に回答コメント。実装は変えない |

破壊的・曖昧・矛盾するコメントは**勝手に実行せず**、要約して人間に確認を促す。特に
「force push」「履歴改変」「他ブランチへの影響」を伴うものは止める。

## 自動マージゲートの判定

`auto_merge` 方針（state の config）で分岐。

- **`off`**: マージしない。承認系コメントが来ても「人間がマージしてください」と促すに留める。
- **`conditional`**（推奨）: 次の **3 条件すべて**で初めてマージ:
  1. その issue の auto-review-loop run が `completed`（`handed_back` は不可）。
  2. CI が green（`gh pr view --json statusCheckRollup` で全 success / 必須チェック通過）。
  3. PR コメント/レビューに**承認・マージ指示**がある（人間の `approve` or 明示の「マージして」）。
- **`green`**: 上記 1 と 2（auto-review-loop completed かつ CI green）でマージ。人間承認は不要。

マージ:

```sh
gh pr merge <pr#> --squash --delete-branch   # マージ方法はプロジェクト慣習に合わせる
```

マージ後 `update-issue --number N --status merged --pr <pr#>`、worktree を片付ける。コンフリクト等で
失敗したら worktree で rebase/解消を試み、解けなければコメントで報告し `failed`/人間待ちにする。

## issue 状態の遷移表

| status | 意味 | 次に来やすい状態 |
|---|---|---|
| `discovered` | gh で見つけたが未分析 | analyzed / blocked / cancelled |
| `analyzed` | 着手可。deps 解決＆枠空きで ready | implementing |
| `blocked` | 情報不足等で保留（人間待ち） | analyzed / cancelled |
| `implementing` | worktree で実装中（並行枠を消費） | pr_open / failed |
| `pr_open` | PR 提出済み・監視中（枠は消費しない） | merged / cancelled / implementing(再修正) |
| `merged` | マージ済み（依存先を解放） | （終端） |
| `cancelled` | 取りやめ | （終端） |
| `failed` | エラーで断念・人間待ち | implementing（再開時） |

`compute_ready` が着手対象とするのは `analyzed` のみ。並行枠を消費するのは `implementing` のみ。
依存を満たす（dependent を解放する）のは `merged` のみ。
