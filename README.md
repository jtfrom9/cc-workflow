# jtfrom9-cc-workflow

jtfrom9 個人用の Claude Code ワークフロー支援プラグイン。「セッション管理のミス」を防ぐための小さなフックを集めている。

フックと、そのフックから呼ばれるシェルスクリプトを 1 つのプラグインとして同梱している。`${CLAUDE_PLUGIN_ROOT}` でプラグイン自身の場所が解決されるので、どこに clone しても動く。

## 目的

長時間の Claude Code セッションでありがちな小さな事故を、機械的に防ぐ／気付かせる:

- **セッションに名前を付け忘れる** → どのセッションが何の作業だったか分からなくなる
- **本来別セッションにすべき作業を混ぜる** → コンテキストが汚れ、圧縮で重要情報が失われる
- **長すぎるセッションをそのまま走らせる** → 圧縮事故、コスト膨張
- **作業途中で別ブランチ／別リポに移ってしまう** → コミット先のミス

このリポジトリでは段階的に防止機構を増やしていく。

## 使い方

このリポジトリをクローンして、プラグインとして読み込ませる:

```sh
git clone <this-repo> ~/src/jtfrom9-cc-workflow
claude --plugin-dir ~/src/jtfrom9-cc-workflow
```

`--plugin-dir` はそのセッションだけプラグインを有効化する一番手軽な方法。複数指定可。

永続的にインストールしたい場合はマーケットプレース経由で（`.claude-plugin/marketplace.json` を別途用意する必要あり）:

```sh
claude plugin marketplace add ~/src/jtfrom9-cc-workflow
claude plugin install jtfrom9-cc-workflow
```

## ディレクトリ構造

```
<repo>/                              ← プラグインルート (= ${CLAUDE_PLUGIN_ROOT})
├── .claude-plugin/
│   └── plugin.json                  ← プラグインマニフェスト（フック宣言などはここ）
├── hooks/                           ← シンプルな bash フック
│   └── banner.sh                    ←   SessionStart で名前表示
├── commands/
│   ├── restore.md                   ← /jtfrom9-cc-workflow:restore <taskId> でプランを復元
│   ├── checkpoint.md                ← /jtfrom9-cc-workflow:checkpoint で議論を保存
│   ├── summarise.md                 ← /jtfrom9-cc-workflow:summarise <taskId> で summary.md 再生成
│   └── tasks.md                     ← /jtfrom9-cc-workflow:tasks で task 一覧表示
├── scripts/                         ← シンプルな bash ヘルパー (commands から呼ばれる)
│   ├── restore-task.sh              ←   restore コマンドのヘルパー
│   └── list-tasks.sh                ←   tasks コマンドのヘルパー
├── python/                          ← 複雑なロジックは Python (UTF-8 / 非同期 / 状態管理)
│   ├── _common.py                   ←   共通ユーティリティ
│   ├── _summarize_worker.py         ←   バックグラウンド要約ワーカー（失敗時は詳細を summary.md に書く）
│   ├── maybe_spawn_summary.py       ←   plan.md が長ければ要約ワーカーを spawn
│   ├── regenerate_summary.py        ←   /summarise の本体（今開いている task の summary.md を再生成）
│   ├── mark_task_open.py            ←   /restore から呼ばれて open_task_id を更新
│   ├── relocate_plan.py             ←   PostToolUse(ExitPlanMode): plan ファイルを task 化
│   └── checkpoint.py                ←   checkpoint の本体（手動も自動も同じスクリプト。`--auto` で Stop フック）
└── README.md
```

実行時状態はホーム側に分離:

```
~/.jtfrom9-cc-workflow/
├── tasks/<project>/<taskId>/        ← プロジェクト単位 + タスク単位の置き場
│   ├── plan.md                      ←   承認されたプラン本体
│   ├── task.md                      ←   タスクのメタ情報 (frontmatter に taskId)
│   └── summary.md                   ←   plan.md が長ければ要約 (短ければ説明文)
├── state/<session-id>/              ← セッション毎の sentinel
│   ├── count
│   ├── suggested
│   └── renamed
└── log/
```

`taskId` の形式は `<index>-<yymmdd>-<original-name>`:

