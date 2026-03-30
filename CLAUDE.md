# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## プロジェクト概要

AIコーディングエージェント（Claude Code, Codex CLI, Aider, Cline等）を安全に自律実行するためのセキュリティハーネス。Docker Compose隔離 + mitmproxyペイロード検査 + TOMLポリシー制御をエージェント非依存で提供する。

セキュリティの根本思想: **「読めても送れない」— ネットワーク隔離が防御の本質。**

設計ドキュメント: `agent-harness-design.md` / 未実装・将来計画: `ROADMAP.md`

## アーキテクチャ

2モード構成:
- **コンテナモード**: Docker `internal: true` ネットワークでエージェントを隔離。mitmproxyサイドカーが唯一の外部通信経路。`--dangerously-skip-permissions` + `cap_drop: [ALL]`
- **ホストモード**: ネイティブClaude Code → srt customProxy → localhost mitmproxy。Seatbeltサンドボックス有効

核心コンポーネント:
- `policy.toml` — ドメイン制御、レート制限、ペイロード検査ルール（両モード共通、ホットリロード対応）
- `addons/policy.py` — ポリシーエンジン（純粋ロジック、mitmproxy非依存）
- `addons/policy_enforcer.py` — mitmproxyアドオン。request()フックでドメイン制御/レート制限/ペイロード検査、SSEストリーミングtool_use検出
- `addons/sse_parser.py` — SSEステートマシン（mitmproxy非依存）
- `addons/policy_edit.py` — ポリシー編集・ホワイトリスト育成ロジック（mitmproxy非依存）
- `data/harness.db` — SQLite（WALモード）。requests, tool_uses, blocks, alertsテーブル

## 開発コマンド

```bash
# コンテナモード（CLAUDE_CODE_OAUTH_TOKEN 必須）
CLAUDE_CODE_OAUTH_TOKEN=xxx make run              # 対話実行
CLAUDE_CODE_OAUTH_TOKEN=xxx make task PROMPT="..." # 自律実行

# ホストモード
make host             # mitmproxyをローカル起動
make host-stop        # 停止

# オプションプロファイル
make up-dashboard     # ダッシュボード（http://localhost:8080）
make up-strict        # CoreDNS strictモード（DNS漏洩対策）

# テスト
make unit             # ユニットテスト（82件）
make test             # Dockerスモークテスト

# ビルド・管理
make certs            # mitmproxy CA証明書の事前生成
make build            # Dockerイメージビルド
make down             # コンテナ停止

# ログ分析（ホスト側Claude CLI利用）
make analyze          # ブロックログ → policy.toml改善提案
make summarize        # tool_use履歴 → ホストモード最小権限提案
make alerts           # アラート履歴の分析
```

## 実装状態

Phase 1-3 実装済み。ユニットテスト82件、Dockerスモークテスト。

## テスト実行ルール

- **pytestは必ず1プロセスだけフォアグラウンドで実行する。バックグラウンド実行禁止。**
- 前のテスト完了を確認してから次を実行する。多重実行するとロックテストでデッドロックする。

## 重要な設計判断

- Dockerfile: **Alpine Linux禁止**（musl libc互換性でClaude Codeがクラッシュする）。node:20-slim を使う
- 証明書: Dockerfile内COPYではなく**ランタイムボリュームマウント** + `NODE_EXTRA_CA_CERTS` + `SSL_CERT_FILE` 環境変数。`NODE_TLS_REJECT_UNAUTHORIZED=0` は絶対使わない
- 認証: `CLAUDE_CODE_OAUTH_TOKEN` を毎回環境変数で渡す。.envファイルは使わない
- SSEストリーミング: ドメイン制御/レート制限は `request()` フックで完結。tool_use検出はSSEチャンクのステートマシン解析
- ポリシー書き換え: atomic write（tmpfile + rename、Docker bind mountではフォールバック）
- ダッシュボード: `127.0.0.1` バインド、データは読み取り専用マウント
