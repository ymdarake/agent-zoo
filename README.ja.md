<p align="center">
  <img src="logo.svg" alt="Agent Zoo" width="400">
</p>

# Agent Zoo

> 日本語 | [English](README.md)

[![CI](https://github.com/ymdarake/agent-zoo/actions/workflows/ci.yml/badge.svg)](https://github.com/ymdarake/agent-zoo/actions/workflows/ci.yml)

AI コーディングエージェント (Claude Code / Codex CLI / Gemini CLI) を
**Docker コンテナで隔離**し、外部通信を mitmproxy 経由のみに制限する
セキュリティハーネス。ペイロード検査 + TOML ポリシー制御で
情報持ち出し / 危険コマンド実行を、エージェントの信頼性に依存せず
物理的に制限する。

## クイックスタート

```bash
uv tool install agent-zoo            # PyPI からインストール
mkdir my-zoo && cd my-zoo
zoo init                             # ./.zoo/ にハーネス一式を展開
zoo build                            # claude イメージをビルド (5〜10 分)
zoo run                              # 対話モードで起動 (初回 /login)
```

`zoo run` 中にエージェントが外部 URL に通信すると、`policy.toml` の
許可リストに無いドメインは 403 で遮断される。ダッシュボード
(`zoo up --dashboard-only`、http://localhost:8080) でリアルタイムに監視できる。

## 特徴

- **Docker 隔離**: エージェントコンテナを `internal: true` のネットワーク上に置き、
  ホスト OS / 他コンテナから分離。外部通信は mitmproxy サイドカー 1 本に強制
- **ドメイン許可リスト**: 通信先を `policy.toml` で明示制限、動的リロード可
- **ペイロード検査**: リクエスト / レスポンスのボディを検査
  (Base64 復号 + 秘密情報パターン + URL 内シークレット)
- **tool_use 検知**: SSE ストリームを解析、危険な tool 実行をリクエストフックで遮断
- **ダッシュボード監査**: リクエスト / tool_use / 遮断ログをリアルタイム表示、
  ホワイトリスト育成 + Inbox (エージェントから人への許可申請) 対応
- **エージェント非依存**: Claude Code / Codex CLI / Gemini CLI に共通で適用、
  unified イメージでエージェント横断呼び出しも可

## ドキュメント

| ドキュメント | 内容 |
|---|---|
| [インストールとセットアップ](docs/user/install-from-package.md) | `uv tool install` → `zoo init` → `zoo run` の詳細手順、全コマンド一覧、unified プロファイル |
| [Inbox の使い方](docs/user/inbox.md) | エージェントからの許可リクエストをダッシュボードで承認する流れ |
| [セキュリティモデル](docs/user/security.md) | 多層防御、既知の制約、運用原則 |
| [ポリシーリファレンス](docs/user/policy-reference.md) | `policy.toml` の全設定項目 |

## ライセンス

MIT