| 部分 | 例 | 説明 |
|---|---|---|
| `<index>` | `0001` | プロジェクト内のローカル通し番号。4 桁 0 埋め |
| `<yymmdd>` | `260515` | 承認日 |
| `<original-name>` | `pure-pondering-crystal` | Claude Code が生成したプランファイル名 (`.md` を除いたもの) |

#### index の採番ルール

各プロジェクトのタスク置き場直下に `.last_index` という隠しカウンタファイルを置き、「これまでに使った最大 index」を記録する。新しい index は以下で決まる:

```
next_index = max(.last_index の値, 既存フォルダ名から抽出した最大番号) + 1
```

これにより:

- フォルダを個別に削除しても、削除した番号が再利用されない（最大番号の削除を含む）
- 万一 `.last_index` を失っても「既存フォルダの最大値 + 1」にフォールバックする
- フォルダ・カウンタの両方が消えれば 0001 から再開する

#### task.md の frontmatter で出所と起動方法を区別

`source:` は task が何を表すか、`trigger:` は誰が起動したかを示す:

| `source` | `trigger` | どこから作られたか |
|---|---|---|
| `plan` | (なし) | プランモードで承認された ExitPlanMode の plan (`python/relocate_plan.py`) |
| `checkpoint` | `manual` | `/jtfrom9-cc-workflow:checkpoint` から手動採取 (`python/checkpoint.py`) |
| `checkpoint` | `auto` | Stop フックでトークン閾値を超えて自動採取 (`python/checkpoint.py --auto`) |

自動 checkpoint と手動 checkpoint は **同じスクリプト・同じ source・同じ task 構造** を持ち、違いは「誰が起動したか」と「plan.md にどこまで内容を書くか」だけ。手動の場合は Claude が plan.md を後から詳細内容で上書きする。

`~/.jtfrom9-cc-workflow/` 配下は実行時に自動で作られる。壊れても消しても良い。

## 機能

### banner: 起動確認バナー

`SessionStart` フックで `systemMessage` に `jtfrom9-cc-workflow` を表示する。プラグインが正しく有効化されていることを起動時に確認するためのもの。

スクリプト: [`hooks/banner.sh`](hooks/banner.sh)

### 自動 checkpoint: Stop でトークン使用量を見て自動採取

Claude の応答が終わるたびに（`Stop` フック）、現在のコンテキスト使用量を確認して、必要なら task を自動採取する。判定は LLM に投げず、セッショントランスクリプト (`~/.claude/projects/<encoded>/<sid>.jsonl`) の `usage.cache_read_input_tokens + cache_creation_input_tokens + input_tokens` をそのまま読む。

トリガルール:

- **「前回タスク」** = `~/.jtfrom9-cc-workflow/tasks/<project>/` 内で **最大 index** の task（source 問わず）
- **同セッション**: 現在トークン > 前回タスク時のトークン × (1 + 30%) → 採取
- **別セッション**: 現在トークン > 最大コンテキスト × 30% → 採取
- **前回タスクなし**: 別セッションの場合と同じく 30% 越えで採取

#### 採取される内容（重要）

`~/.jtfrom9-cc-workflow/tasks/<project>/<taskId>/` の中身:

**`plan.md` （メタ情報のみ。会話本文は転記しない）**

```markdown
# Auto-checkpoint <ISO 時刻>

_(Stop フックで自動採取された checkpoint。トリガ: <発火理由文>)_

- 採取時刻: `<ISO 時刻>`
- セッション ID: `<sid>`
- 現在のコンテキスト使用量: `<tokens 数>` tokens
- 前回タスク: `<前回 taskId or "(なし)">`
- 前回タスク時のトークン: `<前回 tokens 数>`
- 前回セッション ID: `<前回 sid or "(なし)">`

会話の中身はセッショントランスクリプトを参照: `~/.claude/projects/<encoded>/<sid>.jsonl`
```

**`task.md` （frontmatter にトリガ情報）**

```yaml
---
taskId: "<taskId>"
created_at: "<ISO 時刻>"
project: "<project>"
project_root: "<cwd>"
session_id: "<sid>"
source: checkpoint
trigger: auto
tokens: <現在トークン数>
prev_task_id: "<前回 taskId>"
prev_tokens: <前回トークン数>
prev_session_id: "<前回 sid>"
trigger_reason: "<発火理由文>"
status: pending
---
```

**何を保存「しない」か**

