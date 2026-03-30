# Agent Harness 設計ドキュメント

AIコーディングエージェント（Claude Code, Codex CLI, Aider, Cline等）を安全に自律実行するためのセキュリティハーネス。Docker Compose隔離 + mitmproxyペイロード検査 + TOMLポリシー制御をエージェント非依存で提供する。

---

## 1. 背景と動機

### 解決する課題

- エージェントの自律実行時に、承認疲れ（approval fatigue）を解消しつつセキュリティを維持する手段がない
- ドメインレベルのフィルタリング（Little Snitch等）ではペイロード検査ができない
- macOS Seatbelt（sandbox-exec）は非推奨API、ポータブルでない、チーム共有困難
- 既存ツール（claude-container等）は可観測性のみで制御（ブロック）を提供しない

### 既存プロジェクトとの差別化

| 観点 | claude-container | mattolson/agent-sandbox | Docker Sandboxes | 本ハーネス |
|---|---|---|---|---|
| ネットワーク隔離 | なし | iptables | MicroVM | `internal: true` |
| トラフィック検査 | APIログのみ | ドメインフィルタ | ドメインフィルタ | 完全ペイロード検査 |
| ポリシーエンジン | なし | YAML(ドメインのみ) | CLI設定 | TOML(レート制限+パターン検出) |
| ブロック機能 | なし | 403返却 | deny list | リアルタイムブロック+アラート |
| エージェント対応 | Claude Codeのみ | 4エージェント | 6エージェント | エージェント非依存 |
| ホストモード | なし | なし | なし | srt + customProxy |
| DNS隔離 | なし | なし | なし | CoreDNS（strictモード） |

---

## 2. アーキテクチャ

### リポジトリ構成

```
agent-harness/
├── policy.toml              # 共通ポリシー（両モードで同一）
├── addons/
│   └── policy_enforcer.py   # mitmproxyアドオン（共通）
├── host/
│   ├── setup.sh             # mitmproxy起動 + srt設定
│   └── srt-settings.json    # customProxy指定
├── container/
│   ├── docker-compose.yml
│   ├── Dockerfile
│   └── entrypoint.sh        # 証明書セットアップ + 待機
├── dashboard/               # オプション（profiles: dashboard）
│   └── ...
├── dns/                     # オプション（profiles: strict）
│   └── Corefile
├── certs/
│   └── .gitkeep
├── data/                    # SQLiteログ格納（.gitignore）
├── workspace/               # エージェント作業ディレクトリ（.gitignore）
├── Makefile
└── CLAUDE.md
```

### 2モード構成

#### ホストモード（対話的開発向け）

```
Claude Code (ネイティブ) → srt (customProxy) → mitmproxy (localhost:8080) → api.anthropic.com
```

- レイテンシ最小、TTY問題なし
- Mac Studioでの日常開発に最適
- srt-settings.jsonでsandbox-runtimeのcustomProxyにmitmproxyを指定
- Claude Code内蔵サンドボックス（Seatbelt）有効、autoAllowBashIfSandboxed: true
- mitmproxyはホスト上で直接実行（コンテナ外）。Dockerのproxyコンテナとは独立

#### コンテナモード（自律実行・CI向け）

```
┌─── intnet (internal: true) ───┐     ┌─── extnet ───┐
│                               │     │              │
│  claude (エージェント)         │     │              │
│    ↓                          │     │              │
│  proxy (mitmproxy) ───────────┼─────┼→ internet    │
│                               │     │              │
│  dns (CoreDNS) [strict時のみ] │     │              │
└───────────────────────────────┘     └──────────────┘
                                      │              │
                                      │  dashboard   │ :8080 [オプション]
                                      └──────────────┘
```

- `internal: true` でルーティングレベル隔離（iptablesのMASQUERADE/FORWARDルールが生成されない）
- エージェントコンテナはプロキシ経由でのみ外部通信可能
- raw socketやhardcoded URLによる直接接続も不可能
- `--dangerously-skip-permissions` でClaude内蔵サンドボックスは無効化（コンテナ境界が保護）

