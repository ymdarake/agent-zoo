# Agent Zoo ハーネス内での動作指示

このプロジェクトはAgent Zooセキュリティハーネス内で実行されています。

## ネットワーク制約

`/harness/policy.toml` を読んで、許可されている通信先を把握してください。
- `domains.allow.list` のドメインのみ通信可能
- `paths.allow` で特定パスのみ許可されているドメインがある
- それ以外は全てブロックされる

## 制約を超える作業が必要な場合

`/harness/policy_candidate.toml` に以下の形式で追記してください:

```toml
[[candidates]]
type = "domain"
value = "example.com"
reason = "npm installに必要"
```

パス単位の場合:
```toml
[[candidates]]
type = "path"
domain = "registry.npmjs.org"
value = "/some-package/*"
reason = "依存パッケージのインストール"
```

リクエストを書いた後、その作業はスキップして他のタスクを続けてください。

## tool_use制約

`/harness/policy.toml` の `[tool_use_rules]` も確認してください。
特定のツール使用やファイルアクセスがブロックされている場合があります。