- 会話の本文（ユーザの発話・Claude の応答）は `plan.md` に転記しない。JSONL を別途参照する設計
- 採取時点で要約も走らせない（コスト・遅延・サンドボックス制約を避けるため）
- 中身の要約が欲しくなったら、後から `/jtfrom9-cc-workflow:summarise` を手動実行する

スクリプト: [`python/checkpoint.py`](python/checkpoint.py) （`--auto` 起動時）

| 変数 | デフォルト | 意味 |
|---|---|---|
| `JTFROM9_CC_WORKFLOW_AUTO_CHECKPOINT` | `1` | `0` で自動採取を無効化 |
| `JTFROM9_CC_WORKFLOW_CHECKPOINT_PCT` | `30` | 採取の閾値パーセント |
| `JTFROM9_CC_WORKFLOW_MAX_CONTEXT_TOKENS` | `200000` | 別セッション判定の母数。Opus 1M variant 利用時は `1000000` に |

#### 制約

- 採取される plan.md には会話本文を載せない（トランスクリプトを別途参照する想定）。要約が欲しければ `/jtfrom9-cc-workflow:summarise` を後から手動実行する
- Stop フックは毎ターン発火するが、閾値ロジックで実質的に発火頻度は抑制される（前回比 30% 増えたタイミングのみ）

### relocate-plan: プランをタスクフォルダにまとめて、承認後にいったん停止

`ExitPlanMode` で承認されたプランは Claude Code がデフォルトで `~/.claude/plans/` 直下に `<slug>.md` としてフラットに書き出す。
このフックは `PostToolUse` を `ExitPlanMode` matcher で受け、以下を行う:

1. **taskId 採番**: `<index>-<yymmdd>-<original-name>` (index はプロジェクト内通し番号 4 桁 0 埋め)
2. `~/.jtfrom9-cc-workflow/tasks/<project>/<taskId>/` フォルダを作り:
   - `plan.md`: 承認されたプラン本体（移動）
   - `task.md`: メタ情報。frontmatter に `taskId` 等を持つ
   - `summary.md`: `plan.md` が長ければ `claude -p` で非同期に要約生成。短ければ要約不要のメッセージ
3. `JTFROM9_CC_WORKFLOW_PAUSE_AFTER_PLAN=1` (デフォルト) なら、`{ "continue": false, "stopReason": ... }` を返してターン停止。
   「プランの承認」と「実装開始」を分離し、保存されたプランをユーザが確認・編集してから改めて指示できる。

挙動:

```
承認
 → ExitPlanMode 実行: ~/.claude/plans/<slug>.md が書かれる
 → PostToolUse フック発火
 → python/relocate_plan.py:
     taskId 採番
     <slug>.md → ~/.jtfrom9-cc-workflow/tasks/<project>/<taskId>/plan.md
     task.md (frontmatter + 自由記述欄) を生成
     summary.md を生成 (長いプランは裏で claude -p、短ければ静的文言)
 → python/relocate_plan.py: continue:false でターン停止 (デフォルト時)
   → ユーザに制御が戻る。プランファイルを確認 / 編集できる
 → ユーザが「進めて」「実装して」等と指示
 → Claude が実装に進む
```

- プロジェクト名: Claude Code セッションの cwd のベース名（git は参照しない）
- 「直近に書かれた .md」判定: `plansDirectory` 内で 5 分以内に変更された `*.md` の最新

スクリプト: [`python/relocate_plan.py`](python/relocate_plan.py)

#### task.md の中身

```yaml
---
taskId: "0001-260515-pure-pondering-crystal"
created_at: "2026-05-15T10:00:00+0900"
project: "claude-settings"
project_root: "/Users/jtfrom9/work/jtfrom9/claude-settings"
session_id: "..."
original_plan_name: "pure-pondering-crystal"
status: pending
---

# <taskId>

(自由記述: 作業中のメモ、決定事項、成果物リンクなど)
```

`status` は `pending` で始まり、ユーザ／Claude が進捗に応じて手動更新することを想定。

#### 環境変数

