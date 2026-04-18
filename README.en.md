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
  - Supported: Claude Code, Codex CLI

## Features

- **Payload inspection** — Intercept, inspect, and block traffic via mitmproxy (Base64-decoded re-inspection too).
- **tool_use detection + blocking** — Real-time extraction of agent actions; block dangerous executions live.
- **Dashboard** — Web UI for live monitoring + whitelist nurturing + Policy Inbox approval.
- **Sandbox-style operation** — Block-all → analyze logs → gradually allow, with AI-assisted iteration.

## Quickstart

```bash
# Install from PyPI (after publish)
uv tool install agent-zoo
# Or from a clone
git clone https://github.com/ymdarake/agent-zoo.git
cd agent-zoo
uv tool install .

# Claude Code: interactive (first run requires /login inside the container)
zoo run --workspace /path/to/my-project

# Codex CLI: interactive (first run requires `codex login`)
zoo run --agent codex --workspace /path/to/my-project

# Autonomous mode
CLAUDE_CODE_OAUTH_TOKEN=xxx zoo task -p "add tests"
OPENAI_API_KEY=xxx zoo task --agent codex -p "add tests"

# Dashboard: http://localhost:8080
```

If you don't use `uv tool install`, `uv run zoo ...` works too. The Makefile is still available (`make run`, etc.).

## Commands

`zoo` (recommended) and `make` (legacy-compatible) do the same thing.

| Operation | zoo | make |
|---|---|---|
| Interactive | `zoo run [-a claude\|codex] [-w PATH]` | `make run` / `AGENT=codex make run` |
| Sandbox (no approvals) | `zoo run --dangerous` | `make run-dangerous` |
| Autonomous (non-interactive) | `zoo task -p "..." [-a ...] [-w ...]` | `make task PROMPT="…"` |
| Bring services up only | `zoo up [--dashboard-only] [--strict]` | `make up-dashboard` / `make up-strict` |
| Stop | `zoo down` | `make down` |
| Reload policy | `zoo reload` | `make reload` |
| Build images | `zoo build [-a ...]` | `make build` |
| Generate CA cert | `zoo certs` | `make certs` |
| Host mode | `zoo host start` / `zoo host stop` | `make host` / `make host-stop` |
| Bash inside container | `zoo bash [-a ...]` | `make bash` |
| Wrap host CLI through proxy | `zoo proxy <agent> [args...]` | — |
| Clear logs | `zoo logs clear` | `make clear-logs` |
| Log analysis | `zoo logs analyze` / `summarize` / `alerts` | `make analyze` / `summarize` / `alerts` |
| Tests | `zoo test unit` / `zoo test smoke` | `make unit` / `make test` |

Run `zoo --help` / `zoo <cmd> --help` for details.

## Dashboard

Run `make up-dashboard` and open http://localhost:8080.

Live monitor requests, tool_uses, and blocks; nurture your whitelist; review and approve agent-submitted Inbox requests.

| Requests | Tool Uses | Inbox | Whitelist |
|---|---|---|---|
| ![Requests](docs/images/requests.png) | ![Tool Uses](docs/images/tool-uses.png) | _(ADR 0001)_ | ![Whitelist](docs/images/whitelist.png) |

**Inbox** ([ADR 0001](docs/adr/0001-policy-inbox.md)): the agent files allow-list requests it deems necessary; humans approve or reject them in the dashboard, and accepted ones flow into `policy.runtime.toml`.

## Documentation

| Document | Contents |
|---|---|
| [Architecture](docs/architecture.md) | Components, data flow, internal design (Japanese) |
| [ADR 0001 Policy Inbox](docs/adr/0001-policy-inbox.md) | Design rationale: file format, atomic writes, dedup, lifecycle |
| [Codex Integration Guide](docs/codex-integration.md) | Codex CLI integration notes (Japanese) |
| [Security Model](docs/security.md) | Defense in depth, known constraints, operating principles (Japanese) |
| [Policy Reference](docs/policy-reference.md) | All `policy.toml` settings (Japanese) |
| [BACKLOG](BACKLOG.md) | Active tasks + ROADMAP + Resolved Decisions (the old ROADMAP.md / TODO.md were consolidated here) |
| [Sprint history](docs/sprints/) | Completed-task archive per sprint |

## License

MIT
