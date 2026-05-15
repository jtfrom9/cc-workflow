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
│   ├── banner.sh                    ←   SessionStart で名前表示
│   └── suggest-rename.sh            ←   UserPromptSubmit で /rename 提案
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
│   ├── save_prompt_as_task.py       ←   UserPromptSubmit: 分類器付きの task 採取
│   ├── relocate_plan.py             ←   PostToolUse(ExitPlanMode): plan ファイルを task 化
│   └── init_checkpoint.py           ←   checkpoint コマンドのヘルパー
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

#### task.md の frontmatter で出所を区別

`source:` フィールドで、task がどのフックから作られたかが分かる:

- `source: plan` — プランモードで承認された ExitPlanMode の plan を元に作られた (`python/relocate_plan.py`)
- `source: prompt` — プランモード外でユーザが直接送信した指示文から作られた (`python/save_prompt_as_task.py`)
- `source: checkpoint` — `/jtfrom9-cc-workflow:checkpoint` から手動で作られた (`python/init_checkpoint.py` + Claude が要約を Write)

同じセッションで両方発火すると、論理上 1 つのタスクに対して task フォルダが 2 つ並ぶことがある。重複は許容する設計で、不要な方は手動で削除する。

`~/.jtfrom9-cc-workflow/` 配下は実行時に自動で作られる。壊れても消しても良い。

## 機能

### banner: 起動確認バナー

`SessionStart` フックで `systemMessage` に `jtfrom9-cc-workflow` を表示する。プラグインが正しく有効化されていることを起動時に確認するためのもの。

スクリプト: [`hooks/banner.sh`](hooks/banner.sh)

### suggest-rename: セッション名付け忘れ防止

長めの指示が一定回数続いたところで `/rename` を促す。

- 仕掛け: `UserPromptSubmit` フック
- 判定: ユーザ入力が一定長 (デフォルト 100 字) を超えたものを「大きな指示」としてカウント
- 4 回目で 1 度だけ `systemMessage` で `/rename` を提案
- 既に `/rename` を叩いていれば以後追跡しない
- 1 セッション中 1 度提案したら以降は黙る

スクリプト: [`hooks/suggest-rename.sh`](hooks/suggest-rename.sh)

環境変数で閾値を調整できる:

| 変数 | デフォルト | 意味 |
|---|---|---|
| `JTFROM9_CC_WORKFLOW_RENAME_THRESHOLD_CHARS` | `100` | 「大きな指示」と見なす最小文字数 |
| `JTFROM9_CC_WORKFLOW_RENAME_THRESHOLD_COUNT` | `4` | 何回続いたら提案するか |
| `JTFROM9_CC_WORKFLOW_DIR` | `$HOME/.jtfrom9-cc-workflow` | 実行時データ置き場のルート |

### save-prompt-as-task: プランモードを忘れた指示も内容で判定して自動 task 化

プランモードに入らずに指示を送信した場合でも、その内容が「一定規模のコード変更要求」であれば task として保存する。`relocate-plan` の補完的な役割。

判定はバックグラウンドで Haiku に YES/NO で分類させる。フック自体は即時 return するので、ユーザ体感の遅延はない。task が出来上がるのは分類が終わった数秒〜十数秒後。

処理フロー:

```
UserPromptSubmit
 → python/save_prompt_as_task.py
     早期 exit:
       - スラッシュコマンド (/ で始まる) → スキップ
       - MIN_LEN_FOR_CLASSIFY 未満の文字数 → スキップ
       - 前回プロンプトと完全一致 (state/<sid>/last_prompt_hash) → スキップ
     バックグラウンド処理:
       - claude -p --model haiku で YES/NO 分類
       - YES なら task フォルダ作成 (plan.md = 原文プロンプト, task.md, summary.md は長文時のみ)
       - NO なら何もしない
```

`task.md` の `source: prompt` で他のタスクと区別できる。判定結果は `classifier_decision` フィールドにも残る。

スクリプト: [`python/save_prompt_as_task.py`](python/save_prompt_as_task.py)

