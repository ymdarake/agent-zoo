<p align="center">
  <img src="logo.svg" alt="Agent Zoo" width="400">
</p>

# Agent Zoo

> [日本語](README.ja.md) | English

[![CI](https://github.com/ymdarake/agent-zoo/actions/workflows/ci.yml/badge.svg)](https://github.com/ymdarake/agent-zoo/actions/workflows/ci.yml)

A security harness that **isolates AI coding agents** (Claude Code / Codex CLI /
Gemini CLI) **inside Docker containers** and forces all outbound traffic
through mitmproxy. Payload inspection plus TOML policy control physically
prevent data exfiltration and dangerous command execution, without relying on
the agent's own trustworthiness.

## Quickstart

```bash
uv tool install agent-zoo            # install from PyPI
mkdir my-zoo && cd my-zoo
zoo init                             # lay out harness assets under ./.zoo/
zoo build                            # build the claude image (5-10 min)
zoo run                              # interactive mode (first run prompts /login)
```

When the agent makes an outbound request during `zoo run`, any domain absent
from `policy.toml`'s allow-list is rejected with 403. Live audit is available
through the dashboard (`zoo up --dashboard-only`, http://localhost:8080).

## Features

- **Docker isolation**: agent containers run on an `internal: true` network,
  cut off from the host OS and other containers; the only egress is the
  mitmproxy sidecar
- **Domain allow-list**: outbound destinations are explicitly enumerated in
  `policy.toml`, with hot reload support
- **Payload inspection**: request and response bodies are inspected (Base64
  decoding, secret patterns, URL-embedded secrets)
- **tool_use detection**: SSE streams are parsed and dangerous tool invocations
  are blocked at the request hook
- **Dashboard auditing**: requests / tool_uses / blocks shown live, with
  whitelist nurturing and Inbox (agent-to-human approval requests)
- **Agent-agnostic**: same harness covers Claude Code / Codex CLI / Gemini CLI;
  the unified image enables cross-agent invocation

## Documentation

| Doc | Contents |
|---|---|
| [Install & Setup](docs/user/install-from-package.md) | Detailed `uv tool install` → `zoo init` → `zoo run` flow, full command reference, unified profile |
| [Inbox guide (JP)](docs/user/inbox.md) | Approving agent-issued allow-list requests through the dashboard |
| [Security model](docs/user/security.md) | Defense in depth, known limitations, operating principles |
| [Policy reference](docs/user/policy-reference.md) | Every setting in `policy.toml` |

## License

MIT
