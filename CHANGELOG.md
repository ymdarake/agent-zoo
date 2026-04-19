# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Security
- **Docker image SHA pin (4 image)** — `bundle/container/Dockerfile.base` (node:20-slim) / `bundle/dashboard/Dockerfile` (python:3.12-slim) / `bundle/docker-compose.yml` の proxy (mitmproxy/mitmproxy:10) と dns (coredns/coredns:1.11.4) を multi-arch manifest list digest で固定。上流アカウント奪取 / mutable tag 上書き攻撃を防ぐ。Dependabot が週次更新 PR (Sprint 006 PR E、包括レビュー M-3)
- **GitHub Actions SHA pin (19 uses)** — `actions/checkout` / `astral-sh/setup-uv` / `actions/cache` / `actions/upload-artifact` / `actions/download-artifact` / `pypa/gh-action-pypi-publish` を全 commit SHA で固定。Git tag rewrite による任意 step 実行を防ぐ。`pypa/gh-action-pypi-publish` は branch ref から tag SHA に切替 (Dependabot 自動更新を可能化)。コメントに `# <tag>` 併記 (Sprint 006 PR E、包括レビュー M-4)
- **Dependabot 設定 (`.github/dependabot.yml`)** — github-actions / docker x3 / pip x2 を週次更新、`groups` で 1 ecosystem あたり 1 PR に集約してレビュー負荷削減。`docs/dev/security-notes.md` に PR 受け入れ前の manifest list 検証ガイド (Sprint 006 PR E)
- **`pip-audit` を CI に統合** — `uv tool run pip-audit --vulnerability-service osv` で project + dashboard requirements.txt を独立に audit、PyPI advisory + OSV.dev 併用で広い CVE カバレッジ。`docker compose config --resolve-image-digests` 検証 step も追加 (Sprint 006 PR E)
- **request body サイズ上限 + URL secret 検査 + URL scrub** — mitmproxy `--set body_size_limit=1m` で OOM 保護しつつ、addon 側で `Content-Length > 1MB` を 413 で fail-closed 遮断（M-6）。`flow.request.url` を `scrub_url` で userinfo / query / fragment 全部 redact してから DB 保存（M-2、ログ流出防止 + log injection / smuggling 防御の制御文字 reject）。`secret_patterns` を URL にも適用し credential が乗った request を 403 `URL_SECRET_BLOCKED` で遮断 (Sprint 006 PR D、包括レビュー M-2 / M-6)
- **dashboard `_validate_domain` を RFC 1035 準拠 strict regex 化** — `localhost` / `*.com` / `a..com` / `a-.com` / `*.*.example.com` を UI から追加不可に。inbox accept 経由の bypass も塞ぐ (Sprint 006 PR D、包括レビュー M-5)
- **harness.db / WAL / SHM の chmod 600** — PII / 機密情報を含む sqlite 関連ファイル群を同一 host の他ユーザから保護。symlink follow を抑止 (TOCTOU 緩和)、bind mount EPERM は fail-safe (Sprint 006 PR D、Gemini G3-B1)
- **block_args の限界を docs に明記** — user-docs に抽象 warning、dev-docs (`docs/dev/security-notes.md`) に bypass 例 / URL scrub 設計根拠 / DB chmod 運用 / strict regex behavior change / policy_lock defer 分析を集約。agent self-jailbreak 対策で具体例は dev-only に分離 (Sprint 006 PR D、包括レビュー M-7)
- **mitmproxy addon の fail-closed 化** ([ADR 0005](docs/dev/adr/0005-fail-closed-addons.md)) — `policy_enforcer.py` の全 event hook (`request` / `response` / `websocket_message` / `websocket_end` / `done`) に fail-closed decorator を適用。addon 内で未捕捉例外が発生しても policy enforcement を bypass しない (Sprint 005 PR A、包括レビュー C-2 / Gemini 2.5 Pro 検出)
- **dashboard の Werkzeug debugger を撤去** — `docker-compose.yml` の `FLASK_DEBUG=1` + `flask run` override を削除し Dockerfile CMD の `gunicorn` に戻す。`/console` 経由の任意 Python REPL 経路を遮断 (Sprint 005 PR B、包括レビュー C-1)
- **dashboard CSRF 対策** — Flask-WTF CSRFProtect 導入。全 POST endpoint で `X-CSRFToken` ヘッダ or form token 検証。HTMX からは `<body hx-headers='{"X-CSRFToken": ...}'>` で自動送出、bulk 用 fetch() は meta tag から読取 (Sprint 005 PR B、包括レビュー H-1)
- **inbox record_id の path traversal 対策** — `policy_inbox.mark_status` に strict regex 検証 (`^[A-Za-z0-9T:_-]+$`) と `path.resolve().is_relative_to(inbox_resolved)` の 2 段防御。dashboard 側でも API 層で同 regex 検証 (Sprint 005 PR B、包括レビュー H-2)
- **inbox.html 属性 injection / XSS 対策** — `hx-vals` を `|tojson|forceescape` で JSON-safe に。`policy_inbox.list_requests` 側でも glob 取得時に stem を filter (Sprint 005 PR B、包括レビュー H-4)
- **dashboard セキュリティヘッダ群** — `Content-Security-Policy` (default-src 'self' / frame-ancestors 'none' / base-uri 'none' / object-src 'none'), `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer` を全レスポンスに付与 (Sprint 005 PR B、Gemini G-2)
- **dashboard Host ヘッダ whitelist (DNS rebinding 対策)** — `127.0.0.1` / `localhost` 以外の Host ヘッダは 400。`DASHBOARD_ALLOWED_HOSTS` env で override 可能 (Sprint 005 PR B、Gemini G3-B2)
- **proxy / dashboard / dns コンテナの container hardening** — `cap_drop: [ALL]` + `security_opt: [no-new-privileges:true]` + 非 root `user` 指定。agent コンテナと同等の最小権限化で、container escape や policy 改変の攻撃面を縮小 (Sprint 005 PR C、包括レビュー H-3)

