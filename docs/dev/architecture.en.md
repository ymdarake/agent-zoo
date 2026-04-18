# Architecture

> [日本語](architecture.md) | English

## Two-Mode Configuration

### Container Mode (autonomous execution / CI)

```
┌─── intnet (internal: true) ───┐     ┌─── extnet ───┐
│                               │     │              │
│  claude / codex (agent)        │     │              │
│    ↓                          │     │              │
│  proxy (mitmproxy) ───────────┼─────┼→ internet    │
│    ↓ logs                     │     │              │
│  dashboard (Flask)            │     │              │
│                               │     │              │
└───────────────────────────────┘     └──────────────┘
```

- `internal: true` for routing-level isolation
- Agents can talk externally only via the proxy
- Per-agent dangerous-execution flag + `cap_drop: [ALL]`

### Host Mode (interactive development)

```
Claude Code → srt (customProxy) → mitmproxy (localhost:8080) → internet
```

No Docker required. Combine with macOS Seatbelt sandbox.

## Workspace Layout (ADR 0002)

The source repo and the distributed user workspace use **separate naming**:

| | source repo (`bundle/`) | distributed (`<workspace>/.zoo/`) |
|---|---|---|
| Meaning | Where bundled assets live (maintainer-edited) | The harness installed inside the user's workspace |
| `docker-compose.yml` etc. | `bundle/docker-compose.yml` | `.zoo/docker-compose.yml` |
| Makefile | **none** (Docker compose ops are unified under the `zoo` CLI) | **none** |
| Detection | — | `runner.workspace_root()` walks up to find `.zoo/docker-compose.yml` |

See [ADR 0002 .zoo/ Workspace Layout](adr/0002-dot-zoo-workspace-layout.md) for details.
The component table below uses **distributed paths** (`.zoo/...`).

## Components

| Path (distributed) | Role | Deps |
|---|---|---|
| `.zoo/addons/policy.py` | Policy engine (domain/path control, rate limit, payload inspection, alerts, tool_use block decisions) | none |
| `.zoo/addons/sse_parser.py` | Extract tool_use from SSE / JSON / OpenAI Responses events. Implements `BaseSSEParser` + `AnthropicSSEParser` / `OpenAISSEParser` / `OpenAIResponsesStreamParser` / `AutoDetectSSEParser` | none |
| `.zoo/addons/policy_enforcer.py` | mitmproxy addon. Inspects HTTP responses and WebSocket messages, extracts and blocks tool_use | mitmproxy |
| `.zoo/addons/policy_edit.py` | Policy editing / whitelist nurturing (atomic write, file lock) | tomli_w |
| `.zoo/addons/policy_inbox.py` | Storage layer for Policy Inbox (pure logic, ADR 0001) | tomli_w |
| `.zoo/dashboard/app.py` | Flask + HTMX dashboard (includes Inbox tab) | Flask |
| `.zoo/policy.toml` | Base policy (human-edited, comments, git-managed) | — |
| `.zoo/policy.runtime.toml` | Runtime policy (dashboard writes, gitignored) | — |
| `.zoo/inbox/*.toml` | Allow-list requests submitted by the agent (ADR 0001) | — |
| `.zoo/templates/HARNESS_RULES.md` | Common harness rules for all agents (injected as CLAUDE.md / AGENTS.md / GEMINI.md) | — |
| `.zoo/container/Dockerfile.base` | Common base image (`agent-zoo-base:latest`). Each agent `FROM`s this | — |
| `.zoo/container/Dockerfile{,.codex,.gemini}` | Per-agent single image (claude / codex / gemini) | — |
| `.zoo/container/Dockerfile.unified` | Unified image with claude + codex + gemini bundled (#27, cross-agent invocation) | — |

### Image Variants

- **Single-agent images** (`Dockerfile`, `Dockerfile.codex`, `Dockerfile.gemini`): smaller, default for single-agent use
- **Unified image** (`Dockerfile.unified`): for cross-agent invocation (e.g. claude calling gemini). Use `docker compose --profile unified up -d unified` → `docker compose exec unified bash`

## Policy Inbox (ADR 0001)

The agent writes "blocked but necessary" requests to **`/harness/inbox/<timestamp>-<id>.toml`**.
A human approves them in the dashboard, after which they auto-flow into `policy.runtime.toml`'s `domains.allow` / `paths.allow`.

```
agent → /harness/inbox/*.toml (1 request = 1 file, atomic O_EXCL + content hash dedup)
              ↓
         dashboard /partials/inbox (pending list)
              ↓
         accept → policy_edit.add_to_allow_list / add_to_paths_allow
              ↓
         appended to policy.runtime.toml → effective on next proxy reload
```

See [ADR 0001 Policy Inbox](adr/0001-policy-inbox.md) for details.

## Data Flow

### Request Handling

```
agent → HTTP request → policy_enforcer.request()
  1. Domain + path control (is_allowed)
  2. Rate limit (check_rate_limit)
  3. Payload inspection (check_payload + Base64 / URL-decoded re-inspection)
  → ALLOWED / BLOCKED / RATE_LIMITED / PAYLOAD_BLOCKED
  → recorded in SQLite requests + blocks tables
```

### Response Handling (tool_use detection)

```
API response → policy_enforcer.response()
  SSE: known hosts → AnthropicSSEParser / OpenAISSEParser, unknown → AutoDetectSSEParser
  JSON: content[].type == "tool_use" / choices[].message.tool_calls / output[].type == function_call|mcp_call
  WebSocket: OpenAI Responses' response.* events via OpenAIResponsesStreamParser
  → block decision via should_block_tool_use()
  → recorded in SQLite tool_uses + alerts tables
```

### Policy Merge

```
policy.toml (base) + policy.runtime.toml (runtime)
  → merged in PolicyEngine._load()
  allow_list: base + runtime concatenated
  paths_allow: base + runtime merged per domain
  deny: base only (no deny ops from runtime)
  dismissed: base + runtime merged
```

## SSE Parser Design

```
BaseSSEParser (ABC)
  ├── feed(chunk)             # common: SSE line parsing
  ├── drain_completed()       # common: returns ToolUse list
  ├── reset()                 # common: state reset
  └── _handle_data(event_name, data)  # abstract: per-provider impl
        │
    ├── AnthropicSSEParser    # content_block_start/delta/stop
    └── OpenAISSEParser       # tool_calls in delta

OpenAIResponsesStreamParser   # response.function_call_arguments.* etc.
AutoDetectSSEParser           # determines Anthropic/OpenAI by payload shape
```

## Dashboard

- **Requests**: request list (status filter, 5s polling)
- **Tool Uses**: tool_use history (tool name, input, size)
- **Inbox**: ADR 0001 — pending allow-list requests submitted by the agent (single / bulk accept / reject)
- **Whitelist**: current policy view + block candidate review + revoke operations

Tech stack: Flask + HTMX + Pico CSS. Hot-reload dev via source mount + Flask debug mode.