### モード排他制約

ホストモードとコンテナモードは同時に使用しない。同一の `./data/harness.db` を使うため、同時使用するとSQLiteのファイルロック競合が発生する可能性がある。

---

## 3. Docker Compose

```yaml
services:
  claude:
    build:
      context: ./container
      args:
        - HOST_UID=${HOST_UID:-1001}
    depends_on:
      proxy:
        condition: service_healthy
    environment:
      - HTTP_PROXY=http://proxy:8080
      - HTTPS_PROXY=http://proxy:8080
      - NODE_EXTRA_CA_CERTS=/certs/mitmproxy-ca-cert.pem
      - SSL_CERT_FILE=/certs/mitmproxy-ca-cert.pem
      - CLAUDE_CODE_OAUTH_TOKEN=${CLAUDE_CODE_OAUTH_TOKEN}
    networks: [intnet]
    volumes:
      - ./certs:/certs:ro
      - ./workspace:/workspace
    stdin_open: true
    tty: true
    entrypoint: ["/usr/local/bin/entrypoint.sh"]
    cap_drop: [ALL]

  proxy:
    image: mitmproxy/mitmproxy:10
    command: mitmdump -s /scripts/policy_enforcer.py
    healthcheck:
      test: ["CMD", "curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "--proxy", "http://localhost:8080", "http://httpbin.org/status/200"]
      interval: 5s
      timeout: 10s
      retries: 3
      start_period: 10s
    networks: [intnet, extnet]
    volumes:
      - ./certs:/home/mitmproxy/.mitmproxy
      - ./addons:/scripts:ro
      - ./policy.toml:/scripts/policy.toml:ro
      - ./data:/data

  proxy-debug:
    image: mitmproxy/mitmproxy:10
    profiles: ["debug"]
    command: mitmweb --web-host 0.0.0.0 -s /scripts/policy_enforcer.py
    ports: ["8081:8081"]
    networks: [intnet, extnet]
    volumes:
      - ./certs:/home/mitmproxy/.mitmproxy
      - ./addons:/scripts:ro
      - ./policy.toml:/scripts/policy.toml:ro
      - ./data:/data

  dashboard:
    build: ./dashboard
    profiles: ["dashboard"]
    ports: ["127.0.0.1:8080:8080"]
    volumes:
      - ./data:/data:ro
      - ./policy.toml:/app/policy.toml
    networks: [extnet]

  dns:
    image: coredns/coredns
    profiles: ["strict"]
    networks:
      intnet:
        ipv4_address: 172.20.0.10
    volumes:
      - ./dns/Corefile:/etc/coredns/Corefile:ro

networks:
  intnet:
    internal: true
    ipam:
      config:
        - subnet: 172.20.0.0/24
  extnet: {}
```

### 設計判断（前版からの変更点）

1. **mitmproxyイメージのバージョン固定**: `mitmproxy/mitmproxy:10` — メジャーバージョン間でアドオンAPIの破壊的変更がある
2. **proxyのhealthcheck追加**: `depends_on: condition: service_healthy` でclaudeコンテナの起動順序を保証。証明書生成完了も暗黙的に保証される
3. **UID引数のビルド時渡し**: `HOST_UID` でホスト側ユーザーとUID一致を保証（workspace内パーミッション問題の防止）
4. **dashboardのポートバインド**: `127.0.0.1:8080:8080` でlocalhostのみ。認証なしで外部公開しない
5. **proxy-debug**: mitmweb UIをprofilesで分離。`make up-debug` で起動
6. **dashboard volumes**: `./data:/data:ro` で読み取り専用。ポリシー編集はpolicy.tomlへの書き込みのみ許可

### Dockerfile（container/Dockerfile）

```dockerfile
FROM node:20-slim

ARG HOST_UID=1001

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates git sqlite3 curl \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g @anthropic-ai/claude-code

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

WORKDIR /workspace
RUN useradd -m -u ${HOST_UID} claude
USER claude
```