| 変数 | デフォルト | 意味 |
|---|---|---|
| `JTFROM9_CC_WORKFLOW_SAVE_PROMPT_AS_TASK` | `1` | `0` で無効化 |
| `JTFROM9_CC_WORKFLOW_CLASSIFIER_MODEL` | `haiku` | 分類に使うモデル alias もしくはフル ID |
| `JTFROM9_CC_WORKFLOW_MIN_LEN_FOR_CLASSIFY` | `20` | これ未満は分類器に投げず即スキップ |
| `JTFROM9_CC_WORKFLOW_CLASSIFIER_INPUT_BYTES` | `2000` | 分類器に渡すプロンプト上限バイト数（トークン節約） |

#### 再帰防止

子 `claude -p` プロセスが同じ UserPromptSubmit フックを再帰発火しないよう、バックグラウンド処理開始時に環境変数 `_JTFROM9_CC_WORKFLOW_HOOK_RUNNING=1` を立てる。子プロセスでフックが呼ばれてもこの変数を見て即 exit する。

#### 制約

- 分類器はブレることがあるため、保守的に「不明なら NO」と判定するよう指示している
- それでも誤判定はあり得る。task が増え過ぎたら `JTFROM9_CC_WORKFLOW_SAVE_PROMPT_AS_TASK=0` で無効化するか、不要 task を手動削除する
- `claude -p` を呼ぶため Haiku の API トークンを少額消費する

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

- プロジェクト名: `git rev-parse --show-toplevel` のベース名、git 外なら `$PWD` のベース名
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

#### 制約

- フック入力には書かれたプランファイルのパスが含まれないため、`plansDirectory` 内の「直近最新の .md」をヒューリスティックで拾っている。
- 同一セッション内で複数プランを短時間に連続で承認した場合、競合する可能性がある。
- 要約生成 (`claude -p`) はバックグラウンドで走り、終わるとファイルが上書きされる。失敗するとプレースホルダのまま残ることがある。
- ユーザが `plansDirectory` を別のディレクトリに設定している場合は `JTFROM9_CC_WORKFLOW_SOURCE_PLANS` でそちらを指定する。

## カスタムコマンド

### `/jtfrom9-cc-workflow:checkpoint [スラグ]`: 明示的に議論を保存（インクリメンタル）

これまでの会話を Claude に **詳細に**（甘くまとめずに）記録させ、`source: checkpoint` の task として手動保存するコマンド。長くなったセッションの途中で「ここまでを残してから続きをやる」のような区切りに使う。

挙動:

- Python で [`python/init_checkpoint.py`](python/init_checkpoint.py) を呼び、task ディレクトリと採番済みパス、加えて **同一セッション内の直前 checkpoint 情報** を取得する
- 直前 checkpoint がある場合は、Claude がその `plan.md` を Read して内容を把握し、**「以降 → 今」までの差分を詳細に** 新しい `plan.md` に書き出す
- 直前 checkpoint が無い場合は、セッション最初から現時点までの全内容を対象に書き出す
- 続けて Write ツールで `task.md` を書く（frontmatter に `prev_checkpoint_taskid` が入って連鎖する）
- `plan.md` が閾値行数を超えていれば `python/maybe_spawn_summary.py` 経由で `summary.md` を非同期生成（短ければスキップ）
- 引数があれば taskId のスラグ部分にも反映 (省略時 "checkpoint")

「詳細に」とは具体的に、採用方針・却下案・触ったファイル・コミット・走らせたコマンド・未解決の課題・トレードオフ・参考情報まで漏らさず残すこと。短くまとめようとせず、**後でこの plan.md だけ読めば作業を完全に再開できる** 情報量を目指す。

セッション検出: `~/.jtfrom9-cc-workflow/state/<sid>/` の中で mtime が一番新しいサブディレクトリを「現在のセッション」とみなす（UserPromptSubmit フック群が毎ターン触っているため信頼性は実用十分）。

実体:
- コマンド: [`commands/checkpoint.md`](commands/checkpoint.md)
- ヘルパー: [`python/init_checkpoint.py`](python/init_checkpoint.py)

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
- 現在のプロジェクト名（git ルート or cwd のベース名）を判定
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
- **Python 3.9+**: 複雑なフック (`python/save_prompt_as_task.py` / `relocate_plan.py` / `init_checkpoint.py`) は Python。標準ライブラリのみ依存
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
