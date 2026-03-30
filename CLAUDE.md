# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## プロジェクト概要

AIコーディングエージェント（Claude Code, Codex CLI, Aider, Cline等）を安全に自律実行するためのセキュリティハーネス。Docker Compose隔離 + mitmproxyペイロード検査 + TOMLポリシー制御をエージェント非依存で提供する。

設計ドキュメント: `agent-harness-design.md`

## アーキテクチャ

2モード構成:
- **コンテナモード**: Docker `internal: true` ネットワークでエージェントを隔離。mitmproxyサイドカーが唯一の外部通信経路。`--dangerously-skip-permissions` + `cap_drop: [ALL]`
- **ホストモード**: ネイティブClaude Code → srt customProxy → localhost mitmproxy。Seatbeltサンドボックス有効

核心コンポーネント:
- `policy.toml` — ドメイン制御、レート制限、ペイロード検査ルール（両モード共通）
- `addons/policy_enforcer.py` — mitmproxyアドオン。request()フックでドメイン制御/レート制限、SSEストリーミング対応のtool_use検出
- `data/harness.db` — SQLite（WALモード）。requests, tool_uses, blocks, alertsテーブル

## 開発コマンド

```bash
make certs          # mitmproxy CA証明書の事前生成
make build          # certsを含むDockerイメージビルド
make run            # コンテナモードで対話実行
make task PROMPT="..." # コンテナモードで自律実行
make unit           # ユニットテスト（uv run pytest）
make test           # Dockerスモークテスト（許可/ブロック/直接アクセス不可+SQLiteログ確認）
make host           # ホストモードでmitmproxy起動
make host-stop      # ホストモード停止
make analyze        # ブロックログ → policy.toml改善提案
make summarize      # tool_use履歴 → ホストモード最小権限提案
make alerts         # アラート履歴の分析
make down           # コンテナ停止
```

## 実装状態

Phase 1-3 実装済み。ユニットテスト82件、Dockerスモークテスト。

実装済み機能:
- ドメイン制御（allow/deny、ワイルドカード、case-insensitive、ホットリロード）
- レート制限（RPM + burstの2段階ウィンドウ）
- ペイロード検査（block_patterns + secret_patterns）
- SSEストリーミングtool_useキャプチャ（ステートマシン、チャンク境界対応）
- アラート機能（suspicious_tools/args、tool_arg_size_alert）
- ホストモード（setup.sh/stop.sh）
- CLI分析（make analyze/summarize/alerts）
- CoreDNS strictモード（DNS漏洩対策）
- ダッシュボード（Flask + HTMX、ログ閲覧、ホワイトリスト育成）
- ポリシー編集（atomic write、allow/dismiss/restore API）

## 重要な設計判断

- Dockerfile: **Alpine Linux禁止**（musl libc互換性でClaude Codeがクラッシュする）。node:20-slim を使う
- 証明書: Dockerfile内COPYではなく**ランタイムボリュームマウント** + `NODE_EXTRA_CA_CERTS` + `SSL_CERT_FILE` 環境変数。`NODE_TLS_REJECT_UNAUTHORIZED=0` は絶対使わない
- SSEストリーミング: ドメイン制御/レート制限は `request()` フックで完結。tool_use検出はSSEチャンクのステートマシン解析が必要（Phase 2）
- ポリシー書き換え: atomic write（tmpfile + rename）でmitmproxyホットリロードとの競合防止
- ダッシュボード: `127.0.0.1` バインド、データは読み取り専用マウント