### entrypoint.sh（container/entrypoint.sh）

```bash
#!/bin/bash
set -e

# ランタイムで証明書をセットアップ（rootが必要な場合はsudo or ビルド時に対応）
# NODE_EXTRA_CA_CERTS と SSL_CERT_FILE は環境変数で設定済み

echo "Waiting for proxy certificates..."
until [ -f /certs/mitmproxy-ca-cert.pem ]; do
  sleep 1
done
echo "Certificates found."

# コンテナを待機状態に（exec claude は docker compose exec で実行）
exec sleep infinity
```

### 証明書管理の設計判断

**問題**: mitmproxyのCA証明書は初回起動時に自動生成される。Dockerfileの `COPY` ではビルド時に証明書が存在しない（鶏と卵問題）。

**解決策**: Makefileで証明書を事前生成 + ランタイムボリュームマウント の2段構え。

- **ビルド時**: Dockerfile内での `COPY` + `update-ca-certificates` を廃止。証明書はボリュームマウントのみで提供
- **ランタイム**: `NODE_EXTRA_CA_CERTS` + `SSL_CERT_FILE` 環境変数でNode.js/git/curlが参照
- **entrypoint.sh**: 証明書ファイルの存在を待ってから待機状態に入る
- **Makefile**: `make certs` ターゲットで事前生成（後述）

```
Dockerfile注意事項:
- Alpine Linux禁止: musl libc互換性でClaude Codeがクラッシュする（posix_getdents: symbol not found）
- NODE_TLS_REJECT_UNAUTHORIZED=0 は絶対使わない
- メモリ4GB以上確保: 下回るとOOM Killerが発動
- 認証は`CLAUDE_CODE_OAUTH_TOKEN`環境変数で毎回渡す。.envファイルは使わない
```

---

## 4. Makefile

```makefile
# 変数
HOST_UID := $(shell id -u)

# === 証明書管理 ===
certs/mitmproxy-ca-cert.pem:
	@echo "Generating mitmproxy CA certificate..."
	docker run --rm -v ./certs:/home/mitmproxy/.mitmproxy \
	  mitmproxy/mitmproxy:10 \
	  sh -c "mitmdump --set confdir=/home/mitmproxy/.mitmproxy & sleep 3 && kill %1"
	@echo "Certificate generated: certs/mitmproxy-ca-cert.pem"

certs: certs/mitmproxy-ca-cert.pem

# === ビルド ===
build: certs
	HOST_UID=$(HOST_UID) docker compose build

# === コンテナモード ===
run: certs
	HOST_UID=$(HOST_UID) docker compose up -d claude
	docker compose exec claude claude

task: certs
	HOST_UID=$(HOST_UID) docker compose up -d claude
	docker compose exec claude claude -p "$(PROMPT)" --dangerously-skip-permissions

up: certs
	HOST_UID=$(HOST_UID) docker compose up -d

up-dashboard: certs
	HOST_UID=$(HOST_UID) docker compose --profile dashboard up -d

up-strict: certs
	HOST_UID=$(HOST_UID) docker compose --profile strict up -d

up-debug: certs
	HOST_UID=$(HOST_UID) docker compose --profile debug up -d

down:
	docker compose down

# === ホストモード ===
host:
	cd host && ./setup.sh

# === スモークテスト ===
test: certs
	@echo "=== Smoke Test ==="
	HOST_UID=$(HOST_UID) docker compose up -d proxy
	@echo "Testing allowed domain..."
	docker compose run --rm claude curl -x http://proxy:8080 -s -o /dev/null -w '%{http_code}' https://api.anthropic.com/ || true
	@echo "Testing blocked domain..."
	docker compose run --rm claude curl -x http://proxy:8080 -s -o /dev/null -w '%{http_code}' https://evil.com/ || true
	@echo "Testing direct access (should fail)..."
	docker compose run --rm claude curl -s --connect-timeout 3 https://api.anthropic.com/ 2>&1 || true
	docker compose down
	@echo "=== Smoke Test Complete ==="

# === ログ分析（ホスト側Claude CLI利用）===
analyze:
	@sqlite3 data/harness.db -json \
	  "SELECT host, COUNT(*) as n, GROUP_CONCAT(DISTINCT tool_name) as via \
	   FROM requests WHERE status='BLOCKED' GROUP BY host ORDER BY n DESC" \
	| claude -p "ブロックログとcurrent policy.tomlを比較して改善案をTOML形式で提案して。\
	  許可すべきドメインとその理由、危険なドメインとその理由を分けて。" \
	  --file policy.toml

summarize:
	@sqlite3 data/harness.db -json \
	  "SELECT tool_name, input, ts FROM tool_uses ORDER BY ts DESC LIMIT 100" \
	| claude -p "このtool_use履歴からホストモード用settings.jsonの最小権限設定を提案して"

alerts:
	@sqlite3 data/harness.db -json \
	  "SELECT * FROM requests WHERE status IN ('BLOCKED','RATE_LIMITED') \
	   ORDER BY ts DESC LIMIT 50" \
	| claude -p "セキュリティ上の懸念があるパターンを報告して"
```

