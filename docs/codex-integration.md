# Codex CLI 統合ガイド

Agent ZooにCodex CLI対応を追加するための作業ガイド。

## 概要

Agent Zooはエージェント非依存のセキュリティハーネス。現在Claude Code用のDockerfile + SSEパーサーが実装済み。Codex CLI対応には以下が必要:

1. Codex CLI用Dockerイメージ
2. OpenAI形式のSSEパーサー
3. 設定テンプレート

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

`docker-compose.yml`で切り替え:
```yaml
claude:
  build:
    context: ./container
    dockerfile: Dockerfile.codex  # ← ここを変えるだけ
```

## 2. OpenAI SSEパーサー（`addons/openai_sse_parser.py`）

`addons/sse_parser.py`の`BaseSSEParser`を継承して実装。

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

```python
# addons/openai_sse_parser.py
from sse_parser import BaseSSEParser, ToolUse

class OpenAISSEParser(BaseSSEParser):
    def __init__(self):
        super().__init__()
        self._active_tool_calls: dict[int, dict] = {}

    def _handle_data(self, event_name: str, data: dict) -> None:
        # OpenAI形式: data.choices[0].delta.tool_calls
        # tool_callsの各エントリにindex, function.name, function.argumentsがある
        # argumentsはストリーミングで分割して届く
        ...

    def reset(self) -> None:
        super().reset()
        self._active_tool_calls.clear()
```

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

### テスト（`tests/test_openai_sse_parser.py`）

`tests/test_sse_parser.py`を参考にテストを作成:
- 単一tool_callの完全シーケンス
- 複数tool_callsの同時処理
- arguments分割の正しい結合
- チャンク境界を跨ぐケース
- `[DONE]`の処理
- 不正JSONのハンドリング

## 3. policy_enforcer.pyの変更

`addons/policy_enforcer.py`のresponseフックでContent-TypeやURLパターンからプロバイダを判別し、適切なパーサーを使う。

```python
# 判別ロジック案
if "api.openai.com" in flow.request.host:
    parser = OpenAISSEParser()
else:
    parser = AnthropicSSEParser()
```

## 4. 設定テンプレート（`templates/codex-cli/`）

Codex CLI用の推奨設定ファイルを作成:
- `templates/codex-cli/config.json`（あれば）

## 5. docker-compose.yml

現在の`claude`サービスをそのまま使い、`dockerfile`を切り替えるだけ。環境変数を変える:

```yaml
claude:
  build:
    context: ./container
    dockerfile: ${AGENT_DOCKERFILE:-Dockerfile}
  environment:
    - OPENAI_API_KEY=${OPENAI_API_KEY:-}
    # or ANTHROPIC系の環境変数
```

## テスト実行

```bash
# ユニットテスト
uv run python -m pytest tests/test_openai_sse_parser.py -v

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
