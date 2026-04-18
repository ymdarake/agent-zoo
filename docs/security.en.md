# Security Model

> [日本語](security.md) | English

## Core Philosophy

**"Read but can't send" — network isolation is the essence of defense.**

Agents can read files and environment variables inside the container. Rather than preventing this, we control at the network level so they cannot exfiltrate what they read.

## Operating Principles

- **Containers are disposable, ephemeral environments.** Do not put production credentials in.
- Use **dev test keys and local DB connection strings** only.
- Also usable for **bot servers and other long-running processes** (a sandbox where only allowed domains can talk).

## Defense in Depth

| Layer | Defense | Mode |
|---|---|---|
| `permissions.deny` | Reject Read/Edit-tool direct reads of sensitive files | Host |
| Network isolation | Block all traffic except allowed domains | Both |
| Mount restrictions | Don't mount sensitive files into containers | Container |
| `payload_rules` | Detect/block sensitive patterns in requests (Base64-decoded too) | Both |
| `tool_use_rules` | Real-time blocking of dangerous tool execution (composite-condition support) | Both |
| `alerts` | Post-hoc detection of suspicious access patterns | Both |
| CoreDNS strict | Block DNS leakage (optional) | Container |

For host mode, templates are available:
- Claude Code: `templates/claude-code/settings.json` → `.claude/settings.json`
- Codex CLI: `templates/codex-cli/config.toml` → `.codex/config.toml`

## Sandbox-Style Operation

Start fully blocked and gradually allow only the necessary traffic via log analysis and the dashboard.

```
1. Start with everything blocked (only minimal LLM API domains allowed)
   ↓
2. Agent / bot runs, block logs accumulate
   ↓
3. `make analyze` → AI suggests policy.toml improvements
   Dashboard → one-click allow/dismiss for block candidates
   ↓
4. Update policy.toml → reflect via `make reload`
   ↓
5. Repeat
```

## Known Constraints

### Sending to LLM APIs

If you allow communication to `api.anthropic.com` or `api.openai.com`, the conversation context is sent to that provider.

- Data through the API is not used for model training (Anthropic official policy).
- Retained up to 30 days for abuse monitoring.
- Known sensitive patterns are blocked before sending via `payload_rules.secret_patterns`.

### Environment Variable Leakage

`printenv` and `/proc/1/environ` can read env vars inside the container, but network isolation prevents exfiltration to non-allowed destinations. `printenv` is set in `block_patterns` by default.

### Access via Bash

`permissions.deny` only restricts internal tools (Read/Edit). `cat .env` is not blocked. Mitigated by network isolation + `payload_rules`.

### DNS Leakage

HTTP/HTTPS traffic goes through mitmproxy so DNS queries don't occur per request, but non-HTTP commands like `ping` / `dig` can still resolve via Docker's built-in DNS. Use `make up-strict` to enable CoreDNS, which NXDOMAINs non-allowed domains.