| 変数 | デフォルト | 意味 |
|---|---|---|
| `JTFROM9_CC_WORKFLOW_SOURCE_PLANS` | `$HOME/.claude/plans` | 移動元（`plansDirectory` を変更している場合に合わせる） |
| `JTFROM9_CC_WORKFLOW_PAUSE_AFTER_PLAN` | `1` | `1` で承認後に停止、`0` でそのまま実装に進む |
| `JTFROM9_CC_WORKFLOW_SUMMARY_THRESHOLD_LINES` | `50` | `plan.md` がこの行数を超えたら `claude -p` で要約生成 |
| `JTFROM9_CC_WORKFLOW_CLAUDE_CMD` | `claude` | 要約・分類で叩く `claude` バイナリの上書き。docker / sandbox ラッパー越しの起動で TTY エラーになる環境用。例: `/usr/local/bin/claude-direct`、`false`（要約完全無効化）|

#### 制約

- フック入力には書かれたプランファイルのパスが含まれないため、`plansDirectory` 内の「直近最新の .md」をヒューリスティックで拾っている。
- 同一セッション内で複数プランを短時間に連続で承認した場合、競合する可能性がある。
- 要約生成 (`claude -p`) はバックグラウンドで走り、終わるとファイルが上書きされる。失敗するとプレースホルダのまま残ることがある。
- ユーザが `plansDirectory` を別のディレクトリに設定している場合は `JTFROM9_CC_WORKFLOW_SOURCE_PLANS` でそちらを指定する。

## カスタムコマンド

### `/jtfrom9-cc-workflow:checkpoint`: 明示的に議論を保存（インクリメンタル）

これまでの会話を Claude に **詳細に**（甘くまとめずに）記録させ、`source: checkpoint` の task として手動保存するコマンド。長くなったセッションの途中で「ここまでを残してから続きをやる」のような区切りに使う。

挙動:

- Python で `python/checkpoint.py "<title>"` を呼び、task ディレクトリを作成して採番済みパスと **このプロジェクトの直前タスク情報** (auto/manual 問わず最大 index のもの) を受け取る。スクリプトが plan.md / task.md の雛形まで書き込むので、Claude はそのあと plan.md を詳細内容で上書きする
- 直前 checkpoint がある場合は、Claude がその `plan.md` を Read して内容を把握し、**「以降 → 今」までの差分を詳細に** 新しい `plan.md` に書き出す
- 直前 checkpoint が無い場合は、セッション最初から現時点までの全内容を対象に書き出す
- 続けて Write ツールで `task.md` を書く（frontmatter に `prev_checkpoint_taskid` が入って連鎖する）
- `plan.md` が閾値行数を超えていれば `python/maybe_spawn_summary.py` 経由で `summary.md` を非同期生成（短ければスキップ）
- taskId のスラグ部分は Claude が会話内容から短いタイトルを自分で決めて付ける（ユーザの追加引数は不要）

「詳細に」とは具体的に、採用方針・却下案・触ったファイル・コミット・走らせたコマンド・未解決の課題・トレードオフ・参考情報まで漏らさず残すこと。短くまとめようとせず、**後でこの plan.md だけ読めば作業を完全に再開できる** 情報量を目指す。

セッション検出: `~/.jtfrom9-cc-workflow/state/<sid>/` の中で mtime が一番新しいサブディレクトリを「現在のセッション」とみなす（UserPromptSubmit フック群が毎ターン触っているため信頼性は実用十分）。

実体:
- コマンド: [`commands/checkpoint.md`](commands/checkpoint.md)
- ヘルパー: [`python/checkpoint.py`](python/checkpoint.py)（自動採取と同じスクリプト、引数にタイトルを渡す）

### `/jtfrom9-cc-workflow:summarise`: 今開いている task の summary.md を再生成

引数は取らない。現在のセッションで「開いている」task の `summary.md` を非同期で再生成する。

「開いている task」とは、以下のいずれかで最後に記録された taskId のこと:

- `/jtfrom9-cc-workflow:restore <taskId>` を実行した
- `/jtfrom9-cc-workflow:checkpoint` で新規 task を作った
- プランモードで承認した plan が `relocate_plan` 経由で task になった

これらの操作で `~/.jtfrom9-cc-workflow/state/<sid>/open_task_id` が更新される。
`summarise` は同じファイルを読み、対象 plan.md に対して `_summarize_worker.py` を spawn する。

open task が無い場合（restore 等まだ何も操作していない場合）は、その旨と `/jtfrom9-cc-workflow:restore` の案内が表示される。

ユースケース:

- 自動生成された `summary.md` の出来が悪い、もしくは失敗していた → これで撃ち直す
- plan.md を手動編集した後に要約を更新したい
- 後から要約だけ欲しくなった

