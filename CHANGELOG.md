# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed
- **`zoo certs import` が `certs/extra/bundle.pem` を自動生成しない設計欠陥** — mitmproxy は上流 TLS 検証に `--set ssl_verify_upstream_trusted_ca=/certs/extra/bundle.pem` で単一 file path を要求するが、`certs_import` / `certs_remove` / `init` は個別 PEM file 操作のみで bundle への aggregate を行っておらず、user が手動で `cat *.pem > bundle.pem` しない限り自社サーバー (corporate private CA) への TLS handshake で cert chain 検証 fail していた。
  - `_rebuild_cert_bundle()` を新設、`certs/extra/` 内の全 user PEM (`.gitkeep` と `bundle.pem` 自身を除く) を結合して `bundle.pem` を自動再生成
  - `certs_import` / `certs_remove` の最後 + `init` (古い version で import 済 workspace への遡及適用) で呼ぶ
  - `bundle.pem` は予約名、`zoo certs import --name bundle.pem` / `zoo certs remove bundle.pem` は明示 error で reject
  - `zoo certs list` は `bundle.pem` を自動生成物として除外
  - CLI hint に "mitmproxy 稼働中なら `zoo down && zoo up` で再読込" 案内追加
  - 7 unit test (import / remove / list / 予約名 / init 遡及)

## [0.1.4] - 2026-04-20

v0.1.3 で dashboard を `FROM agent-zoo-base:latest` に切替えた副作用として、base の system python (Debian 系 `node:20-slim` + apt python3) が PEP 668 で externally-managed となり、dashboard の `pip install` が `externally-managed-environment` エラーで fail する問題を修正。

### Fixed
- **dashboard image build の PEP 668 エラー** — `bundle/container/Dockerfile.base` の apt install に `python3-venv` を追加 + `bundle/dashboard/Dockerfile` で `python3 -m venv /opt/venv` + `PATH=/opt/venv/bin:$PATH` を設定。dashboard 専用 virtualenv で pip install し、system python を汚さない (PEP 668 の意図通り)。`--break-system-packages` や `rm EXTERNALLY-MANAGED` の hacky 回避は採らない

## [0.1.3] - 2026-04-20

build 周辺の UX 改善 patch。corporate CA 配下での dashboard image build と、`zoo build` の layer cache 再ビルド option 追加。

### Added
- **`zoo build --no-cache`** — Docker image layer cache を skip して 0 から再 build する option。`uv tool upgrade agent-zoo` 後に Dockerfile の変更 (CA env 追加等) を確実に反映したい時に使う。`runner.build_base(no_cache=True)` で base image の `docker build` と `docker compose build` 双方に `--no-cache` を伝播。Dockerfile.base が欠損している場合は warning を出して skip (以前は silent return)。4 unit test (base + compose 伝播、default 挙動)

### Fixed
- **dashboard image の `pip install` が corporate CA 配下で TLS fail する問題** — `bundle/dashboard/Dockerfile` が `FROM python:3.12-slim` で独立 image だったため、v0.1.2 で `Dockerfile.base` に入れた CA plumbing (certs/extra COPY + update-ca-certificates + 4 env) が効かず pip の TLS 検証で fail していた。dashboard を `FROM agent-zoo-base:latest` に切り替え、CA plumbing を base に **single source of truth** で集約 (DRY)。`bundle/dashboard/.dockerignore` も新設し、bind mount 経由で runtime 生成される `__pycache__` / `*.pyc` を次回 build で image に焼かないよう除外

## [0.1.2] - 2026-04-20

user experience 改善 patch。初回 `zoo run` での image 未 build 時の挙動が分かりやすくなり、corporate root CA 下での `zoo build` も通るようになった。

### Changed
- **`zoo run` / `zoo up` / `zoo task` で Docker image 未 build 時の UX 改善** — 初回起動時 (または `zoo build` を忘れた時) に agent-zoo 系 image が未 build だと compose が registry pull を試みて `pull access denied` で落ちる問題を解決:
  - `docker-compose.yml` の agent service (`claude` / `codex` / `gemini` / `unified`) に `image: agent-zoo-<agent>:latest` + `pull_policy: never` を明示追加。registry pull 試行を抑止
  - `api.run` / `api.task` / `api.bash` / `api.up` の各 entry で `ensure_agent_images_built()` を呼び、`agent-zoo-base:latest` / `agent-zoo-<agent>:latest` の存在を `docker image inspect` で pre-check。無ければ English hint (`Run 'zoo build --agent <agent>' first`) を stderr に出して fail-fast。低レイヤ `runner.compose_up` からは呼ばず、単体 test の purity を保つ設計