`make run` 一発でproxy起動→claude待機→対話開始。終了後もコンテナは残るので、次回は `docker compose exec claude claude` で即再入可能。

---

## 5. ポリシーエンジン

### policy.toml

```toml
[general]
log_db = "/data/harness.db"

[domains.allow]
list = ["api.anthropic.com"]

[domains.deny]
list = ["*.evil.com"]

[domains.dismissed]
"registry.npmjs.org" = { reason = "ホスト側でnpm install済み", date = "2026-03-29" }

[rate_limits]
"api.anthropic.com" = { rpm = 30, burst = 5 }

[payload_rules]
# エージェント→Anthropic APIへの送信内容を検査（機密情報の流出防止）
# ※実行コマンドのブロックは [tool_use_rules] で行う
block_patterns = []
secret_patterns = [
  "AWS_SECRET_ACCESS_KEY",
  "ANTHROPIC_API_KEY",
  "-----BEGIN.*PRIVATE KEY-----",
]

[tool_use_rules]
# Anthropic API→エージェントのtool_useを検査（危険な実行を阻止）
block_tools = []
block_args = ["rm -rf /", "chmod 777", "printenv", "/etc/shadow"]

[alerts]
suspicious_tools = []
suspicious_args = ["~/.ssh", "~/.aws", ".env", "id_rsa"]
# tool_use引数のサイズ閾値（バイト）— 異常に大きい場合アラート
tool_arg_size_alert = 10000
```

設計方針:
- **TOML = 判断の記録**（どうするか・なぜそうしたか）。gitで管理可能
- **SQLite = 事実の記録**（何が起きたか）。ログ専用
- mitmproxyのホットリロード対応。policy.tomlを保存すると即座に反映
- **ポリシー書き換えはatomic write**（tmpfile + rename）で行い、mitmproxyのホットリロードとの競合を防止

### mitmproxyアドオン（policy_enforcer.py）

核心機能:
1. **ドメイン制御**: allowedDomains外への通信をブロック（flow.kill()） — `request()` フックで処理
2. **レート制限**: ドメイン別RPMカウント、閾値超過でブロック — `request()` フックで処理
3. **tool_use検出**: APIレスポンス内のtool_useブロックを解析し、危険パターンをログ/アラート（SSEストリーミング対応が必要、後述）
4. **ログ記録**: 全リクエスト/レスポンスをSQLiteに記録（INSERTのみ、ホットパスに余計な処理を入れない）

### SSEストリーミング対応

**問題**: Claude APIの `/v1/messages` は `stream: true` の場合SSE（Server-Sent Events）でレスポンスを返す。mitmproxyのデフォルト動作ではレスポンス全体をバッファリングするため、long-lived connectionの `response()` フックが発火しない/大幅に遅延する。

**影響範囲**:
- **ドメイン制御/レート制限**: `request()` フックで完結するため**影響なし**
- **tool_use検出**: SSEチャンクの逐次解析が必要。`content_block_start`/`content_block_delta`/`content_block_stop` のステートマシンでtool_useを再構築する必要がある

