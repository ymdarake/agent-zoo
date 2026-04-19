# ポリシーリファレンス

> 日本語 | [English](policy-reference.en.md)

`policy.toml`の全設定項目。ホストモードではファイル保存で即反映。コンテナモードでは`zoo reload`が必要。

ダッシュボードからの操作は`policy.runtime.toml`に書き込まれ、base設定のコメントは保持される。

## 初期プロファイル (`zoo init --policy`)

`zoo init` の時点で選択される初期ポリシー。default = `minimal` (secure by default、空 allow list)。

| profile | 想定 |
|---|---|
| `minimal` (default) | 空 allow list。全通信が Inbox 経由で都度承認 |
| `claude` | Anthropic / Claude 系のみ許可 (Claude Code 用) |
| `codex` | OpenAI / ChatGPT 系のみ許可 (Codex CLI 用) |
| `gemini` | Google AI 系のみ許可 (Gemini CLI 用) |
| `all` | 全 provider 許可 (0.1 以前の default 相当) |

profile 間で差分があるのは `domains.allow.list` / `paths.allow` / `rate_limits` の 3 セクションのみ。`payload_rules` / `tool_use_rules` / `alerts` / `domains.deny` / `general` は全 profile で完全一致。

切替: `zoo init --policy <profile> --force` で `.zoo/policy.toml` を再生成。

---

## [general]

```toml
[general]
log_db = "/data/harness.db"           # SQLiteログの保存先
max_tool_input_store = 1000           # tool_usesテーブルに保存するinputの最大文字数（0=無制限）
log_retention_days = 30               # 起動時に古いレコードを自動削除（0=無制限）
```

## [domains.allow]

```toml
[domains.allow]
list = ["api.anthropic.com"]
```

通信を許可するドメイン。**ここにないドメインは全てブロック**（デフォルト全拒否）。

ワイルドカード対応: `*.example.com`はexample.com自体とサブドメインの両方にマッチ。

## [domains.deny]

```toml
[domains.deny]
list = ["*.evil.com"]
```

allowより優先して拒否。allowのワイルドカードから例外除外する用途。デフォルト全拒否なので通常は空でよい。

## [domains.dismissed]

```toml
[domains.dismissed]
"http-intake.logs.us5.datadoghq.com" = { reason = "不要", date = "2026-03-31" }
```

ダッシュボードで「無視」したドメイン。ホワイトリスト育成の候補から除外。

## [paths.allow]

```toml
[paths.allow]
"raw.githubusercontent.com" = ["/anthropics/*"]
"registry.npmjs.org" = ["/@anthropic-ai/*", "/playwright", "/playwright/*"]
```

ドメインが`domains.allow`になくても、特定パスだけ許可。glob対応。URLデコード後にマッチング。

## [paths.deny]

```toml
[paths.deny]
"api.anthropic.com" = ["/v1/files*"]
```

ドメインが`domains.allow`にあっても、特定パスはブロック。

## [rate_limits]

```toml
[rate_limits]
"api.anthropic.com" = { rpm = 120, burst = 50 }
```

ドメイン別のレート制限。2段階ウィンドウ:
- `rpm`: 60秒間の上限
- `burst`: 1秒間の上限

超過時は429 Retry-Afterレスポンスを返す。

## [payload_rules]

```toml
[payload_rules]
block_patterns = []
secret_patterns = [
    "AWS_SECRET_ACCESS_KEY",
    "ANTHROPIC_API_KEY",
    "-----BEGIN.*PRIVATE KEY-----",
]
```

エージェント→API送信時のリクエストボディを検査。

- `block_patterns`: 正規表現でマッチしたらブロック
- `secret_patterns`: 正規表現（case-insensitive）でマッチしたらブロック

Base64/URLデコード後に再検査する（1段階のみ）。

## [tool_use_rules]

```toml
[tool_use_rules]
block_tools = []
block_args = ["rm -rf /", "chmod 777", "printenv", "/etc/shadow"]
```

APIレスポンス内のtool_useを検査。マッチしたらレスポンスを403に差し替え。

- `block_tools`: ツール名の完全一致でブロック
- `block_args`: 引数のワード境界マッチでブロック

> ⚠ **重要な制約**: `block_args` は文字列パターンマッチの性質上、本質的に bypass 可能性があります。LLM が生成するコマンドの完全な危険パターン検知は困難です。**最終的な防御はネットワーク隔離**（外部 API 経由でしか破壊操作できない状態を保つこと）であり、`block_args` は補助的な早期検知として位置づけてください。具体的にどのような変形が通るかの議論は `docs/dev/security-notes.md` にあります。

### 組み合わせ条件

```toml
[[tool_use_rules.rules]]
name = "Bash accessing secrets"
tools = ["Bash"]
args = ["~/.ssh", "~/.aws", ".env"]

[[tool_use_rules.rules]]
name = "Large write"
tools = ["Write", "Edit"]
min_size = 50000
```

ルール内はAND、ルール間はOR。
- `tools`: いずれかのツール名にマッチ（省略=全ツール対象）
- `args`: いずれかのパターンにワード境界マッチ（省略=引数条件なし）
- `min_size`: 引数サイズ超過（省略=サイズ条件なし）

## [alerts]

```toml
[alerts]
suspicious_tools = []
suspicious_args = ["~/.ssh", "~/.aws", ".env", "id_rsa"]
```

tool_use検出時にアラートを生成。**ログのみ、ブロックはしない。**

- `suspicious_tools`: このツール名の全使用をログ（デバッグ用、通常は空）
- `suspicious_args`: ワード境界マッチでアラート

### 組み合わせ条件

```toml
[[alerts.rules]]
name = "Bash accessing secrets"
tools = ["Bash"]
args = ["~/.ssh", "~/.aws"]

[[alerts.rules]]
name = "Large file operation"
tools = ["Write", "Edit"]
min_size = 50000
```

`tool_use_rules.rules`と同じ構造。アラート→ブロックの切り替えはセクション名を変えるだけ。

## 環境変数

| 変数 | デフォルト | 説明 |
|---|---|---|
| `POLICY_LOCK_DIR` | `/locks` | `policy.runtime.toml` の cross-container shared/exclusive lock ファイルを置くディレクトリ。proxy / dashboard 双方から writable な共有 dir である必要がある (Sprint 006 PR F、TOCTOU M-8 対策)。`zoo init` が `.zoo/locks/` を生成し、docker-compose.yml が `./locks:/locks` を bind mount する。host-mode で proxy を動かす場合は writable な絶対パスを指定（未指定でも policy_path 同階層 → tempdir の順で fallback する）。`<dir>/<basename>.lock` の形式で lock file が作られる。 |
