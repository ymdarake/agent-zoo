<p align="center">
  <img src="logo.svg" alt="Agent Zoo" width="400">
</p>

# Agent Zoo

AIコーディングエージェント（Claude Code, Codex CLI, Aider, Cline等）を安全に自律実行するためのセキュリティハーネス。

Docker Compose隔離 + mitmproxyペイロード検査 + TOMLポリシー制御をエージェント非依存で提供。

## 特徴

- **エージェント非依存**: Claude Code, Codex CLI, Aider, Cline等どのツールでも動作。プロキシ層で制御するためエージェント側の改修不要
- **ネットワーク隔離**: Docker `internal: true` でエージェントの直接外部通信を遮断
- **完全ペイロード検査**: mitmproxyでHTTP/HTTPS通信を傍受・検査・ブロック（Base64デコード対応）
- **tool_use検知+ブロック**: SSEストリーミングからエージェントの行動をリアルタイム抽出。危険なtool実行はストリーム切断で阻止（現在はAnthropic API形式に対応。OpenAI形式は今後対応予定）
- **ダッシュボード**: リクエスト/ブロック/tool_use/アラートをWebUIでリアルタイム監視
- **ホワイトリスト育成**: ブロックログから許可候補を自動提案。ダッシュボードでワンクリック許可/無視。段階的にポリシーを育てる
- **AI支援ログ分析**: `make analyze`でブロックログをClaude CLIに食わせてポリシー改善提案を自動生成
- **ドメイン制御**: allow/denyリスト + ワイルドカード対応
- **レート制限**: ドメイン別RPM + burstの2段階制御
- **アラート**: 独立条件 + 組み合わせ条件（ルール内AND、ルール間OR）で柔軟に検知
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
make unit             # ユニットテスト（115件）
make test             # Dockerスモークテスト
make analyze          # ブロックログ → policy.toml改善提案
make summarize        # tool_use履歴 → 最小権限settings.json提案
make alerts           # セキュリティアラートの分析
make clear-logs       # ログDB削除（WAL/SHM含む）
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
# 送信内容から機密情報の流出を検知・ブロック
secret_patterns = ["AWS_SECRET_ACCESS_KEY", "-----BEGIN.*PRIVATE KEY-----"]

[tool_use_rules]
# 危険なツール実行をリアルタイムで阻止
block_args = ["rm -rf /", "chmod 777", "printenv", "/etc/shadow"]

[alerts]
# 独立条件（それぞれ単発で発火）
suspicious_args = ["~/.ssh", "~/.aws", ".env"]        # 引数にこの文字列が含まれたらアラート
tool_arg_size_alert = 10000                           # 引数サイズ（バイト）超過でアラート

# 組み合わせ条件（ルール内AND、ルール間OR）
[[alerts.rules]]
name = "Bash accessing secrets"
tools = ["Bash"]                                      # かつ
args = ["~/.ssh", "~/.aws"]                           # いずれかにマッチで発火
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

**原則: コンテナは使い捨ての一時環境として扱う。** 本番のクレデンシャルや漏洩すると致命的な情報は入れない。開発用のテストキーやローカルDB接続文字列に留め、本番環境の秘密情報はworkspaceの外で管理する。

**botサーバー等の常駐プロセスにも利用可能。** APIキーを含むbotサーバー（Slack bot等）の実行環境としても、ネットワーク隔離により最低限の箱庭を提供する。許可ドメイン（`api.anthropic.com` + botが接続する先）のみ通信可能にし、それ以外への漏洩を遮断できる。

### 箱庭運用: 段階的にポリシーを育てる

最初は全遮断で起動し、ログ分析とダッシュボードで必要な通信だけを段階的に許可していく。

```
1. 全遮断で起動（api.anthropic.comのみ許可）
   ↓
2. エージェント/botが動き、ブロックログが溜まる
   ↓
3. make analyze → Claude CLIがブロックログを分析し、policy.toml改善をTOML形式で提案
   make summarize → tool_use履歴から最小権限設定を提案
   ダッシュボード → ブロック候補をワンクリックで許可/無視
   ↓
4. policy.toml更新 → ホットリロードで即反映（再起動不要）
   ↓
5. 繰り返し（必要なものだけ開く、不要なものは閉じたまま）
```

この「deny by default → 観察 → 根拠付きで許可」のサイクルにより、安全マージンを取りながら運用できる。

### 多層防御

| 層 | 防御 | 対象モード |
|---|---|---|
| `permissions.deny` | Read/Edit toolでの機密ファイル直接読み取りを拒否 | ホストモード |
| ネットワーク隔離 | api.anthropic.com 以外への通信を全てブロック | 両モード |
| マウント制限 | 機密ファイルをコンテナに入れない | コンテナモード |
| `payload_rules` | リクエスト内の機密パターンを検知・ブロック（Base64デコード対応） | 両モード |
| `alerts` | Bash経由の間接アクセスを事後検知 | 両モード |
| CoreDNS strict | DNS漏洩を遮断（オプション） | コンテナモード |

ホストモードでは `templates/claude-code/settings.json` を `.claude/settings.json` にコピーして使用。

### 既知の制約

- **Anthropic APIへの送信**: 会話コンテキストはAnthropicに送信される（API経由のデータは学習に使用されない。不正利用監視のため最大30日間保持）
- **printenv**: コンテナ内で `printenv` で環境変数は読めるが、ネットワーク隔離で送れない。`secret_patterns`に自前のAPIキーパターンを追加推奨
- **Bash経由のアクセス**: `permissions.deny` は内部ツール(Read/Edit)のみ制限。`cat .env` は防げない。ネットワーク隔離+payload_rulesで対応

## 開発

```bash
# Python 3.11+ が必要
uv sync --dev
uv run python -m pytest tests/ -v
```

## ライセンス

MIT