**対応方針**:

```python
def responseheaders(self, flow: http.HTTPFlow):
    content_type = flow.response.headers.get("content-type", "")
    if "text/event-stream" in content_type:
        # SSEレスポンスはストリーミングモードで透過（レイテンシに影響しない）
        flow.response.stream = self._sse_chunk_handler(flow)

def _sse_chunk_handler(self, flow):
    """SSEチャンクを逐次処理し、tool_useブロックを再構築するステートマシン"""
    buffer = SSEToolUseBuffer()
    def handler(chunks):
        for chunk in chunks:
            yield chunk  # クライアントにはそのまま透過
            buffer.feed(chunk)  # 同時にバッファに蓄積して解析
            for tool_use in buffer.drain_completed():
                self._log_tool_use(flow, tool_use)
    return handler
```

**MVPでの方針**: tool_use検出はPhase 2に移動。MVPではドメイン制御とリクエストログ記録のみ実装し、SSEストリーミングは透過させる。

### tool_use検出について

Anthropic APIレスポンスのJSON内にtool_useブロック（Claudeが次に実行するツールと引数）が含まれる。mitmproxyでこれを傍受すると、実行前にパターンを検知できる。主な用途は**監査・アラート・異常検知**。「何をしようとしたか」のログはポリシー改善とホストモード設定の最適化に活用する。

---

## 6. データストア

### SQLite（/data/harness.db）

```
harness.db
├── requests       # 全リクエスト/レスポンスログ（ts, host, method, url, status, body_size）
├── tool_uses      # tool_use呼び出し履歴（ts, tool_name, input, input_size）
├── blocks         # ブロックされたリクエスト（ts, host, reason）
└── alerts         # アラート履歴（ts, type, detail）
```

設計方針:
- **WALモード**: mitmproxy（書き込み）とダッシュボード（読み取り）が同時アクセス可能
- **ローテート不要**: ダッシュボードのクリアボタンで手動管理
- **プロキシはINSERTだけ**: ホットパスに余計な処理を入れない

---

## 7. ダッシュボード（オプション）

composeのprofilesで分離。`make up-dashboard` で起動。extnetに配置し、エージェントコンテナからはアクセス不可能（ポリシー改ざん防止）。

### セキュリティ

- **localhostバインド**: `127.0.0.1:8080:8080` で外部ネットワークからのアクセスを遮断
- **読み取り専用データ**: SQLiteは `ro` マウント。ダッシュボードからのデータ改ざんを防止
- **ポリシー編集**: policy.tomlへの書き込みのみ許可。atomic write（tmpfile + rename）で書き換え
- **将来の認証**: Phase 3以降でBasic認証 or APIキー認証を追加検討。現時点ではlocalhost制限で十分

### 機能

- **ログ閲覧**: 全リクエスト、tool_use履歴、ブロック履歴（リアルタイム）
- **ポリシー編集**: allowedDomains、レート制限、block_patterns → 保存時にpolicy.toml書き換え → ホットリロード
- **ダッシュボード**: リクエスト数/分、ドメイン別トラフィック、アラート一覧
- **クリアボタン**: ログの手動削除（全削除 or 日付指定）

### ホワイトリスト育成機能

ブロックされたリクエストを集計し、許可候補として提示する。

```
⚠ 推奨ドメイン候補
registry.npmjs.org    blocked 23回 (npm install経由)  [許可] [無視]
pypi.org              blocked 8回  (pip install経由)  [許可] [無視]
evil.com              blocked 3回  (curl POST経由)    [許可] [無視]

🚫 無視済みドメイン
registry.npmjs.org  「ホスト側でnpm install済み」  2026-03-29  [再評価]
```

- tool_useのコンテキスト（どのコマンド経由か）を一緒に表示し、判断を支援
- **「許可」** → policy.toml の `domains.allow.list` に追記 → ホットリロード
- **「無視」** → メモ入力ダイアログ → policy.toml の `domains.dismissed` に理由・日付とともに保存
- **「再評価」** → dismissedから削除し候補に復帰

