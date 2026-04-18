# Policy Reference

> [日本語](policy-reference.md) | English

All settings in `policy.toml`. In host mode, file save is reflected immediately. In container mode, run `zoo reload` (or `cd bundle && make reload` for maintainers).

Operations from the dashboard are written to `policy.runtime.toml`; comments in the base config are preserved.

---

## [general]

```toml
[general]
log_db = "/data/harness.db"           # SQLite log destination
max_tool_input_store = 1000           # Max characters of input stored in the tool_uses table (0 = unlimited)
log_retention_days = 30               # Auto-delete old records on startup (0 = no auto-deletion)
```

## [domains.allow]

```toml
[domains.allow]
list = ["api.anthropic.com"]
```

Domains allowed to communicate. **Anything not listed here is blocked** (default-deny).

Wildcard supported: `*.example.com` matches both example.com and its subdomains.

## [domains.deny]

```toml
[domains.deny]
list = ["*.evil.com"]
```

Denied with priority over allow. Use to carve exceptions out of allow wildcards. Default-deny means this is usually empty.

## [domains.dismissed]

```toml
[domains.dismissed]
"http-intake.logs.us5.datadoghq.com" = { reason = "not needed", date = "2026-03-31" }
```

Domains "dismissed" via the dashboard. Excluded from whitelist nurturing candidates.

## [paths.allow]

```toml
[paths.allow]
"raw.githubusercontent.com" = ["/anthropics/*"]
"registry.npmjs.org" = ["/@anthropic-ai/*", "/playwright", "/playwright/*"]
```

Allow specific paths even when the domain is not in `domains.allow`. Glob supported. Matched after URL-decoding.

## [paths.deny]

```toml
[paths.deny]
"api.anthropic.com" = ["/v1/files*"]
```

Block specific paths even when the domain is in `domains.allow`.

## [rate_limits]

```toml
[rate_limits]
"api.anthropic.com" = { rpm = 120, burst = 50 }
```

Per-domain rate limit. Two-window:
- `rpm`: limit over 60 seconds
- `burst`: limit over 1 second

On exceed: returns 429 with Retry-After.

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

Inspects the request body sent from the agent to the API.

- `block_patterns`: regex; block on match
- `secret_patterns`: regex (case-insensitive); block on match

Re-inspected after Base64 / URL decoding (one level deep).

## [tool_use_rules]

```toml
[tool_use_rules]
block_tools = []
block_args = ["rm -rf /", "chmod 777", "printenv", "/etc/shadow"]
```

Inspects tool_use in the API response. On match, the response is replaced with 403.

- `block_tools`: block on exact tool-name match
- `block_args`: block on word-boundary match against arguments

### Composite Conditions

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

Within a rule = AND, between rules = OR.
- `tools`: matches any of the tool names (omit = applies to all tools)
- `args`: word-boundary match against any of the patterns (omit = no arg condition)
- `min_size`: argument size threshold (omit = no size condition)

## [alerts]

```toml
[alerts]
suspicious_tools = []
suspicious_args = ["~/.ssh", "~/.aws", ".env", "id_rsa"]
```

Generate alerts on tool_use detection. **Logging only — does not block.**

- `suspicious_tools`: log every use of these tool names (debugging; usually empty)
- `suspicious_args`: alert on word-boundary match

### Composite Conditions

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

Same shape as `tool_use_rules.rules`. To upgrade an alert into a block, just change the section name.