### Added
- **Policy Inbox** ([ADR 0001](docs/dev/adr/0001-policy-inbox.md)) — agent が必要な許可 request を `<workspace>/.zoo/inbox/<id>.toml` に submit、dashboard で accept すると `policy.runtime.toml` に自動反映 (Sprint 001)
- **`bundle/` source / `.zoo/` 配布の命名分離** ([ADR 0002](docs/dev/adr/0002-dot-zoo-workspace-layout.md)) — user workspace が clean に保たれる (Sprint 002)
- `zoo bash` — コンテナ内に対話 shell
- `zoo proxy <agent>` — host CLI に proxy 環境を注入して exec
- `zoo` CLI (typer ベース) — 全機能をサブコマンド化
- Python API (`zoo.run`, `zoo.task`, `zoo.up`, `zoo.down`, ...)
- `zoo init [DIR]` — `<DIR>/.zoo/` 配下に harness 一式を展開 + `<DIR>/.gitignore` 生成
- Gemini CLI 対応（`AGENT=gemini` / `bundle/container/Dockerfile.gemini`）
- **Unified イメージ**（`Dockerfile.unified`、cross-agent 呼び出し用、#27）
- 共通 base イメージ `agent-zoo-base:latest` と base+agent の二段ビルド
- GitHub Actions CI (`.github/workflows/ci.yml`) — `unit` (Python 3.11/3.12/3.13 matrix) + `e2e-dashboard` (P1) を毎 PR + main push で自動実行、`e2e-proxy` (P2) は main push (merge 後) のみ。docs / LICENSE / logo のみの変更時は `paths-ignore` で skip
- PR テンプレート (`.github/pull_request_template.md`) — 動作確認 checklist
- PyPI 公開用のメタデータ（classifiers, urls, license など）
- Release workflow に TestPyPI デプロイ対応 — `workflow_dispatch` の `target` 入力で `none` / `testpypi` を選択可能。本番 PyPI へのリリースは `v*.*.*` タグ push 専用とし、手動実行からの本番公開経路は塞いでいる

### Changed
- **dashboard domain validation を strict 化 (behavior change)** — UI 経由で `localhost` / 単一ラベル host / TLD-only wildcard (`*.com`) / 連続 dot / leading-trailing hyphen / 多段 wildcard を追加できなくなる。これらを使いたい場合は base `policy.toml` を直接編集する。詳細は [docs/dev/security-notes.md](docs/dev/security-notes.md) (Sprint 006 PR D、包括レビュー M-5)
- **log DB の URL 列に query / fragment / userinfo が保存されなくなる** — Sprint 006 PR D 以前に保存された row はそのまま残る。clean したい場合は `zoo logs clear` を実行してください
- **新 status `URL_SECRET_BLOCKED` / `BODY_TOO_LARGE` を block 集計に追加** — dashboard の "blocked" カウント / whitelist candidate 抽出に反映。新 status の event は `blocks` テーブルにも転記される
- **Workspace layout を `.zoo/` 集約に移行** — `zoo init` は `<workspace>/.zoo/` 配下に展開（ADR 0002）
- docs を **`docs/user/`（利用者向け）と `docs/dev/`（開発者向け）に分離**
- Docker compose 操作を **`zoo` CLI に一本化** — Makefile は source repo / 配布物ともに含めない
- CI `paths-ignore` を root .md whitelist 方式に変更（`**.md` glob だと `bundle/templates/HARNESS_RULES.md` の変更が CI を通らなかった）
- CI `unit` / `e2e-*` jobs の uv cache を `actions/cache@v4` 明示 key（Python matrix 毎に独立）+ `restore-keys` で partial restore 対応
- CI `workflow_dispatch: {}` 追加で任意 branch から手動実行可能に
- `tests/e2e/test_proxy_block.py::proxy_up` fixture を try/finally で保護し、`up -d` 失敗時も `docker compose down` が走るよう修正、healthcheck timeout 時は `docker compose logs` 添えで `pytest.fail`
- `pyproject.toml` を hatchling ビルドに切り替え、assets を `bundle/` から `zoo/_assets/.zoo/` へ map
- Release workflow に `concurrency` グループを追加し、同一 ref での重複実行を直列化

### Removed
- `bundle/Makefile` — maintainer 用の Docker compose 操作も `zoo build` / `zoo run` / `zoo reload` 等で代替（ADR 0002 D5 の最終状態）
- `zoo test smoke` コマンド — Makefile 依存だったため削除。同等の疎通確認は E2E P2 (`tests/e2e/test_proxy_block.py`) でカバー済みのため再実装しない
- `policy_candidate.toml` 経路（Sprint 002 D8）— inbox に完全移行、互換層も削除
- `docs/codex-integration.md` / `.en.md` — maintainer 用ガイドとしての役目終了
- `ROADMAP.md` / `TODO.md` — `BACKLOG.md` に集約
- repo root の空 `data/` ディレクトリ — `.zoo/data/` に集約されたため不要

## [0.1.0] - TBD

初回リリース。
