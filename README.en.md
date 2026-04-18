<p align="center">
  <img src="logo.svg" alt="Agent Zoo" width="400">
</p>

# Agent Zoo

> [日本語](README.md) | English

[![CI](https://github.com/ymdarake/agent-zoo/actions/workflows/ci.yml/badge.svg)](https://github.com/ymdarake/agent-zoo/actions/workflows/ci.yml)

A security harness for running AI coding agents autonomously and safely.

mitmproxy payload inspection + TOML policy control. Agent-agnostic.

## Modes

- **Standalone** — Proxy-only (`zoo host start`). Works with any agent on the host.
- **Docker Compose isolation** — Agents are isolated on an `internal: true` network. *"They can read, but they can't send."*
  - Supported: Claude Code / Codex CLI / Gemini CLI (single + all-in-one unified image)

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

## Dashboard

Run `zoo up --dashboard-only` and open http://localhost:8080.

Live monitor requests, tool_uses, and blocks; nurture your whitelist; review and approve agent-submitted Inbox requests.

| Requests | Tool Uses | Inbox | Whitelist |
|---|---|---|---|
| ![Requests](docs/images/requests.png) | ![Tool Uses](docs/images/tool-uses.png) | _(ADR 0001)_ | ![Whitelist](docs/images/whitelist.png) |

**Inbox** ([User guide (JP)](docs/user/inbox.md)): the agent files allow-list requests it deems necessary; humans approve or reject them in the dashboard, and accepted ones flow into `policy.runtime.toml`.

## Documentation

| Document | Contents |
|---|---|
| [Install & setup](docs/user/install-from-package.md) | `uv tool install` → `zoo init` → `zoo run` setup + `.zoo/` layout |
| [Inbox guide (JP)](docs/user/inbox.md) | Approve agent-submitted allow-list requests in the dashboard |
| [Security Model](docs/user/security.md) | Defense in depth, known constraints, operating principles |
| [Policy Reference](docs/user/policy-reference.md) | All `policy.toml` settings |

## Unified image (cross-agent)

To use one agent from another (e.g., Claude calling Gemini), the `unified` profile bundles claude + codex + gemini into a single container:

```bash
cd <workspace>  # already zoo init'd
HOST_UID=$(id -u) docker compose -f .zoo/docker-compose.yml --profile unified up -d unified
docker compose -f .zoo/docker-compose.yml exec unified bash
# run claude / codex / gemini inside the container
```

Image size is larger (3 CLIs + deps).

## Feedback & developers

- Bug reports / feature requests: [GitHub Issues](https://github.com/ymdarake/agent-zoo/issues)
- Internal design & contributing: [docs/dev/](docs/dev/) (architecture, Python API, ADRs, sprint history)

## License

MIT
