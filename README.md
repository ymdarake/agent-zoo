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
- **ホットリロード**: policy.toml更新で即座に反映
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
make certs          # mitmproxy CA証明書の事前生成
make build          # Dockerイメージビルド
make run            # 対話モード（Claude Codeが起動）
make task PROMPT="..." # 自律実行モード（--dangerously-skip-permissions）
make down           # コンテナ停止
```

### ホストモード
```bash
make host           # ホストモードでmitmproxy起動
make host-stop      # ホストモード停止
```

### テスト・分析
```bash
make unit           # ユニットテスト（60件）
make test           # Dockerスモークテスト
make analyze        # ブロックログ → policy.toml改善提案
make summarize      # tool_use履歴 → 最小権限settings.json提案
make alerts         # セキュリティアラートの分析
```

## ポリシー設定（policy.toml）

```toml
[domains.allow]
list = ["api.anthropic.com"]

[domains.deny]
list = ["*.evil.com"]

[rate_limits]
"api.anthropic.com" = { rpm = 30, burst = 5 }

[payload_rules]
block_patterns = ["rm -rf /", "chmod 777"]
secret_patterns = ["AWS_SECRET_ACCESS_KEY", "-----BEGIN.*PRIVATE KEY-----"]

[alerts]
suspicious_tools = ["Bash"]
suspicious_args = ["~/.ssh", "~/.aws", ".env"]
tool_arg_size_alert = 10000
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

### ホストモード
```
Claude Code → srt (customProxy) → mitmproxy (localhost:8080) → internet
```

## セキュリティモデル

- `api.anthropic.com` 以外への通信はデフォルトで**全てブロック**
- github.com、npmレジストリ等も非許可（exfiltration防止）
- コンテナモード: `cap_drop: [ALL]` + `internal: true` + mitmproxy
- ホストモード: Seatbelt sandbox + mitmproxy

## 開発

```bash
# Python 3.11+ が必要
uv sync --dev
uv run python -m pytest tests/ -v
```

## ライセンス

MIT
