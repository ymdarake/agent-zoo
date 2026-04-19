# インストールとセットアップ

`agent-zoo` はパッケージとしてインストールして使います（clone 不要）。

## インストール

```bash
# uv 推奨
uv tool install agent-zoo         # PyPI 公開後
uv tool install git+https://github.com/ymdarake/agent-zoo  # 現状はこちら
# pip も可
pip install agent-zoo
```

## セットアップ

任意のディレクトリで `zoo init` を実行すると、harness 一式が
**`<workspace>/.zoo/` 配下** に展開されます。作業ディレクトリは workspace 直下、
zoo の管理ファイルは `.zoo/` 配下に分離されるため、作業ディレクトリが散らかりません。

```bash
mkdir ~/my-zoo && cd ~/my-zoo
zoo init                             # default: --policy minimal (secure by default)
# zoo init --policy claude           # Anthropic / Claude 関連のみ allow
# zoo init --policy codex            # OpenAI / ChatGPT 関連のみ allow
# zoo init --policy gemini           # Google AI 関連のみ allow
# zoo init --policy all              # 全 provider allow (0.1 以前の default 相当)
zoo build                            # base + agent イメージをビルド
zoo run                              # 対話モードで claude を起動（初回は /login）
```

`--force` で既存ファイルを上書き、引数なしで `.` に展開されます。

### ポリシープロファイル (`--policy`)

`zoo init --policy <profile>` で初期の `.zoo/policy.toml` を選択できます。

| profile | `domains.allow.list` | 想定用途 |
|---|---|---|
| **minimal** (default) | 空 | secure by default。全通信を Inbox 経由で都度承認 |
| `claude` | `api.anthropic.com` / `claude.ai` / ... 6 domain | Claude Code 利用時 |
| `codex` | `api.openai.com` / `*.chatgpt.com` / ... 4 domain | Codex CLI 利用時 |
| `gemini` | `generativelanguage.googleapis.com` / ... 3 domain | Gemini CLI 利用時 |
| `all` | 上記全 13 domain | 全 provider 横断 (0.1 以前の default 相当) |

`paths.allow` / `rate_limits` は profile に応じて関連 domain 分のみ。
`payload_rules` / `tool_use_rules` / `alerts` / `domains.deny` / `general`
は全 profile で共通 (drift detection test 済み)。

後から profile を切り替えたい場合:

```bash
zoo init --policy claude --force     # 既存 policy.toml を上書き
```

`--force` 無しだと既存 `.zoo/policy.toml` は保持されます (CLI が yellow hint で明示)。

## ディレクトリ構成

```
~/my-zoo/                    # workspace root
├── .gitignore               # 生成: `.zoo/` 1 行で全 runtime artifact 除外
├── .zoo/                    # zoo 管理ファイル（普段触らない）
│   ├── docker-compose.yml
│   ├── docker-compose.strict.yml
│   ├── policy.toml          # 編集して独自ポリシーに（既存は尊重、先頭に profile コメント）
│   ├── policy/              # zoo init --policy で選択可能な 5 profile (minimal/claude/codex/gemini/all)
│   ├── policy.runtime.toml  # dashboard が書き込む runtime 状態
│   ├── addons/              # mitmproxy アドオン
│   ├── container/           # Agent 用 Dockerfile（claude/codex/gemini/unified）
│   ├── dashboard/           # 監視用 Flask アプリ
│   ├── dns/                 # strict モードの CoreDNS
│   ├── host/                # ホストモードのセットアップスクリプト
│   ├── templates/           # エージェント用 HARNESS_RULES.md 等
│   ├── certs/               # mitmproxy CA（zoo certs で生成）
│   ├── data/                # SQLite ログ保存先（harness.db）
│   └── inbox/               # agent からの policy 許可リクエスト
└── src/                     # 自分のコード（任意）
```

`zoo` CLI は CWD から `.zoo/docker-compose.yml` を walk-up で検出するため、
workspace root でもその配下のサブディレクトリでも、どこで `zoo` コマンドを
叩いても自動的に正しい `.zoo/` を解決します。

## Python API からも

```python
import zoo
zoo.init("~/my-zoo")   # 同じことをプログラムから
```

## 企業 proxy / 社内 root CA を信頼させる場合

社内 proxy が独自 root CA で TLS を終端しているような環境では、その CA cert を mitmproxy の信頼ストアに含める必要があります。

```bash
zoo certs import /etc/ssl/certs/company-ca.pem        # default 名でコピー
zoo certs import /path/to/ca.pem --name custom.pem    # リネーム
zoo certs import /path/to/ca.pem --force              # 既存を上書き
zoo certs list                                        # 現在の extra cert 一覧
zoo certs remove company-ca.pem                       # 削除
```

コピー先: `<workspace>/.zoo/certs/extra/`

> **重要**: import した cert を実際に使うには、base image の再構築が必要です:
>
> ```bash
> zoo build --no-cache
> ```
>
> `--no-cache` 無しだと Docker layer cache hit で `COPY certs/extra/` が再評価されず、新 cert が image に取り込まれません。

許容する file 名は `.pem` / `.crt` / `.cer` のみ。`.gitkeep` は保護対象 (削除/上書き不可)。
