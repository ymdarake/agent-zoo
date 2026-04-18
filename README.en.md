<p align="center">
  <img src="logo.svg" alt="Agent Zoo" width="400">
</p>

# Agent Zoo

> [日本語](README.md) | English

A security harness for running AI coding agents autonomously and safely.

mitmproxy payload inspection + TOML policy control. Agent-agnostic.

## Modes

- **Standalone** — Proxy-only (`make host`). Works with any agent on the host.
- **Docker Compose isolation** — Agents are isolated on an `internal: true` network. *"They can read, but they can't send."*
  - Supported: Claude Code, Codex CLI, Gemini CLI (single + unified images, see #27)

## Features

- **Payload inspection** — Intercept, inspect, and block traffic via mitmproxy (Base64-decoded re-inspection too).
- **tool_use detection + blocking** — Real-time extraction of agent actions; block dangerous executions live.
- **Dashboard** — Web UI for live monitoring + whitelist nurturing + Policy Inbox approval.
- **Sandbox-style operation** — Block-all → analyze logs → gradually allow, with AI-assisted iteration.

## Quickstart

```bash
# 1. Install (after PyPI publish)
uv tool install agent-zoo
# or via git
uv tool install git+https://github.com/ymdarake/agent-zoo

# 2. Initialize a workspace anywhere
mkdir my-zoo && cd my-zoo
zoo init                      # creates ./.zoo/ harness + ./.gitignore

# 3. Build images
zoo build                     # base + claude (default). --agent codex/gemini etc.

# 4. Run
zoo run                       # Claude Code interactive (first time: /login)
zoo run --agent codex         # Codex CLI (first time: codex login)
zoo run --agent gemini        # Gemini CLI (first time: OAuth or GEMINI_API_KEY)

# Autonomous (token required)
CLAUDE_CODE_OAUTH_TOKEN=xxx zoo task -p "add tests"
OPENAI_API_KEY=xxx zoo task --agent codex -p "add tests"
GEMINI_API_KEY=xxx zoo task --agent gemini -p "add tests"

# Dashboard: http://localhost:8080
```

See [docs/user/install-from-package.md](docs/user/install-from-package.md) for details.

## Commands

The `zoo` CLI covers all features. `zoo --help` / `zoo <cmd> --help` for details.

| Operation | Command |
|---|---|
| Interactive | `zoo run [-a claude\|codex\|gemini]` |
| Sandbox (no approvals) | `zoo run --dangerous` |
| Autonomous (non-interactive) | `zoo task -p "..." [-a ...]` |
| Bash inside container | `zoo bash [-a ...]` |
| Wrap host CLI through proxy | `zoo proxy <agent> [args...]` |
| Bring services up only | `zoo up [--dashboard-only] [--strict]` |
| Stop | `zoo down` |
| Reload policy | `zoo reload` |
| Build images | `zoo build [-a ...]` |
| Generate CA cert | `zoo certs` |
| Host mode | `zoo host start` / `zoo host stop` |
| Clear logs | `zoo logs clear` |
| Log analysis | `zoo logs analyze` / `summarize` / `alerts` |
| Tests | `zoo test unit` |

> **Maintainer-only**: in the agent-zoo source repo (clone), `bundle/Makefile` is available via `cd bundle && make build` etc. See [ADR 0002 D7](docs/dev/adr/0002-dot-zoo-workspace-layout.md#d7-source-repo-bundle-と配布先-zoo-の命名分離).

## Dashboard

Run `zoo up --dashboard-only` and open http://localhost:8080.

Live monitor requests, tool_uses, and blocks; nurture your whitelist; review and approve agent-submitted Inbox requests.

| Requests | Tool Uses | Inbox | Whitelist |
|---|---|---|---|
| ![Requests](docs/images/requests.png) | ![Tool Uses](docs/images/tool-uses.png) | _(ADR 0001)_ | ![Whitelist](docs/images/whitelist.png) |

**Inbox** ([ADR 0001](docs/dev/adr/0001-policy-inbox.md)): the agent files allow-list requests it deems necessary; humans approve or reject them in the dashboard, and accepted ones flow into `policy.runtime.toml`.

## Documentation

### For users ([docs/user/](docs/user/))

| Document | Contents |
|---|---|
| [Install from package](docs/user/install-from-package.md) | `uv tool install` → `zoo init` → `zoo run` setup + `.zoo/` layout |
| [Security Model](docs/user/security.md) | Defense in depth, known constraints, operating principles (Japanese / EN) |
| [Policy Reference](docs/user/policy-reference.md) | All `policy.toml` settings (Japanese / EN) |

### For developers ([docs/dev/](docs/dev/))

| Document | Contents |
|---|---|
| [Architecture](docs/dev/architecture.md) | Components, data flow, internal design (Japanese / EN) |
| [Python API](docs/dev/python-api.md) | `zoo` library API for automation / notebook usage |
| [ADR 0001 Policy Inbox](docs/dev/adr/0001-policy-inbox.md) | Design rationale: file format, atomic writes, dedup, lifecycle |
| [ADR 0002 Workspace Layout](docs/dev/adr/0002-dot-zoo-workspace-layout.md) | source = `bundle/` / distribution = `.zoo/` naming separation |
| [Sprint history](docs/dev/sprints/) | Completed-task archive per sprint |

### Project management

| | Contents |
|---|---|
| [BACKLOG](BACKLOG.md) | Active tasks + ROADMAP + sprint history links |

## License

MIT
