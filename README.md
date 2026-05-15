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
├── hooks/
│   ├── banner.sh                    ← SessionStart で名前表示
│   └── suggest-rename.sh            ← UserPromptSubmit で /rename 提案
└── README.md
```

実行時状態はホーム側に分離:

```
~/.jtfrom9-cc-workflow/
├── state/<session-id>/              ← セッション毎の sentinel
│   ├── count
│   ├── suggested
│   └── renamed
└── log/
```

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

## 設計方針

- **小さく単機能**: 1 フック = 1 スクリプト = 1 関心事
- **依存最小**: bash と `jq` だけで動かす
- **副作用最小**: 状態は `~/.jtfrom9-cc-workflow/state/` 配下のファイルのみ
- **黙って動く**: 提案や警告は **1 度だけ** 出す。連発しない
- **オプトイン**: プラグインを有効化した時だけ動く

## 動作要件

- macOS / Linux (bash, jq)
- Claude Code CLI

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