---

## 8. ログ分析CLI

専用のanalyzerコンテナは設けず、**ホスト側のClaude CLIにSQLiteログを食わせる**。コンテナ化しないことで、analyzer自身が環境変数やログ内容を外部に漏洩するリスクをゼロにする。

```bash
make analyze     # ブロックログ → policy.toml改善提案（TOML形式で出力）
make summarize   # tool_use履歴 → ホストモードsettings.jsonの最小権限提案
make alerts      # 異常パターン検出
```

### tool_useログの活用

コンテナモードを**ポリシー発見のためのサンドボックス**として使える：

```
コンテナモードで自律実行（ゆるめの設定）
  ↓
tool_useログが溜まる
  ↓
「このプロジェクトでClaudeが実際に使うコマンド/パス/ドメイン」が判明
  ↓
make summarize でホストモード用settings.jsonの最小権限設定を提案
```

### 異常パターンの共有

ブロックされたリクエストのドメイン+パターン（ペイロードの中身は含めない）を集約し、コミュニティdenyリストとして共有する可能性がある。

---

## 9. ネットワークセキュリティ

### 最小限のドメインアローリスト

- `api.anthropic.com` — 必須（API通信）
- `statsig.anthropic.com` — オプション（フィーチャーフラグ、なくても動くが「offline」表示の場合あり）
- `sentry.io` — オプション（エラー追跡）

### github.comをallowedDomainsに入れない

github.comを許可すると:
- 攻撃者管理リポへのデータpushが可能
- Gist API経由の情報窃取が可能
- 公開issue/PR/READMEからのプロンプトインジェクション（インバウンド）
- denyRead等のファイル制限ではCWD内のソースコード漏洩を防げない

git操作はホスト側で実施するか、スコープ付きトークン+プロキシパターンを使用。

### サプライチェーン（パッケージ管理）のポリシー

パッケージレジストリ（registry.npmjs.org、pypi.org等）は初期ホワイトリストに入れない。

- パッケージのインストールは人間がホスト側で行い、lock fileでバージョン固定
- コンテナにはworkspaceごとマウント。エージェントは `npm ci`（lock file完全一致のみ）で再現
- ネットワークが `api.anthropic.com` のみ許可なので `npm install <新パッケージ>` は物理的に失敗（二重防御）
- 脆弱性スキャン（trivy等）はハーネスのスコープ外

### DNS外部送信

HTTP/HTTPS通信はすべてmitmproxy経由のため、claudeコンテナからDNSクエリ自体が発生しない（プロキシが代理解決）。漏洩経路は `ping` や `dig` 等の非HTTPコマンドのみで、Docker内蔵DNS（127.0.0.11）がホストのリゾルバに転送する経路を使う。

- **通常モード**: この穴を受容。実用上のリスクは限定的（DNS経由で送れるデータ量はごく小さい）
- **strictモード**: `make up-strict` でCoreDNSを有効化。許可ドメインのみDNS解決、それ以外はNXDOMAINで即座に拒否

### api.anthropic.com経由のデータ漏洩対策

`api.anthropic.com` のみ許可でもFile API経由のデータ漏洩が理論上可能（Embrace The Red報告）。

対策:
- サンドボックス内の機密データ量自体を最小化する設計が根本的に重要
- マウントしたボリューム（/workspace）内のデータはエージェントが自由に読み書きできる。機密ファイルを置かない
- `payload_rules.secret_patterns` でAPI KEY等の機密パターンをデフォルトで検知
- `alerts.tool_arg_size_alert` で異常に大きいtool_use引数を検知（大量データ流出の兆候）
- Phase 2以降: エンコード済みペイロードのデコード+再検査（Base64, Hex, URL encoding）

### 既知のリスク（受容）

- File API経由のデータ漏洩は完全な防止が困難。上記の多層防御で検知・抑止を目指す
- 正規表現ベースのblock_patternsは難読化に対して脆弱。MLベース検知は将来の拡張として検討

