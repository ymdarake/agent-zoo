<p align="center">
  <img src="logo.svg" alt="Agent Zoo" width="400">
</p>

# Agent Zoo

> 日本語 | [English](README.en.md)

[![CI](https://github.com/ymdarake/agent-zoo/actions/workflows/ci.yml/badge.svg)](https://github.com/ymdarake/agent-zoo/actions/workflows/ci.yml)

AIコーディングエージェントを安全に自律実行するためのセキュリティハーネス。

mitmproxyペイロード検査 + TOMLポリシー制御。エージェント非依存で動作。

## モード

- **スタンドアロン** — プロキシのみ起動（`zoo host start`）。ホスト上の任意のエージェントに適用可能
- **Docker Compose隔離** — `internal: true` ネットワークでエージェントを隔離。「読めても送れない」
  - 対応: Claude Code / Codex CLI / Gemini CLI（単体 + 全部入り unified イメージ）

## 特徴

- **ペイロード検査** — mitmproxyで通信を傍受・検査・ブロック（Base64デコード対応）
- **tool_use検知+ブロック** — エージェントの行動をリアルタイム抽出、危険な実行を阻止
- **ダッシュボード** — WebUIでリアルタイム監視 + ホワイトリスト育成
- **箱庭運用** — 全遮断→ログ分析→段階的に許可のサイクルをAI支援で回す

## クイックスタート

```bash
# 1. インストール（PyPI 公開後）
uv tool install agent-zoo
# もしくは git 経由
uv tool install git+https://github.com/ymdarake/agent-zoo

# 2. workspace を初期化（任意のディレクトリで）
mkdir my-zoo && cd my-zoo
zoo init                      # ./.zoo/ に harness 一式 + ./.gitignore を生成

# 3. イメージをビルド
zoo build                     # base + claude (デフォルト)。--agent codex/gemini 等

# 4. 起動
zoo run                       # Claude Code 対話モード（初回は /login 必要）
zoo run --agent codex         # Codex CLI（初回は codex login）
zoo run --agent gemini        # Gemini CLI（初回は OAuth or GEMINI_API_KEY）

# 自律実行モード（token 必須）
CLAUDE_CODE_OAUTH_TOKEN=xxx zoo task -p "テストを追加して"
OPENAI_API_KEY=xxx zoo task --agent codex -p "テストを追加して"
GEMINI_API_KEY=xxx zoo task --agent gemini -p "テストを追加して"

# ダッシュボード: http://localhost:8080
```

詳細は [docs/user/install-from-package.md](docs/user/install-from-package.md) を参照。

## コマンド

`zoo` CLI で全機能カバー。詳細は `zoo --help` / `zoo <cmd> --help`。

| 操作 | コマンド |
|---|---|
| 対話モード | `zoo run [-a claude\|codex\|gemini]` |
| 箱庭モード（承認なし） | `zoo run --dangerous` |
| 自律実行（非対話） | `zoo task -p "..." [-a ...]` |
| コンテナ内 bash | `zoo bash [-a ...]` |
| host CLI を proxy 経由で実行 | `zoo proxy <agent> [args...]` |
| サービス起動のみ | `zoo up [--dashboard-only] [--strict]` |
| 停止 | `zoo down` |
| policy 反映 | `zoo reload` |
| イメージビルド | `zoo build [-a ...]` |
| CA 証明書生成 | `zoo certs` |
| ホストモード | `zoo host start` / `zoo host stop` |
| ログクリア | `zoo logs clear` |
| ログ分析 | `zoo logs analyze` / `summarize` / `alerts` |
| テスト | `zoo test unit` |

## ダッシュボード

`zoo up --dashboard-only` で起動（ http://localhost:8080 ）。

リクエスト・tool_use・ブロックをリアルタイム監視し、ホワイトリストを育成できる。

| Requests | Tool Uses | Inbox | Whitelist |
|---|---|---|---|
| ![Requests](docs/images/requests.png) | ![Tool Uses](docs/images/tool-uses.png) | _(ADR 0001)_ | ![Whitelist](docs/images/whitelist.png) |

**Inbox** ([使い方ガイド](docs/user/inbox.md)): エージェントが必要と判断した通信許可リクエストを human-in-the-loop で承認・反映する。

## ドキュメント

| ドキュメント | 内容 |
|---|---|
| [インストールとセットアップ](docs/user/install-from-package.md) | `uv tool install` → `zoo init` → `zoo run` の手順、`.zoo/` 配下構造 |
| [Inbox の使い方](docs/user/inbox.md) | agent からの許可リクエストを dashboard で承認するワークフロー |
| [セキュリティモデル](docs/user/security.md) | 多層防御、既知の制約、運用原則 |
| [ポリシーリファレンス](docs/user/policy-reference.md) | `policy.toml` の全設定項目 |

## Unified イメージ（cross-agent）

Claude から Gemini を呼ぶような cross-agent 利用には、`unified` profile（claude + codex + gemini を 1 コンテナに同梱）が使える。

```bash
cd <workspace>  # zoo init 済の dir
HOST_UID=$(id -u) docker compose -f .zoo/docker-compose.yml --profile unified up -d unified
docker compose -f .zoo/docker-compose.yml exec unified bash
# コンテナ内で claude / codex / gemini を任意に起動
```

イメージサイズは大きめ（3 CLI + 依存）。

## フィードバック / 開発者向け

- バグ報告・機能要望: [GitHub Issues](https://github.com/ymdarake/agent-zoo/issues)
- 内部設計・コントリビューション: [docs/dev/](docs/dev/)（アーキテクチャ / Python API / ADR / Sprint 履歴）

## ライセンス

MIT