- **Dockerfile.base に CA bundle env 追加 — corporate root CA 配下での `zoo build` を fix** — `certs/extra/` に企業 root CA を配置 + `update-ca-certificates` は system CA store (`/etc/ssl/certs/ca-certificates.crt`) に追加するが、**pip / Python requests / Node.js (npm) はそれぞれ自前 bundle (`certifi` / node built-in) を使う**ため、TLS 検証が fail して build 時の `npm install @anthropic-ai/claude-code` / `pip install` 等がエラーで止まる問題を解決。`Dockerfile.base` の `update-ca-certificates` 直後に `SSL_CERT_FILE` / `REQUESTS_CA_BUNDLE` / `PIP_CERT` / `NODE_EXTRA_CA_CERTS` の 4 つを system bundle path に向ける `ENV` を追加。base image から派生する agent image (claude / codex / gemini / unified) でも継承され、build 時 RUN + runtime の両方で TLS 解決が通る。5 unit test で regression 防止 (env の存在 + `update-ca-certificates` 後の順序 assert)

## [0.1.1] - 2026-04-20

初回 stable release (PyPI 公開)。中間 beta (`0.1.1b1` / `0.1.1b2`) を経て release workflow と 2-phase flow を固めた上での initial stable。

### Security
- **`zoo init --policy <profile>` で secure-by-default** ([#66](https://github.com/ymdarake/agent-zoo/issues/66)) — `zoo init` の default profile が `minimal` (空 allow list) になり、初期状態では全外向き通信が BLOCKED → Inbox に pending として積まれる。従来は Anthropic / OpenAI / Google の 13 domain が最初から allow されていたため、企業環境 / 高セキュリティ環境では意図せず provider への通信が通る状態だった。初体験を secure by default に転換 (breaking change、user 0 のため migration guide 不要)
- **dashboard 外部依存ゼロ化** ([ADR 0004](docs/dev/adr/0004-dashboard-external-deps-removal.md)) — pico.css / htmx.org の CDN 経由読込を完全撤去し、自前 HTML/CSS/vanilla JS (CSS ~284 行 + JS ~268 行) に移行。CDN 乗っ取り / unpkg リダイレクト改ざんによる任意 JS 注入経路を消滅 (Sprint 007 PR F〜I、包括レビュー M-1)
- **dashboard CSP `'self'` only に厳格化** — `'unsafe-inline'` / `https://cdn.jsdelivr.net` / `https://unpkg.com` を全 directive から削除、`form-action 'self'` 追加 (default-src の fallback 対象外、CSP3)。`response.headers["Content-Security-Policy"] = ...` で **強制上書き** に変更し他 layer の弱い CSP 不入を保証 (Sprint 007 PR I)
- **`Permissions-Policy: camera=(), microphone=(), geolocation=(), payment=()`** 追加 — defense-in-depth で不要な Browser API を全 deny (Sprint 007 PR I)
- **dashboard template から inline `<script>` / `<style>` / `style="..."` / `onclick=` を完全削除** — BS4 ベース test (`tests/test_dashboard_inline_assets.py` 11 件) で全 6 endpoint を assert、`<base>` / dns-prefetch / preconnect to CDN も全部不在を保証。Playwright route で CDN を強制 abort しても dashboard 全機能 PASS (`tests/e2e/test_dashboard_offline.py` 3 件、Sprint 007 PR H + I)
- **`<body hx-headers='...'>` 削除** — CDN htmx 経由の CSRF header 渡しを排除、自前 JS が `csrf()` helper で都度送出 (Sprint 007 PR H)
- **inbox.html attribute injection / XSS 完全防御** — `data-json-body="{{ {'record_id': r._id}|tojson|forceescape }}"` パターンで Jinja escape を強制、record_id 内の特殊文字でも JSON / HTML 両方 safe (Sprint 007 PR H、包括レビュー L-6 完全 resolved)
- **policy.toml の cross-container shared/exclusive lock** (`bundle/addons/_policy_lock.py` 新設) — proxy / dashboard 両方から writable な `/locks` bind mount 経由で `fcntl.flock` を取得し、`PolicyEngine._load` (reader = LOCK_SH) と `policy_edit` (writer = LOCK_EX) の TOCTOU を解決。reader = warn + passthrough、writer = raise の API 分離で ADR 0005 fail-closed と両立。`os.open(O_NOFOLLOW, 0o600)` で symlink 攻撃を抑止。`zoo init` で `.zoo/locks/` を自動生成 (Sprint 006 PR F、包括レビュー M-8)
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
- **release workflow: PEP 440 native tag の自動 routing + 整合チェック + 2-phase flow** ([#68](https://github.com/ymdarake/agent-zoo/issues/68)) — `v0.1.0a1` / `v0.1.0b1` / `v0.1.0rc1` 等の pre-release tag / stable tag (`v0.1.0`) を PEP 440 spec に沿って自動分類 (pre-release → 本番 PyPI `--pre` opt-in / stable → 本番 PyPI + GitHub Release)。build job で tag と `pyproject.toml` project.version の bit-for-bit 整合チェック (不一致 / 非 PEP 440 native / leading zero / `dynamic version` を fail-fast で reject)。pre-release 判定は `build.outputs.is_prerelease` で一元化し、GitHub Release の stable-only guard (`is_prerelease == 'false'`) で belt-and-suspenders。バージョンアップ作業は `make release-commit <V>` (release branch で pyproject bump + `:bookmark: release: v<V>` commit) → PR → squash merge → `make release-tag <V>` (main HEAD に annotated tag) の 2-phase flow で自動化。`release-tag` は **pyproject.version == VERSION + HEAD subject `release: v<V>` + HEAD == origin/main** の 3 precondition を fail-fast で verify し、orphan tag による本番 PyPI 暴発を防ぐ。`[project].version` は Python で section-aware に書き換え、`tomllib` で read-back verify、失敗 / SIGINT で rollback。運用詳細は [docs/dev/release-testing.md](docs/dev/release-testing.md)
- **`.github/PULL_REQUEST_TEMPLATE/release.md` 新設** — release PR 専用 checklist。`gh pr create --template release.md` で呼び出し、CHANGELOG / pyproject version 整合 / pre-release vs stable 判定 / PyPI yank / Trusted Publisher tag filter / rollback 手順を忘れず確認できるようにする
- **`zoo init --policy <minimal|claude|codex|gemini|all>`** ([#66](https://github.com/ymdarake/agent-zoo/issues/66)) — 初期ポリシーを profile 選択可能に。`bundle/policy/*.toml` 5 profile を wheel に同梱し、init 時に `<workspace>/.zoo/policy.toml` へ書き出す。profile 差分は `domains.allow.list` / `paths.allow` / `rate_limits` のみで、`payload_rules` / `tool_use_rules` / `alerts` は全 profile 共通
  - Python: `zoo.init(target, *, force, policy="minimal")` / `zoo.PolicyProfile` Enum を公開 (str subclass)
  - 生成 policy.toml の先頭にメタデータコメント (`# Generated by zoo init --policy X`) を付与、再 init hint を明記
  - 既存 `.zoo/policy.toml` は `--force` 未指定なら保持、CLI は yellow hint で明示
  - 44 unit test (profile 内容 35 件 + init behavior 11 件 + CLI smoke 5 件)
- **`zoo certs import / list / remove`** ([#64](https://github.com/ymdarake/agent-zoo/issues/64)) — 企業 root CA cert を `<workspace>/.zoo/certs/extra/` に管理する CLI / Python API。`zoo certs` (no arg) は従来どおり mitmproxy CA 生成 (typer sub-app callback で後方互換維持)。
  - PEM ヘッダ検証 + 拡張子 whitelist (`.pem` / `.crt` / `.cer`) + path traversal 防御 (`.gitkeep` 保護 / `/`, `\`, `\x00`, `..` reject)
  - symlink を target に resolve、dest が dir の場合は ValueError、同一 inode の再 import は no-op
  - 上書きには `--force`、新 cert を image に取り込むには `zoo build --no-cache` 必須 (CLI に yellow 警告)
  - Python: `zoo.certs_import(src, *, name, force) -> Path` / `zoo.certs_list() -> list[str]` / `zoo.certs_remove(name) -> bool`
  - 27 unit test (CLI smoke 3 件 + PEM header 整合性 1 件含む)
- **dashboard 自前 CSS/JS 基盤** — `bundle/dashboard/static/app.css` (design tokens 9 + status badge tokens 6 + layout / table / form / button / status badge / tab nav / spinner / utility) + `bundle/dashboard/static/app.js` (declarative data-* API: `data-poll-url` / `data-poll-interval` / `data-swap-target` / `data-trigger-from` / `data-include` / `data-confirm` / `data-json-body` / `data-tab` / `data-bulk-action` / `data-bulk-toggle-all` / `data-suggest-target`)。MutationObserver で partial swap 後の再 attach + cleanup、exponential backoff (base × 2^failures、最大 60s)、aria-* a11y 補強 (Sprint 007 PR G + H)
- **`ASSET_VERSION` env による cache busting** — `app.config["ASSET_VERSION"]` + `@app.context_processor` 注入で `<link href=".../app.css?v={{ asset_version }}">` を defensive Jinja で出力 (Sprint 007 PR G + H)
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

### Changed
- **release workflow: pre-release tag を本番 PyPI publish に統一 (PEP 440 流儀)** ([#68](https://github.com/ymdarake/agent-zoo/issues/68) follow-up) — breaking change。`v0.1.0b1` / `v0.1.0rc1` 等の pre-release tag push で **本番 PyPI に publish** される (中間 flow で TestPyPI 経由だった経路を撤去)。user 側 install は `pip install --pre agent-zoo==<VERSION>` / `uv tool install --prerelease=allow agent-zoo==<VERSION>`。人間 gate は `environment: pypi` の required reviewers (public repo 前提、[#73](https://github.com/ymdarake/agent-zoo/issues/73))。TestPyPI は `workflow_dispatch` (target=testpypi) からの手動発火 = publish workflow デバッグ専用に縮退 (tag push 経路は撤去)。GitHub Release は stable のみ自動作成 (pre-release の release notes は CHANGELOG / PyPI description / 手動 `gh release create --prerelease`)。既存 `v0.1.1b1` は TestPyPI 側にのみ残留 (backfill なし、次 beta から新 flow)。PyPI Trusted Publisher は workflow + environment で OIDC gate する (tag ref filter は PyPI 側に無い、PEP 440 spec 遵守は release.yml の Classify step が担う)
- **`bundle/policy.toml` → `bundle/policy/*.toml` 5 profile に分離** ([#66](https://github.com/ymdarake/agent-zoo/issues/66)) — breaking change。旧 `bundle/policy.toml` と等価な内容は `bundle/policy/all.toml` に移行。`zoo init --policy all` で旧 default 相当を復元可能
- **dashboard template を `hx-*` から `data-*` に全書換** — 全 partial / index.html の HTMX 23 出現 / 9 種類を vanilla JS の declarative data-* API に置換、pico class を自前 class 体系 (`.layout-container` / `.btn-secondary` / `.btn-contrast` / `.btn-outline` 等) に統一 (Sprint 007 PR H、ADR 0004)
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
- **dashboard CDN 依存 (pico.css / htmx.org)** — `https://cdn.jsdelivr.net/npm/@picocss/pico@2/...` と `https://unpkg.com/htmx.org@2.0.4` の `<link>` / `<script>` を削除。CSP 上の CDN ホスト許可も削除し `'self'` only に (Sprint 007 PR I、包括レビュー M-1)
- **dashboard 全 inline asset** — `<script>showTab/bulkInbox/...</script>` / `<style>...</style>` / `style="..."` 属性 / `onclick=` を全 partial / index.html から完全削除、`static/app.css` + `static/app.js` に集約 (Sprint 007 PR H、CSP `'unsafe-inline'` 撤去の前提条件)
- `bundle/Makefile` — maintainer 用の Docker compose 操作も `zoo build` / `zoo run` / `zoo reload` 等で代替（ADR 0002 D5 の最終状態）
- `zoo test smoke` コマンド — Makefile 依存だったため削除。同等の疎通確認は E2E P2 (`tests/e2e/test_proxy_block.py`) でカバー済みのため再実装しない
- `policy_candidate.toml` 経路（Sprint 002 D8）— inbox に完全移行、互換層も削除
- `docs/codex-integration.md` / `.en.md` — maintainer 用ガイドとしての役目終了
- `ROADMAP.md` / `TODO.md` — `BACKLOG.md` に集約
- repo root の空 `data/` ディレクトリ — `.zoo/data/` に集約されたため不要

初回リリース。