---

## 10. モード別パーミッション戦略

### コンテナモードではClaude内蔵サンドボックスを使わない

コンテナモードでは `--dangerously-skip-permissions` を使用。

理由:
- コンテナ自体がサンドボックス（ファイルシステム = Dockerマウント境界、ネットワーク = `internal: true` + mitmproxy）
- `cap_drop: [ALL]` でコンテナ脱出リスクを最小化
- Docker内でbubblewrapを二重に動かす意味が薄い
- パーミッションプロンプトがゼロになり、完全な自律実行が可能

```
ホストモード:
  Claude sandbox: 有効 + autoAllowBashIfSandboxed: true
  保護層: Seatbelt + mitmproxy（customProxy経由）
  承認: サンドボックス内Bashは自動承認、境界外は確認

コンテナモード:
  Claude sandbox: 無効（--dangerously-skip-permissions）
  保護層: Docker境界 + internal:true + mitmproxy + cap_drop:[ALL]
  承認: なし（完全自律）
```

### ホストモード：srt-settings.json

```json
{
  "customProxy": {
    "url": "http://127.0.0.1:8080",
    "caCertPath": "${HOME}/.agent-harness/certs/mitmproxy-ca-cert.pem"
  }
}
```

注意: customProxy はsandbox-runtime (srt) の機能。対応するClaude Codeのバージョン要件を確認すること。

### ホストモード：settings.json推奨設定

```json
{
  "sandbox": {
    "enabled": true,
    "autoAllowBashIfSandboxed": true,
    "failIfUnavailable": true,
    "allowUnsandboxedCommands": false,
    "excludedCommands": [],
    "filesystem": {
      "allowWrite": ["./"],
      "denyWrite": ["/etc", "/usr", "~/.claude"],
      "denyRead": ["~/.ssh", "~/.aws/credentials"],
      "allowRead": ["."]
    },
    "network": {
      "allowedDomains": ["api.anthropic.com"]
    }
  }
}
```

重要:
- `allowUnsandboxedCommands` デフォルト `true`（脱出ハッチ）→ 必ず `false`
- `failIfUnavailable` デフォルト `false`（サイレントフォールバック）→ 必ず `true`
- Hooksのexit code 2がブロック、exit code 1はノンブロッキング（実行される）
- CLAUDE.mdはソフトガイダンス。ハードな強制にはHooks exit 2またはdenyルール

### ホストモード：setup.sh

```bash
#!/bin/bash
set -e

HARNESS_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CERTS_DIR="${HARNESS_DIR}/certs"
DATA_DIR="${HARNESS_DIR}/data"

# 1. mitmproxyのインストール確認
if ! command -v mitmdump &> /dev/null; then
    echo "mitmproxy not found. Install with: brew install mitmproxy"
    exit 1
fi

# 2. 証明書の存在確認（なければ生成）
if [ ! -f "${CERTS_DIR}/mitmproxy-ca-cert.pem" ]; then
    echo "Generating mitmproxy CA certificate..."
    mitmdump --set confdir="${CERTS_DIR}" &
    MITM_PID=$!
    sleep 3
    kill ${MITM_PID}
fi

# 3. mitmproxyをバックグラウンドで起動
echo "Starting mitmproxy on localhost:8080..."
mitmdump -s "${HARNESS_DIR}/addons/policy_enforcer.py" \
  --set confdir="${CERTS_DIR}" \
  --listen-port 8080 &
MITM_PID=$!
echo "mitmproxy PID: ${MITM_PID}"

# 4. srt-settings.jsonの配置案内
echo ""
echo "=== Setup Complete ==="
echo "mitmproxy running on localhost:8080 (PID: ${MITM_PID})"
echo ""
echo "To stop: kill ${MITM_PID}"
echo ""
echo "Configure Claude Code's srt-settings.json with:"
echo '  { "customProxy": { "url": "http://127.0.0.1:8080", "caCertPath": "'${CERTS_DIR}'/mitmproxy-ca-cert.pem" } }'

# PIDを記録（停止用）
echo ${MITM_PID} > "${DATA_DIR}/.mitmproxy.pid"
```

