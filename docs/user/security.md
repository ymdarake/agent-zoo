# セキュリティモデル

> 日本語 | [English](security.en.md)

## 根本思想

**「読めても送れない」— ネットワーク隔離が防御の本質。**

エージェントはコンテナ内のファイルや環境変数を読むことができる。これを防ぐのではなく、読んだ情報を外部に送信できないようにネットワークレベルで制御する。

## 運用原則

- **コンテナは使い捨ての一時環境**。本番クレデンシャルは入れない
- **開発用のテストキーやローカルDB接続文字列**に留める
- **botサーバー等の常駐プロセス**にも利用可能（許可ドメインのみ通信可能な箱庭）

## 多層防御

| 層 | 防御 | 対象モード |
|---|---|---|
| `permissions.deny` | Read/Edit toolでの機密ファイル直接読み取りを拒否 | ホストモード |
| ネットワーク隔離 | 許可ドメイン以外への通信を全てブロック | 両モード |
| マウント制限 | 機密ファイルをコンテナに入れない | コンテナモード |
| `payload_rules` | リクエスト内の機密パターンを検知・ブロック（Base64デコード対応） | 両モード |
| `tool_use_rules` | 危険なtool実行をリアルタイムブロック（組み合わせ条件対応） | 両モード |
| `alerts` | 不審なアクセスパターンを事後検知 | 両モード |
| CoreDNS strict | DNS漏洩を遮断（オプション） | コンテナモード |

ホストモードでは以下のテンプレートを利用できる（`<workspace>/.zoo/templates/` 配下）:
- Claude Code: `templates/claude-code/settings.json` → `.claude/settings.json`
- Codex CLI: `templates/codex-cli/config.toml` → `.codex/config.toml`

## 箱庭運用

最初は全遮断で起動し、ログ分析とダッシュボードで必要な通信だけを段階的に許可する。

```
1. 全遮断で起動（必要最小限のLLM APIドメインのみ許可）
   ↓
2. エージェント/botが動き、ブロックログが溜まる
   ↓
3. `zoo logs analyze` → AIがpolicy.toml改善を提案
   ダッシュボード → Inbox / ブロック候補をワンクリック許可/無視
   ↓
4. policy.toml更新 → `zoo reload` で反映
   ↓
5. 繰り返し
```

## 既知の制約

### LLM APIへの送信

`api.anthropic.com` や `api.openai.com` への通信を許可している場合、会話コンテキストはそのプロバイダに送信される。

- API経由のデータはモデルの学習には使用されない（Anthropic公式ポリシー）
- 不正利用監視のため最大30日間保持
- `payload_rules.secret_patterns`で既知の機密パターンは送信前にブロック

### 環境変数の漏洩

コンテナ内で`printenv`や`/proc/1/environ`で環境変数は読めるが、ネットワーク隔離で許可先以外には送れない。`block_patterns`に`printenv`をデフォルト設定済み。

### Bash経由のアクセス

`permissions.deny`は内部ツール（Read/Edit）のみ制限。`cat .env`は防げない。ネットワーク隔離 + payload_rules で対応。

### DNS漏洩

HTTP/HTTPS通信はmitmproxy経由のためDNSクエリ自体が発生しないが、`ping`や`dig`等の非HTTPコマンドはDocker内蔵DNS経由で名前解決できる。`zoo up --strict`でCoreDNSを有効化し、許可ドメイン以外をNXDOMAINで遮断可能。
