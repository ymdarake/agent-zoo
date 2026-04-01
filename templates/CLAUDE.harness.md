# Agent Zoo ハーネス内での動作指示

このプロジェクトはAgent Zooセキュリティハーネス内で実行されています。

## ネットワーク制約

`/harness/policy.toml` を読んで、許可されている通信先を把握してください。
- `domains.allow.list` に含まれるドメインのみ通信可能
- `paths.allow` で特定パスのみ許可されているドメインがある
- それ以外への通信は全てブロックされる

## 制約を超える作業が必要な場合

許可されていないドメインやパスへのアクセスが必要になった場合:
1. `/harness/policy_candidate.toml` にリクエストを追記してください
2. フォーマット:

```toml
[[candidates]]
type = "domain"  # or "path" or "tool"
domain = "example.com"
reason = "npm パッケージのインストールに必要"
priority = "high"
```

3. リクエストを書いた後、その作業はスキップして他のタスクを続けてください
4. 人間がリクエストを確認し、policy.tomlに反映します

## tool_use制約

`/harness/policy.toml` の `[tool_use_rules]` セクションも確認してください。
特定のツール使用やファイルアクセスがブロックされている場合があります。