---

## 11. 実装フェーズ

### MVP（Phase 1）✅

- [x] policy.toml パーサー
- [x] policy_enforcer.py（ドメイン制御、リクエストログ記録）
- [x] docker-compose.yml（claude + proxy、`internal: true`、healthcheck）
- [x] Dockerfile + entrypoint.sh（node:20-slim、ランタイム証明書）
- [x] Makefile（certs, build, run, task, up, down, test）
- [x] SQLiteスキーマ（requests, blocks）
- [x] スモークテスト（make test: 許可/ブロック/直接アクセス不可の3パターン）

### Phase 2 ✅

- [x] SSEストリーミング対応（ステートマシンによるtool_use再構築）
- [x] tool_useキャプチャ + tool_usesテーブル
- [x] レート制限（RPM + burst 2段階ウィンドウ）
- [x] payload_rules（block_patterns + secret_patterns）
- [x] tool_use引数サイズアラート + alertsテーブル
- [x] ホストモード（setup.sh + srt-settings.json）
- [x] make analyze / summarize / alerts

### Phase 3 ✅

- [x] ダッシュボード（Flask + HTMX、ログ閲覧、リアルタイム更新）
- [x] ホワイトリスト育成機能（推奨候補、許可/無視/再評価）
- [x] ポリシー編集API（atomic write）
- [x] CoreDNS strictモード

### 未実装・将来の拡張

[ROADMAP.md](ROADMAP.md) を参照。

---

## 12. レビュー指摘事項と対応

本設計は3つのレビュー（Claude自身・Planエージェント・Gemini）の指摘を統合して改善した。主要な変更点:

| 指摘 | 重要度 | 対応 |
|---|---|---|
| 証明書のビルド順序（鶏と卵問題） | 高 | Dockerfile COPYを廃止、Makefile certsターゲット + entrypoint.shでランタイム対応 |
| mitmproxyバージョン未固定 | 高 | `mitmproxy/mitmproxy:10` に固定 |
| SSEストリーミング未考慮 | 高 | セクション5に対応方針を追記、tool_useキャプチャをPhase 2に移動 |
| proxyのhealthcheck未定義 | 中 | `depends_on: condition: service_healthy` を追加 |
| UID不一致のリスク | 中 | `HOST_UID` ビルド引数を追加 |
| ダッシュボード認証なし | 中 | localhostバインド + データroマウント + Phase 3で認証追加 |
| host/setup.shの詳細不足 | 中 | セクション10に擬似コードを追加 |
| モード排他制約の未明記 | 低 | セクション2に制約を明記 |
| payload_rulesの回避可能性 | 低 | デコード+再検査、エントロピーチェック、secret_patternsをPhase 2に追加 |
| api.anthropic.com経由漏洩の追加対策 | 低 | tool_arg_size_alert、secret_patternsを追加 |
| スモークテストの欠如 | 低 | make testターゲットを追加 |

---

## 13. 参考プロジェクト・文献

- anthropic-experimental/sandbox-runtime — Anthropic公式サンドボックス
- mattolson/agent-sandbox — mitmproxyサイドカー構成の先行実装
- nezhar/claude-container — プロキシ+SQLite+Datasette構成の参考
- akitaonrails/ai-jail — TOML設定の参考
- agentgateway/agentgateway — MCP/A2Aプロキシ、将来統合候補
- chouzz/llm-interceptor — mitmproxyによるLLMトラフィック傍受
- Meta LlamaFirewall — ガードレールシステム設計の参考
- Anthropic "Beyond permission prompts" — 公式設計思想
- NVIDIA "Practical Security Guidance for Sandboxing Agentic Workflows" — レッドチーム知見
- Meta "Agents Rule of Two" — パーミッション設計原則
- Ona "How Claude Code escapes its own denylist and sandbox" — サンドボックス回避の実証
