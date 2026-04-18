# Codex CLI Integration Guide

> [日本語](codex-integration.md) | English

A working guide for adding Codex CLI support to Agent Zoo.

## Overview

Agent Zoo is an agent-agnostic security harness. Codex CLI integration adds a Docker image, OpenAI-compatible response tool_call extraction, configuration templates, and Compose / Makefile wiring.

1. Codex CLI Docker image
2. OpenAI-compatible SSE / JSON / Responses stream parser
3. Configuration templates
4. Separate `claude` / `codex` services

## 1. Dockerfile (`container/Dockerfile.codex`)

Use `container/Dockerfile` (for Claude Code) as a reference.

```dockerfile
# See: container/Dockerfile
FROM node:20-slim
# Install Codex CLI, copy entrypoint.sh, etc.
```

Requirements:
- **No Alpine Linux** (musl libc compatibility issues)
- `entrypoint.sh` is shareable (waits for cert + sleep infinity)
- Must work under `cap_drop: [ALL]`
- Authentication-related env vars (`OPENAI_API_KEY`, etc.)

In `docker-compose.yml`, separate Claude and Codex services for cleanliness:

```yaml
codex:
  build:
    context: ./container
    dockerfile: Dockerfile.codex
```

Share `workspace` / `certs` / `policy*`; keep auth volumes separate between `claude` and `codex`.

## 2. OpenAI-compatible Parser (`addons/sse_parser.py`)

Implementation lives in `addons/sse_parser.py`. Currently:

- `OpenAISSEParser`: Chat Completions-style SSE `choices[].delta.tool_calls`
- `OpenAIResponsesStreamParser`: Responses API / Codex WebSocket `response.*` events
- `AutoDetectSSEParser`: for unknown hosts; auto-detects Anthropic / OpenAI by payload shape

### BaseSSEParser interface

```python
class BaseSSEParser(ABC):
    def feed(self, chunk: bytes) -> None:        # common (implemented)
    def drain_completed(self) -> list[ToolUse]:  # common (implemented)
    def reset(self) -> None:                     # common (implemented)

    @abstractmethod
    def _handle_data(self, event_name: str, data: dict) -> None:
        # implement this
        ...
```

### What you implement

### OpenAI SSE format

```
data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_xxx","type":"function","function":{"name":"bash","arguments":""}}]}}]}

data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"{\"command\":"}}]}}]}

data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":" \"ls -la\"}"}}]}}]}

data: {"choices":[{"finish_reason":"tool_calls"}]}

data: [DONE]
```

Key points:
- `tool_calls[].index` identifies which tool_call
- `function.name` only appears on the first chunk
- `function.arguments` is delivered as JSON string fragments
- `finish_reason: "tool_calls"` signals completion
- `[DONE]` is not JSON (handle specially)
- On completion, return `ToolUse(name=function.name, input=full arguments, input_size=len(arguments))`

### OpenAI Responses / Codex WebSocket events

Codex may stream `response.*` events over a WebSocket on the `chatgpt.com` side. Track `response.function_call_arguments.delta` / `.done` and `response.output_item.done` via `OpenAIResponsesStreamParser`.

### Tests

Cover the following:
- `tests/test_openai_sse_parser.py`: Chat Completions SSE, AutoDetect, JSON shape helper
- `tests/test_openai_responses_stream_parser.py`: Responses / Codex WebSocket event parser

## 3. Changes in policy_enforcer.py

`addons/policy_enforcer.py` handles both HTTP responses and WebSocket messages.

```python
# SSE:
parser = create_sse_parser_for_host(flow.request.host)

# JSON:
tool_uses = extract_tool_uses_from_openai_response_data(data)
if not tool_uses:
    tool_uses = extract_tool_uses_from_anthropic_response_data(data)

# WebSocket:
if looks_like_openai_responses_event(event):
    parser.feed_event(event)
```

Because LiteLLM-style hosts can vary, JSON / WebSocket are detected by payload shape, not by hostname.

## 4. Config Templates (`templates/codex-cli/`)

Recommended Codex CLI config:
- `templates/codex-cli/config.toml`

## 5. docker-compose.yml

Keep `claude` and `codex` as separate services. Share only `workspace` / `certs` / `policy*`; auth directories are separate:

```yaml
claude:
  build:
    context: ./container
    dockerfile: Dockerfile
  environment:
    - CLAUDE_CODE_OAUTH_TOKEN=${CLAUDE_CODE_OAUTH_TOKEN:-}

codex:
  build:
    context: ./container
    dockerfile: Dockerfile.codex
  environment:
    - OPENAI_API_KEY=${OPENAI_API_KEY:-}
```

## Running tests

```bash
# Unit tests
python -m pytest tests/test_openai_sse_parser.py tests/test_openai_responses_stream_parser.py -q

# All tests
make unit
```

## Reference files

| File | Use for |
|---|---|
| `addons/sse_parser.py` | BaseSSEParser + AnthropicSSEParser (implementation reference) |
| `tests/test_sse_parser.py` | Test patterns |
| `container/Dockerfile` | Docker image structure |
| `container/entrypoint.sh` | Shared entrypoint |
| `docker-compose.yml` | Service composition |
| `docs/architecture.md` | Overall architecture |
