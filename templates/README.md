# テンプレート設定ファイル

エージェントツール側で機密ファイルアクセスを制限するための設定テンプレート。

Agent Harnessのネットワーク隔離（読めても送れない）に加えて、ツール側の設定で多層防御を実現する。

## 防御の層

| 層 | 防御内容 | 対象モード |
|---|---|---|
| **permissions.deny** | Read/Edit toolでの直接読み取りを拒否 | ホストモード |
| **ネットワーク隔離** | 読めても許可ドメイン以外に送れない | 両モード |
| **マウント制限** | そもそもコンテナに機密ファイルを入れない | コンテナモード |
| **payload_rules** | リクエスト内の機密パターンを検知・ブロック | 両モード |
| **alerts** | Bash経由の間接アクセスを事後検知 | 両モード |

## 注意事項

### permissions.deny の限界

`permissions.deny` は Claude Code の内部ツール（Read, Edit）を制限するが、**Bash 経由の `cat .env` は防げない**。Bash経由のアクセスは:
- ネットワーク隔離で「送れない」
- `payload_rules.secret_patterns` で送信前にパターン検知
- `alerts.suspicious_args` で事後検知

### コンテナモードでは settings.json は無効

`--dangerously-skip-permissions` を使用するため、settings.json の permissions/sandbox 設定は全て無視される。コンテナ自体がサンドボックスであり、以下で保護する:
- 機密ファイルをworkspaceにマウントしない
- アプリの実行に必要なAPIキーやDB接続文字列は環境変数で渡す（アプリが動かないと開発できない）
- ネットワーク隔離 + payload_rules で保護する

### LLM API への送信について

`api.anthropic.com` や `api.openai.com` への通信を許可している場合、エージェントが読んだ内容は会話コンテキストとしてそのプロバイダに送信される。これは「読めても送れない」の**例外ケース**。

- API経由のデータはモデルの学習には使用されない（Anthropic公式ポリシー）
- 不正利用監視のため最大30日間保持される
- `payload_rules.secret_patterns` で既知の機密パターンは送信前にブロック
- 完全な防止は原理的に不可能。ワークスペースに置くデータ量を最小化するのが根本対策

### printenv / 環境変数の漏洩

コンテナ内で `printenv` や `/proc/1/environ` で環境変数は読めてしまう。アプリ実行に必要なAPIキー等を環境変数で渡す以上、これは避けられない。

**ネットワーク隔離が防御の本質。** 読めても許可先以外に送れない。`payload_rules.secret_patterns` に自前のAPIキーパターンを追加しておけば、LLM APIへの送信もブロックできる。

## 使い方

### Claude Code（ホストモード）

```bash
# settings.json をプロジェクトの .claude/ にコピー
cp templates/claude-code/settings.json .claude/settings.json
```

### Codex CLI（ホストモード）

```bash
# config.toml をプロジェクトの .codex/ にコピー
mkdir -p .codex
cp templates/codex-cli/config.toml .codex/config.toml
```

`approval_policy = "untrusted"` と `sandbox_mode = "workspace-write"` をベースに、
ホストモードでの安全寄り設定を用意している。既存設定がある場合は必要なキーだけマージする。

## 対応ツール

現在テンプレートが用意されているツール:
- Claude Code (`templates/claude-code/settings.json`)
- Codex CLI (`templates/codex-cli/config.toml`)

今後追加予定:
- Aider
- Cline