失敗時の `summary.md` には例外名・終了コード・stderr 等の診断情報が書き込まれるので、再生成前にそこから原因を確認できる。

実体:
- コマンド: [`commands/summarise.md`](commands/summarise.md)
- ヘルパー: [`python/regenerate_summary.py`](python/regenerate_summary.py)
- open task の記録: [`python/mark_task_open.py`](python/mark_task_open.py) (`/restore` から呼ばれる) + 各 task 作成ヘルパー

### `/jtfrom9-cc-workflow:tasks`: task 一覧表示

現在のプロジェクトの全 task を表で表示する。`taskId` / 作成日時 / `source` / `status` がわかる。
選んだ task を別セッションで読み戻したい場合は、ユーザ自身で `/clear` してから `/jtfrom9-cc-workflow:restore <taskId>` を実行する。

(Claude Code のカスタムスラッシュコマンドは別のスラッシュコマンドを自動実行できない仕様のため、`/clear` と `/restore` の連鎖は提供しない。)

実体:
- コマンド: [`commands/tasks.md`](commands/tasks.md)
- ヘルパー: [`scripts/list-tasks.sh`](scripts/list-tasks.sh)

### `/jtfrom9-cc-workflow:restore <taskId>`: 保存済みプランの復元

引数の taskId に対応する保存済みプランをコンテキストに読み込み、その続きから作業を再開するためのスラッシュコマンド。
（プラグインのコマンドは常に `<plugin-name>:<command>` 形式で名前空間化されるため、フルネームで呼ぶ。）

挙動:
- 現在のプロジェクト名（Claude Code セッションの cwd のベース名）を判定
- `~/.jtfrom9-cc-workflow/tasks/<project>/<taskId>/` 配下の `task.md` / `plan.md` / `summary.md` を読み出してプロンプトに展開
- Claude はその内容を踏まえて、ユーザの次の指示を待つ

エラー時の挙動:
- 引数なし → 使い方を返し、当該プロジェクトの taskId 一覧を表示
- 該当 taskId が見つからない → エラー + 一覧を表示

実体:
- コマンド: [`commands/restore.md`](commands/restore.md)
- ヘルパー: [`scripts/restore-task.sh`](scripts/restore-task.sh)

## 設計方針

- **小さく単機能**: 1 フック = 1 スクリプト = 1 関心事
- **依存最小**: bash と `jq` だけで動かす
- **副作用最小**: 状態は `~/.jtfrom9-cc-workflow/state/` 配下のファイルのみ
- **黙って動く**: 提案や警告は **1 度だけ** 出す。連発しない
- **オプトイン**: プラグインを有効化した時だけ動く

## 動作要件

- Claude Code CLI
- **Python 3.9+**: 複雑なフック (`python/relocate_plan.py` / `checkpoint.py` ほか) は Python。標準ライブラリのみ依存
- **bash**: シンプルなフック (`hooks/*.sh`) と一覧／復元ヘルパー (`scripts/*.sh`) は bash。`jq` も依存
- 動作環境別:
  - **macOS / Linux**: bash・python3 ともに通常標準で入っている
  - **Windows**: Git for Windows (Git Bash) + Python 3 をインストールしておく必要あり。`plugin.json` のフックは `command: "bash"` / `command: "python3"` の args 形式で起動するため、シェル種別の違いを吸収できる

## マニフェストの検証

開発中に手で書き換えた場合:

```sh
claude plugin validate .
```

## 状態のクリーンアップ

`~/.jtfrom9-cc-workflow/state/<session-id>/` は session 終了後も残るので、定期的に古いものを掃除したい場合:

```sh
find ~/.jtfrom9-cc-workflow/state -mindepth 1 -maxdepth 1 -type d -mtime +30 -exec rm -rf {} +
```

将来 `SessionEnd` フックで自動掃除するスクリプトを追加するかもしれない。

## 今後の追加候補

- `branch-watcher`: ブランチを跨いだ作業に気付かせる
- `context-pressure`: 圧縮直前に `PreCompact` で重要情報を保存させる
- `long-session-warn`: セッションが N 時間 / N ターンを超えたら警告

## 既知の制限

- プラグインは Claude Code のトップレベル設定（`plansDirectory` など）を上書きできない。プランファイルの整理は事後移動（`relocate-plan`）で対応している。
