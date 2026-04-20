# Agent Zoo ハーネス内での動作指示

このプロジェクトは Agent Zoo セキュリティハーネス内で実行されています。
あなたが Claude Code / Codex CLI / Gemini CLI のいずれであっても、
本ファイルの指示に従ってください。

## ネットワーク制約

`/harness/policy.toml` を読んで、許可されている通信先を把握してください。

- `domains.allow.list` のドメインのみ通信可能
- `paths.allow` で特定パスのみ許可されているドメインがある
- それ以外は全てブロックされる

## 制約を超える作業が必要な場合

`/harness/inbox/` ディレクトリに新規 TOML ファイルを作成して
**Policy Inbox Request** を出してください。

ファイル名は同名衝突を避けるため `<日時>-<任意ユニーク文字列>.toml` を推奨します
（例: `2026-04-18T10-23-45-myreq.toml`）。

例（domain 許可をリクエスト）:

```toml
schema_version = 1
created_at = "2026-04-18T10:23:45Z"
agent = "claude"   # codex / gemini も可
type = "domain"
value = "registry.npmjs.org"
reason = "npm install で依存解決のため"
status = "pending"
```

例（path 許可をリクエスト）:

```toml
schema_version = 1
created_at = "2026-04-18T10:23:45Z"
agent = "claude"
type = "path"
domain = "registry.npmjs.org"
value = "/some-package/*"
reason = "依存パッケージのインストール"
status = "pending"
```

リクエストを書いた後、その作業はスキップして他のタスクを続けてください。
人間が dashboard で承認すれば次回以降は許可されます。

## tool_use 制約

`/harness/policy.toml` の `[tool_use_rules]` も確認してください。
特定のツール使用やファイルアクセスがブロックされている場合があります。
