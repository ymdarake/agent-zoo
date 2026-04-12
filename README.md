<p align="center">
  <img src="logo.svg" alt="Agent Zoo" width="400">
</p>

# Agent Zoo

AIコーディングエージェントを安全に自律実行するためのセキュリティハーネス。

mitmproxyペイロード検査 + TOMLポリシー制御。エージェント非依存で動作。

## モード

- **スタンドアロン** — プロキシのみ起動（`make host`）。ホスト上の任意のエージェントに適用可能
- **Docker Compose隔離** — `internal: true` ネットワークでエージェントを隔離。「読めても送れない」
  - 対応済み: Claude Code, Codex CLI

## 特徴

- **ペイロード検査** — mitmproxyで通信を傍受・検査・ブロック（Base64デコード対応）
- **tool_use検知+ブロック** — エージェントの行動をリアルタイム抽出、危険な実行を阻止
- **ダッシュボード** — WebUIでリアルタイム監視 + ホワイトリスト育成
- **箱庭運用** — 全遮断→ログ分析→段階的に許可のサイクルをAI支援で回す

## クイックスタート

```bash
git clone https://github.com/ymdarake/agent-zoo.git
cd agent-zoo

# `zoo` コマンドをインストール（uv 必須）
uv tool install .

# Claude Code: 対話モード（初回は /login 必要）
zoo run --workspace /path/to/my-project

# Codex CLI: 対話モード（初回は codex login 必要）
zoo run --agent codex --workspace /path/to/my-project

# 自律実行モード
CLAUDE_CODE_OAUTH_TOKEN=xxx zoo task -p "テストを追加して"
OPENAI_API_KEY=xxx zoo task --agent codex -p "テストを追加して"

# ダッシュボード: http://localhost:8080
```

`uv tool install` を使わない場合は `uv run zoo ...` でも実行できる。Makefile も引き続き利用可能（`make run` など）。

## コマンド

```bash
zoo run [-a claude|codex] [-w PATH] [--dangerous]   # 対話モード
zoo task -p "..." [-a claude|codex] [-w PATH]       # 自律実行（非対話）
zoo up [--dashboard-only] [--strict]                # 起動のみ（exec しない）
zoo down                                             # 停止
zoo reload                                           # policy.toml 反映
zoo build [-a claude|codex]                          # Docker イメージビルド
zoo certs                                            # CA 証明書生成
zoo host start | zoo host stop                       # ホストモード（Docker 不要）
zoo logs clear | analyze | summarize | alerts | candidates   # ログ操作
zoo test unit | zoo test smoke [-a claude|codex]     # テスト
```

`zoo --help` / `zoo <cmd> --help` で詳細。`make` も互換で残しています。

## ダッシュボード

`make up-dashboard` で起動（ http://localhost:8080 ）。

リクエスト・tool_use・ブロックをリアルタイム監視し、ホワイトリストを育成できる。

| Requests | Tool Uses | Whitelist |
|---|---|---|
| ![Requests](docs/images/requests.png) | ![Tool Uses](docs/images/tool-uses.png) | ![Whitelist](docs/images/whitelist.png) |

## ドキュメント

| ドキュメント | 内容 |
|---|---|
| [アーキテクチャ](docs/architecture.md) | コンポーネント、データフロー、内部設計 |
| [Codex統合ガイド](docs/codex-integration.md) | Codex CLI対応の構成と実装メモ |
| [セキュリティモデル](docs/security.md) | 多層防御、既知の制約、運用原則 |
| [ポリシーリファレンス](docs/policy-reference.md) | policy.toml全設定項目 |
| [ROADMAP](ROADMAP.md) | 未実装機能・将来計画 |

## ライセンス

MIT
