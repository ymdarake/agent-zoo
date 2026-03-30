# Agent Harness

AIコーディングエージェント（Claude Code, Codex CLI, Aider, Cline等）を安全に自律実行するためのセキュリティハーネス。

Docker Compose隔離 + mitmproxyペイロード検査 + TOMLポリシー制御をエージェント非依存で提供。

## 特徴

- **ネットワーク隔離**: Docker `internal: true` でエージェントの直接外部通信を遮断
- **完全ペイロード検査**: mitmproxyでHTTP/HTTPS通信を傍受・検査・ブロック
- **ドメイン制御**: allow/denyリスト + ワイルドカード対応
- **レート制限**: ドメイン別RPM + burstの2段階制御
- **ペイロード検査**: 危険コマンドパターン + 機密情報流出検知
- **tool_useキャプチャ**: SSEストリーミングからエージェントの行動をリアルタイム抽出
- **アラート**: 不審なツール使用・引数・データサイズの検知
- **ホットリロード**: policy.toml更新で即座に反映（再起動不要）
- **2モード**: コンテナモード（自律実行）+ ホストモード（対話開発）

## クイックスタート

```bash
# 1. クローン
git clone https://github.com/ymdarake/agent-zoo.git
cd agent-zoo

# 2. 対話モードで起動
CLAUDE_CODE_OAUTH_TOKEN=xxx make run

# 3. 自律実行モードで起動
CLAUDE_CODE_OAUTH_TOKEN=xxx make task PROMPT="このプロジェクトにテストを追加して"
```

## コマンド一覧

### コンテナモード

```bash
make certs            # mitmproxy CA証明書の事前生成
make build            # Dockerイメージビルド
make run              # 対話モード（Claude Codeが起動）
make task PROMPT="..."  # 自律実行モード（--dangerously-skip-permissions）
make down             # コンテナ停止
```

`run` / `task` は `CLAUDE_CODE_OAUTH_TOKEN` 環境変数が必須。

### ホストモード

```bash
make host             # mitmproxyをローカル起動（Docker不要）
make host-stop        # ホストモード停止
```

### オプションプロファイル

```bash
make up-dashboard     # ダッシュボード起動（http://localhost:8080）
make up-strict        # CoreDNS strictモード（DNS漏洩対策）
```

### テスト・分析

```bash
make unit             # ユニットテスト（82件）
make test             # Dockerスモークテスト
make analyze          # ブロックログ → policy.toml改善提案
make summarize        # tool_use履歴 → 最小権限settings.json提案
make alerts           # セキュリティアラートの分析
```

## ポリシー設定（policy.toml）

編集すると mitmproxy にホットリロードされる（再起動不要）。

```toml
[domains.allow]
# 通信を許可するドメイン。ここにないドメインは全てブロック
# ワイルドカード対応: "*.example.com" は example.com 自体とサブドメインの両方にマッチ
list = ["api.anthropic.com"]

[domains.deny]
# 明示的に拒否するドメイン。allow より優先
list = ["*.evil.com"]

[rate_limits]
# ドメイン別のレート制限。rpm=1分あたり上限、burst=1秒あたり上限
# 超過時は 429 Retry-After レスポンスを返す
"api.anthropic.com" = { rpm = 30, burst = 5 }

[payload_rules]
# リクエストボディに含まれていたらブロック（正規表現）
block_patterns = ["rm -rf /", "chmod 777", "base64.*\\|.*curl"]
# 機密情報の流出検知（正規表現、大文字小文字を区別しない）
secret_patterns = ["AWS_SECRET_ACCESS_KEY", "-----BEGIN.*PRIVATE KEY-----"]

[alerts]
# tool_use検出時にアラートを生成する条件（それぞれ独立、ログのみでブロックはしない）
suspicious_tools = []                                 # 全使用をログするツール（デバッグ用、通常は空）
suspicious_args = ["~/.ssh", "~/.aws", ".env"]        # 引数にこの文字列が含まれたらアラート
tool_arg_size_alert = 10000                           # 引数サイズ（バイト）超過でアラート
```

## アーキテクチャ

### コンテナモード

```
┌─── intnet (internal: true) ───┐     ┌─── extnet ───┐
│                               │     │              │
│  claude (エージェント)         │     │              │
│    ↓                          │     │              │
│  proxy (mitmproxy) ───────────┼─────┼→ internet    │
│                               │     │              │
└───────────────────────────────┘     └──────────────┘
```

エージェントはプロキシ経由でのみ外部通信可能。直接アクセスはネットワークレベルで遮断。

### ホストモード

```
Claude Code → srt (customProxy) → mitmproxy (localhost:8080) → internet
```

Docker不要の軽量モード。macOS Seatbeltサンドボックスと併用。

## セキュリティモデル

**根本思想: 「読めても送れない」— ネットワーク隔離が防御の本質。**

エージェントはコンテナ内のファイルや環境変数を読むことができる。これを防ぐのではなく、読んだ情報を外部に送信できないようにネットワークレベルで制御する。`api.anthropic.com` のみ許可し、それ以外への通信を全て遮断することで、データ漏洩の経路を塞ぐ。

- `api.anthropic.com` 以外への通信はデフォルトで**全てブロック**
- github.com、npmレジストリ等も非許可（exfiltration防止）
- コンテナモード: `cap_drop: [ALL]` + `internal: true` + mitmproxy
- ホストモード: Seatbelt sandbox + mitmproxy
- 認証: `CLAUDE_CODE_OAUTH_TOKEN` を毎回環境変数で渡す（コンテナに痕跡なし）
- workspace内に機密ファイル（`.env`等）を置かないことを推奨。環境変数で渡す
- HTTP/HTTPS通信はmitmproxy経由のためDNSクエリ自体が発生しないが、`ping`や`dig`等の非HTTPコマンドはDocker内蔵DNS経由で名前解決できてしまう（DNSトンネリングによる微量なデータ漏洩の余地）。これも防ぎたい場合は `make up-strict` でCoreDNSを有効化し、許可ドメイン以外をNXDOMAINで遮断できる

## 開発

```bash
# Python 3.11+ が必要
uv sync --dev
uv run python -m pytest tests/ -v
```

## ライセンス

MIT
