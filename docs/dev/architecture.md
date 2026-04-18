# アーキテクチャ

> 日本語 | [English](architecture.en.md)

## 2モード構成

### コンテナモード（自律実行・CI向け）

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

- `internal: true` でルーティングレベル隔離
- エージェントはプロキシ経由でのみ外部通信可能
- エージェントごとの危険実行フラグ + `cap_drop: [ALL]`

### ホストモード（対話開発向け）

```
Claude Code → srt (customProxy) → mitmproxy (localhost:8080) → internet
```

Docker不要。macOS Seatbeltサンドボックスと併用。

## Workspace Layout（ADR 0002）

source repo (clone) と 配布物 (zoo init された user workspace) で命名分離している:

| | source repo (`bundle/`) | 配布物 (`<workspace>/.zoo/`) |
|---|---|---|
| 意味 | 配布資材の置き場（maintainer が編集）| user workspace 内の harness 一式 |
| `docker-compose.yml` 等 | `bundle/docker-compose.yml` | `.zoo/docker-compose.yml` |
| Makefile | **無し**（Docker compose 操作は `zoo` CLI に一本化） | **無し** |
| 検出ロジック | — | `runner.workspace_root()` が `.zoo/docker-compose.yml` を walk-up |

詳細は [ADR 0002 .zoo/ Workspace Layout](adr/0002-dot-zoo-workspace-layout.md) を参照。
以下のコンポーネント表のパスは **配布物視点**（`.zoo/...`）で記述する。

## コンポーネント

| パス（配布物） | 役割 | 依存 |
|---|---|---|
| `.zoo/addons/policy.py` | ポリシーエンジン（ドメイン/パス制御、レート制限、ペイロード検査、アラート、tool_useブロック判定） | なし |
| `.zoo/addons/sse_parser.py` | SSE / JSON / OpenAI Responsesイベントからtool_useを抽出。`BaseSSEParser` + `AnthropicSSEParser` / `OpenAISSEParser` / `OpenAIResponsesStreamParser` / `AutoDetectSSEParser` を実装 | なし |
| `.zoo/addons/policy_enforcer.py` | mitmproxyアドオン。HTTP response と WebSocket message を検査し、tool_use抽出とブロックを行う | mitmproxy |
| `.zoo/addons/policy_edit.py` | ポリシー編集・ホワイトリスト育成（atomic write、ファイルロック） | tomli_w |
| `.zoo/addons/policy_inbox.py` | Policy Inbox の storage layer（pure logic、ADR 0001） | tomli_w |
| `.zoo/dashboard/app.py` | Flask + HTMX ダッシュボード（Inbox タブ含む） | Flask |
| `.zoo/policy.toml` | ベースポリシー（人間が編集、コメント付き、git管理） | — |
| `.zoo/policy.runtime.toml` | ランタイムポリシー（ダッシュボードが書き込み、gitignore） | — |
| `.zoo/inbox/*.toml` | エージェントが提出する許可リクエスト（ADR 0001） | — |
| `.zoo/templates/HARNESS_RULES.md` | Agent 共通の harness 規約（CLAUDE.md / AGENTS.md / GEMINI.md として inject） | — |
| `.zoo/container/Dockerfile.base` | 共通 base イメージ（agent-zoo-base:latest）。各 agent はこれを `FROM` する | — |
| `.zoo/container/Dockerfile{,.codex,.gemini}` | 各 agent 単体イメージ（claude / codex / gemini） | — |
| `.zoo/container/Dockerfile.unified` | claude + codex + gemini を同梱した統合イメージ（#27、cross-agent 呼び出し用） | — |

### Image Variants

- **単体イメージ**（`Dockerfile`, `Dockerfile.codex`, `Dockerfile.gemini`）: 1 agent 専用、最小サイズ。通常はこちら
- **統合イメージ**（`Dockerfile.unified`）: claude → gemini を呼ぶ等の cross-agent 呼び出し用。`docker compose --profile unified up -d unified` → `docker compose exec unified bash` でコンテナ内に入って任意 CLI を起動

## Policy Inbox（ADR 0001）

エージェントが「ブロックされたが必要な通信」を **`/harness/inbox/<日時>-<id>.toml`** に書き込み、
人間が dashboard で承認すれば `policy.runtime.toml` の `domains.allow` / `paths.allow` に自動反映される。

```
agent → /harness/inbox/*.toml (1 リクエスト 1 ファイル, atomic O_EXCL + content hash dedup)
              ↓
         dashboard /partials/inbox（pending 一覧）
              ↓
         accept → policy_edit.add_to_allow_list / add_to_paths_allow
              ↓
         policy.runtime.toml に追記 → 次の proxy reload で有効化
```

詳細は [ADR 0001 Policy Inbox](adr/0001-policy-inbox.md) を参照。

## データフロー

### リクエスト処理

```
エージェント → HTTP request → policy_enforcer.request()
  1. ドメイン + パス制御（is_allowed）
  2. レート制限（check_rate_limit）
  3. ペイロード検査（check_payload + Base64/URLデコード再検査）
  → ALLOWED / BLOCKED / RATE_LIMITED / PAYLOAD_BLOCKED
  → SQLite requests + blocks テーブルに記録
```

### レスポンス処理（tool_use検出）

```
API response → policy_enforcer.response()
  SSE: 既知ホストは AnthropicSSEParser / OpenAISSEParser、未知ホストは AutoDetectSSEParser で抽出
  JSON: content[].type == "tool_use" / choices[].message.tool_calls / output[].type == function_call|mcp_call を抽出
  WebSocket: OpenAI Responses の response.* イベントを OpenAIResponsesStreamParser で抽出
  → should_block_tool_use() でブロック判定
  → SQLite tool_uses + alerts テーブルに記録
```

### ポリシーマージ

```
policy.toml (base) + policy.runtime.toml (runtime)
  → PolicyEngine._load() でマージ
  allow_list: base + runtime を結合
  paths_allow: base + runtime をドメイン別にマージ
  deny: baseのみ（runtimeからはdeny操作不可）
  dismissed: base + runtime を結合
```

## SSEパーサー設計

```
BaseSSEParser (ABC)
  ├── feed(chunk)           # 共通: SSE行パース
  ├── drain_completed()     # 共通: ToolUse リスト返却
  ├── reset()               # 共通: 状態リセット
  └── _handle_data(event_name, data)  # 抽象: プロバイダごとに実装
        │
    ├── AnthropicSSEParser   # content_block_start/delta/stop
    └── OpenAISSEParser      # tool_calls in delta

OpenAIResponsesStreamParser      # response.function_call_arguments.* など
AutoDetectSSEParser              # payload shape で Anthropic/OpenAI を判定
```

## ダッシュボード

- **Requests**: リクエスト一覧（ステータスフィルター付き、5秒ポーリング）
- **Tool Uses**: tool_use履歴（ツール名、入力、サイズ）
- **Whitelist**: Current Policy表示 + ブロック候補レビュー + Revoke操作

技術スタック: Flask + HTMX + Pico CSS。ソースマウント + Flask debug modeでホットリロード開発。
