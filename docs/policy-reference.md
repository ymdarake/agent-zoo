# ポリシーリファレンス

`policy.toml`の全設定項目。ホストモードではファイル保存で即反映。コンテナモードでは`make reload`が必要。

ダッシュボードからの操作は`policy.runtime.toml`に書き込まれ、base設定のコメントは保持される。

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
