# Codex CLI 統合ガイド

> 日本語 | [English](codex-integration.en.md)

Agent ZooにCodex CLI対応を追加するための作業ガイド。

## 概要

Agent Zooはエージェント非依存のセキュリティハーネス。Codex CLI対応では Docker イメージ、OpenAI 互換レスポンスの tool_call 抽出、設定テンプレート、Compose/Makefile 連携を追加する。

1. Codex CLI用Dockerイメージ
2. OpenAI互換 SSE / JSON / Responses stream parser
3. 設定テンプレート
4. `claude` / `codex` の service 分離

## 1. Dockerfile（`container/Dockerfile.codex`）

`container/Dockerfile`（Claude Code用）を参考に作成。

```dockerfile
# 参考: container/Dockerfile
FROM node:20-slim
# Codex CLIのインストール、entrypoint.shのコピー等
```

要件:
- **Alpine Linux禁止**（musl libc互換性問題）
- `entrypoint.sh`は共通で使用可能（証明書待機+sleep infinity）
- `cap_drop: [ALL]`で動作すること
- 認証方式に応じた環境変数（`OPENAI_API_KEY`等）

`docker-compose.yml`ではClaude用/ Codex用サービスを分離しておくと扱いやすい:
```yaml
codex:
  build:
    context: ./container
    dockerfile: Dockerfile.codex
```

共有するのは `workspace` / `certs` / `policy*` で、認証ボリュームは `claude` と `codex` で分離する。

## 2. OpenAI互換パーサー（`addons/sse_parser.py`）

実装は `addons/sse_parser.py` に集約する。現在は以下を持つ:

- `OpenAISSEParser`: Chat Completions系 SSE の `choices[].delta.tool_calls`
- `OpenAIResponsesStreamParser`: Responses API / Codex WebSocket の `response.*` イベント
- `AutoDetectSSEParser`: 未知ホスト向け。payload shape で Anthropic / OpenAI を自動判定

### BaseSSEParserインターフェース

```python
class BaseSSEParser(ABC):
    def feed(self, chunk: bytes) -> None:       # 共通（実装済み）
    def drain_completed(self) -> list[ToolUse]:  # 共通（実装済み）
    def reset(self) -> None:                     # 共通（実装済み）

    @abstractmethod
    def _handle_data(self, event_name: str, data: dict) -> None:
        # ここを実装する
        ...
```

### 実装すべきもの

### OpenAI SSEフォーマット

```
data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_xxx","type":"function","function":{"name":"bash","arguments":""}}]}}]}

data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"{\"command\":"}}]}}]}

data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":" \"ls -la\"}"}}]}}]}

data: {"choices":[{"finish_reason":"tool_calls"}]}

data: [DONE]
```

ポイント:
- `tool_calls[].index`でどのtool_callか識別
- `function.name`は最初のチャンクにのみ含まれる
- `function.arguments`はJSON文字列が分割されて届く
- `finish_reason: "tool_calls"`で完了
- `[DONE]`はJSON形式ではない（特別扱い）
- 完了したら`ToolUse(name=function.name, input=arguments全体, input_size=len(arguments))`を返す

### OpenAI Responses / Codex WebSocket イベント

Codex は `chatgpt.com` 側の WebSocket で `response.*` イベントを流すことがある。`response.function_call_arguments.delta` / `.done` や `response.output_item.done` を `OpenAIResponsesStreamParser` で追跡する。

### テスト

以下をカバーする:
- `tests/test_openai_sse_parser.py`: Chat Completions SSE、AutoDetect、JSON shape helper
- `tests/test_openai_responses_stream_parser.py`: Responses / Codex WebSocket event parser

## 3. policy_enforcer.pyの変更

`addons/policy_enforcer.py` では HTTP response と WebSocket message の両方を扱う。

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

LiteLLM のように host が変わるケースがあるため、JSON / WebSocket は host 名ではなく payload shape で判定する。

## 4. 設定テンプレート（`templates/codex-cli/`）

Codex CLI用の推奨設定ファイル:
- `templates/codex-cli/config.toml`

## 5. docker-compose.yml

`claude` と `codex` を別サービスにしておく。共有するのは `workspace` / `certs` / `policy*` のみで、認証ディレクトリは分離する:

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

## テスト実行

```bash
# ユニットテスト
python -m pytest tests/test_openai_sse_parser.py tests/test_openai_responses_stream_parser.py -q

# 全テスト
make unit
```

## 参考ファイル

| ファイル | 参考にすべき内容 |
|---|---|
| `addons/sse_parser.py` | BaseSSEParser + AnthropicSSEParser（実装参考） |
| `tests/test_sse_parser.py` | テストの書き方 |
| `container/Dockerfile` | Dockerイメージ構成 |
| `container/entrypoint.sh` | 共通entrypoint |
| `docker-compose.yml` | サービス構成 |
| `docs/architecture.md` | 全体アーキテクチャ |
