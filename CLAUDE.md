# CLAUDE.md

agent-zoo source repo で Claude Code が作業するための指示書。

## プロジェクト概要

AI コーディングエージェント（Claude Code / Codex CLI / Gemini CLI 等）を安全に自律実行するためのセキュリティハーネス。Docker Compose 隔離 + mitmproxy ペイロード検査 + TOML ポリシー制御を **エージェント非依存** で提供する。

セキュリティの根本思想: **「読めても送れない」— ネットワーク隔離が防御の本質。**

参照:
- 利用者向け docs: [`docs/user/`](docs/user/)
- 開発者向け docs: [`docs/dev/`](docs/dev/) (architecture, python-api, ADR, Sprint アーカイブ)
- BACKLOG / ROADMAP: [`BACKLOG.md`](BACKLOG.md)

## リポジトリ構造（ADR 0002）

```
agent-zoo/
├── src/zoo/                  # Python source: zoo CLI / API
│   ├── api.py / runner.py / cli.py
│   └── _init_assets/         # zoo init() で workspace に配布する .gitignore 等
├── bundle/                   # 配布資材（zoo init で <workspace>/.zoo/ にコピーされる元）
│   ├── docker-compose.yml
│   ├── policy.toml
│   ├── addons/               # mitmproxy addons (policy / policy_enforcer / sse_parser / policy_inbox 等)
│   ├── container/            # Dockerfile.{base,codex,gemini,unified}
│   ├── dashboard/            # Flask + HTMX ダッシュボード
│   ├── templates/            # HARNESS_RULES.md（agent への指示テンプレ）
│   └── host/, dns/, certs/
├── tests/                    # pytest（repo root、bundle/ を pythonpath で参照）
├── docs/user/                # 利用者向け（install / security / policy-reference）
├── docs/dev/                 # 開発者向け（architecture / python-api / adr/ / sprints/）
└── BACKLOG.md                # active タスク + ROADMAP + Sprint 履歴 link
```

**source repo では `zoo` CLI は動かない**（`.zoo/` が無いため）。dogfood は別 dir で `pip install -e . && zoo init && zoo build` する。詳細は [ADR 0002 D7](docs/dev/adr/0002-dot-zoo-workspace-layout.md)。

## アーキテクチャ

2 モード構成（詳細: [docs/dev/architecture.md](docs/dev/architecture.md)）:
- **コンテナモード**: `internal: true` ネットワークで agent を隔離。mitmproxy サイドカーが唯一の外部通信経路。`cap_drop: [ALL]` + dangerously-skip-permissions
- **ホストモード**: ネイティブ CLI → mitmproxy (localhost:8080)。Seatbelt サンドボックス併用

## 開発コマンド（maintainer、dogfood workspace で `zoo` CLI）

source repo 直下では動かないため、別 dir で dogfood する:

```bash
pip install -e .
mkdir /tmp/zoo-dogfood && cd /tmp/zoo-dogfood
zoo init                          # `.zoo/` を作成

# build
zoo build --agent claude          # base + agent image

# dogfood run
zoo run                           # 対話モード（初回は /login）
zoo run --dangerous               # 箱庭モード（承認なし）
CLAUDE_CODE_OAUTH_TOKEN=xxx zoo task "..."
zoo bash                          # コンテナ内 bash
zoo up --dashboard-only           # dashboard のみ起動
zoo down                          # 停止
zoo reload                        # policy.toml 変更後のリロード

# ログ
zoo logs clear
zoo logs analyze / summarize / alerts   # ホスト側 claude CLI で AI 分析
```

配布物には Makefile を含めない（zoo CLI 一本化）。

## テスト・dev タスク（repo root の `Makefile`）

repo root の `Makefile` は **dev 専用**。`PLAYWRIGHT_BROWSERS_PATH` を `.venv/playwright-browsers/` へ強制 export し、system の `~/Library/Caches/ms-playwright/` を汚さない仕組み。配布物の Docker compose 操作は `zoo` CLI に一本化（Makefile は source repo にも配布物にも含めない）。

```bash
make help           # ターゲット一覧
make setup          # uv sync --extra dev --extra e2e
make e2e-install    # Playwright Chromium を .venv 配下に download (~150MB、初回)
make unit           # ユニットテスト 234 件
make e2e            # E2E P1 (dashboard, Docker 不要、~5 秒)
make e2e-all        # E2E 全実行 (P2 は Docker daemon 必要)
make test           # unit + e2e
```

- **pytest は必ず 1 プロセス・フォアグラウンド**（並列禁止、ロック系テストがデッドロックする）
- `tests/` は repo root 直下、`pythonpath = ["bundle"]` (pyproject.toml) で `addons` / `dashboard` を top-level import
- E2E 詳細は [tests/e2e/README.md](tests/e2e/README.md)、戦略は [ADR 0003](docs/dev/adr/0003-e2e-test-strategy.md)

## 重要な設計判断

- **Dockerfile**: Alpine Linux 禁止（musl libc 互換性で agent がクラッシュ）。`node:20-slim` を使う
- **証明書**: ランタイムボリュームマウント + `NODE_EXTRA_CA_CERTS` + `SSL_CERT_FILE` env。`NODE_TLS_REJECT_UNAUTHORIZED=0` は絶対使わない
- **認証**: 対話 = コンテナ内 `/login` / 自律 = `CLAUDE_CODE_OAUTH_TOKEN` env（`claude setup-token` で取得）
- **SSE 解析**: ドメイン制御/レート制限は `request()` フックで完結。tool_use 検出は SSE チャンクのステートマシン解析
- **ポリシー書き換え**: atomic write（tmpfile + rename、Docker bind mount ではフォールバック）
- **ダッシュボード**: `127.0.0.1` バインド、`bundle/data` は読み取り専用マウント
- **Inbox** (ADR 0001): agent → `<workspace>/.zoo/inbox/*.toml` → dashboard accept → `policy.runtime.toml` 自動反映
- **Workspace Layout** (ADR 0002): **source = `bundle/`** / **配布 = `.zoo/`** で命名分離

## Sprint 進行状況

[BACKLOG.md](BACKLOG.md) と [docs/dev/sprints/](docs/dev/sprints/) 参照。
