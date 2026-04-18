# 2026-04-18 時点: 統合作業計画書（Work Breakdown）

| 項目 | 値 |
|---|---|
| 作成日 | 2026-04-18 |
| 対象範囲 | [2026-04-18 包括レビュー](../dev/reviews/2026-04-18-comprehensive-review.md) の全指摘 + [BACKLOG.md](../../BACKLOG.md) active items |
| 総 Sprint 数 | 5（Sprint 004〜008） |
| 想定期間 | 約 2〜3 週間（Sprint 007 の大きさ次第） |
| リリース milestone | Sprint 005 完了 = Alpha release 可 / Sprint 007 完了 = Beta / Sprint 008 完了 = 1.0 候補 |

---

## エグゼクティブサマリ

| # | Sprint | テーマ | 規模 | 期間見積 | ブロッカー |
|---|---|---|---|---|---|
| **004** | Docs/CI Cleanup | 当日作業の不整合 + CI の小修正 | 11 PR 項目を 1 PR | 半日 | なし（即着手可） |
| **005** | Critical Security Fix | リリース blocker (C-1, C-2, H-1〜H-4) | 3 PR | 2〜3 日 | **publish blocker** |
| **006** | Security Hardening | Medium 指摘 (M-2〜M-8) + サプライチェーン | 2 PR | 2 日 | 005 完了後 |
| **007** | Dashboard 外部依存ゼロ化 | pico/htmx → 自前 HTML/CSS/JS (ADR 0004) | 4 PR | 1〜2 週間 | 005 完了後（CSRF 済前提） |
| **008** | Low polish + 残務 | Low 指摘 + 監査外 followup | 1 PR | 1 日 | なし |

並列化の余地: 005 と 007 の設計 (ADR 0004) は並行で進められる。006 は 005 完了後。

---

## 依存関係 / ブロッカーチェーン

```
Sprint 004 (Docs/CI Cleanup)  ─┐
                                ├→ 着手: 並行で OK、どれから始めても可
Sprint 005 (Critical)          ─┤
                                └→ 完了で Alpha リリース可能

Sprint 005 完了 → Sprint 006 (Medium Hardening)
               → Sprint 007 (Dashboard rewrite) ← CSRF が入っていないと書換えで漏れる

Sprint 006 + 007 完了 → Beta リリース

Sprint 008 (Polish) → 1.0 候補

別 phase:
- #31 user smoke (user 環境依存)
- #32 README screenshots (user 環境依存)
- #34 E2E P3 real agent (Sprint 007 後)
- #35 inbox agent script (要 grooming)
```

---

## Sprint 004: Docs / CI Integrity Cleanup（半日、1 PR）

### ゴール

Sprint 003 で発生した **docs / CI の小さな不整合** を一気に解消。リスク低、影響小、着手即可能。

### 作業単位（すべて 1 PR）

#### P004-1. `docs/dev/python-api.md` から削除済 API 参照除去（H1）

- `docs/dev/python-api.md:52` の `/ zoo.test_smoke(*, agent)` を削除
- **検証**: grep で `test_smoke` が消えたことを確認

#### P004-2. `CLAUDE.md` 構造図を実態に合わせる（H2）

- L26: `│   ├── Makefile              # maintainer 専用...` 行削除
- L31: `│   └── host/, dns/, certs/, data/` → `│   └── host/, dns/, certs/` に修正
- **検証**: `ls bundle/` と diff、乖離なきことを目視確認

#### P004-3. CI `e2e-proxy` の前提ファイル touch（H3）

- `.github/workflows/ci.yml` の `e2e-proxy` job の `Build base image` 直前に `run: touch bundle/policy.runtime.toml` 追加
- **代替**: `tests/e2e/test_proxy_block.py::proxy_up` 冒頭で `(BUNDLE / "policy.runtime.toml").touch(exist_ok=True)` も可
- **検証**: 次 main push で `e2e-proxy` job が green であること

#### P004-4. `paths-ignore` を明示化、`HARNESS_RULES.md` を CI 対象に（H4 旧 M1）

- 現行: `paths-ignore: ['**.md', 'docs/**', 'LICENSE', 'logo.svg']`
- 新: `paths-ignore: ['README*.md', 'CHANGELOG.md', 'BACKLOG.md', 'CLAUDE.md', 'docs/**', 'LICENSE', 'logo.svg']`
- **検証**: `bundle/templates/HARNESS_RULES.md` を typo 修正するだけの PR で CI が走ることを次 PR で実機確認

#### P004-5. E2E `proxy_up` healthcheck 強化（M2）

- `tests/e2e/test_proxy_block.py` の `proxy_up` fixture で healthcheck loop 末尾に `else: pytest.fail("proxy did not become healthy in 30s")`
- **検証**: unit test で healthcheck fail 時に pytest.fail されることを確認（難しければ目視レビュー）

#### P004-6. `conftest.py` の `__import__("os")` を通常 import に（M3）

- `tests/e2e/conftest.py` と `test_proxy_block.py` の冒頭に `import os` 追加、`__import__("os")` を全て `os.` に置換
- **検証**: `make e2e` が通る

#### P004-7. PR template 文言整理（M4）

- `.github/pull_request_template.md` の checklist から「CI で自動実行」注記を削除
- ローカル確認要件は文面から削除、CI 結果に一任

#### P004-8. Sprint 003 archive の `<next>` placeholder 置換（M5）

- `docs/dev/sprints/003-e2e-foundation-and-zoo-cli-unification.md:113` の `<next>` を `9f78e5a` に置換

#### P004-9. CI に `workflow_dispatch` 追加（M6 / Gemini G-1）

- `ci.yml` の `on:` に `workflow_dispatch: {}` 追加
- **検証**: GitHub Actions UI で "Run workflow" ボタンが出ることを目視

#### P004-10. uv cache key に Python version を含める（M7 / Gemini G-2）

- `setup-uv@v7` の `enable-cache: true` を外し、`actions/cache@v4` で明示キー化
- Key: `${{ runner.os }}-py-${{ matrix.python-version }}-uv-${{ hashFiles('uv.lock') }}`
- **検証**: matrix 3 版が独立 cache に入ることを Actions log で確認

#### P004-11. root `Makefile` の責務コメント追加（M8 / Gemini G-2/G3-A2）

- Makefile 冒頭に責務明記: 「dev 環境専用、GitHub Actions workflows のエイリアス」
- `bundle/Makefile` 撤去との関係を明示

#### P004-12. `Dockerfile.base` を `uv.lock` ベースに（Gemini G3-A1、optional）

- `bundle/container/Dockerfile.base` に `COPY uv.lock pyproject.toml ./` と `uv sync --frozen` を追加
- **Note**: agent-zoo-base は Python ランタイムではないので不要の可能性あり。先に要否検証してから判断
- **本 sprint では保留**、Sprint 006 (supply chain) で判断

### 受入基準（Sprint 004）

- [ ] 上記 P004-1〜11 すべて反映
- [ ] `make unit` / `make e2e` 全 PASS
- [ ] CI で docs-only PR が skip される、src PR では走る動作を実機確認
- [ ] 包括レビューの H1〜H4 / M1〜M8 が resolved

---

## Sprint 005: Critical Security Fix（2〜3 日、3 PR）

### ゴール

**リリース blocker（Critical 2 件 + High 4 件）の完全解消**。これが終わるまで PyPI publish は不可。

### PR A: mitmproxy addon fail-closed 化（C-2）

#### スコープ

mitmproxy addon で未捕捉例外が起きたときに **デフォルト pass-through（fail-open）** してしまう仕様を、**fail-closed** に修正する。

#### 作業単位

##### P005A-1. fail-closed 共通デコレータを実装

- `bundle/addons/_fail_closed.py` 新設
- 関数デコレータ `@fail_closed_http(flow_arg=0)` を実装:
  ```python
  def fail_closed_http(flow_arg=0):
      """mitmproxy event handler 用: 例外時は flow.kill() + log"""
      def decorator(fn):
          @functools.wraps(fn)
          def wrapper(*args, **kwargs):
              try:
                  return fn(*args, **kwargs)
              except Exception as e:
                  flow = args[flow_arg]
                  ctx.log.error(f"addon {fn.__name__} raised {type(e).__name__}: {e}")
                  try:
                      flow.kill()
                  except Exception:
                      pass
                  # 追加: DB に alert 記録（addon bypass attempt として）
                  return None
          return wrapper
      return decorator
  ```

##### P005A-2. 既存 addon に適用

対象関数（requestment / response hook）:
- `bundle/addons/policy.py`: `request(self, flow)`, `response(self, flow)`
- `bundle/addons/policy_enforcer.py`: `request(self, flow)`, `response(self, flow)`, `done(self)`
- `bundle/addons/sse_parser.py`: 全 public hooks
- `bundle/addons/policy_inbox.py`: hook があれば対象

**各関数の先頭に `@fail_closed_http()` を付与**。

##### P005A-3. テスト追加

- `tests/test_addon_fail_closed.py` 新設
- ケース:
  1. 正常系: 例外無しで `flow.kill()` が呼ばれないこと
  2. 異常系: addon 内で `raise KeyError` → `flow.kill()` が 1 回呼ばれること
  3. ログに error が出ること（caplog で assert）
  4. 後続 addon が呼ばれるか（mitmproxy のコア挙動確認）

##### P005A-4. docs 更新

- `docs/dev/architecture.md` に「Fail-closed 設計」セクションを追加
- `bundle/addons/README.md` があれば同様（なければ新設）

#### 受入基準（PR A）

- [ ] 全 addon の public hook が `@fail_closed_http` 適用
- [ ] 新規 4 テスト PASS
- [ ] 既存 234 unit + 7 E2E P1 PASS
- [ ] `make e2e-all` で P2 も通ることを maintainer 環境で確認
- [ ] ログに「addon raised」メッセージが出ることを目視確認

---

### PR B: Dashboard セキュリティ包括対応（C-1, H-1, H-2, H-4, G3-B2, G-2）

#### スコープ

dashboard の Web 脆弱性を一括で修正。Werkzeug debugger 無効化、CSRF 対策、path traversal、XSS、CSP、DNS rebinding Strict Host。

#### 作業単位

##### P005B-1. FLASK_DEBUG 撤去、gunicorn 復元（C-1）

- `bundle/docker-compose.yml:141-142` の `FLASK_DEBUG=1` および `command: [flask run ...]` を削除
- Dockerfile 既定の `gunicorn` CMD に戻す
- 開発用は `bundle/docker-compose.override.yml` に分離（未コミット、.gitignore に追加）

##### P005B-2. CSRF 対策導入（H-1）

- **採用方針**: Flask-WTF の `CSRFProtect` + HTMX 連携
- `pyproject.toml` 依存に `flask-wtf>=1.2` 追加
- `bundle/dashboard/app.py`:
  ```python
  from flask_wtf.csrf import CSRFProtect, generate_csrf
  csrf = CSRFProtect(app)

  @app.after_request
  def inject_csrf_cookie(response):
      response.set_cookie("csrf_token", generate_csrf(), samesite="Strict")
      return response
  ```
- `bundle/dashboard/templates/index.html`:
  ```html
  <meta name="csrf-token" content="{{ csrf_token() }}">
  <body hx-headers='{"X-CSRFToken": "{{ csrf_token() }}"}'>
  ```
- テスト: `tests/test_dashboard.py` に「CSRF token 無しの POST は 400」「token 有りで 200」のケースを追加

##### P005B-3. path traversal 対策（H-2）

- `bundle/dashboard/app.py::api_inbox_reject` / `api_inbox_bulk_reject` で `record_id` を strict validate:
  ```python
  _RECORD_ID_RE = re.compile(r"^[A-Za-z0-9:T_-]+$")
  if not _RECORD_ID_RE.match(record_id):
      return "invalid record_id", 400
  ```
- `bundle/addons/policy_inbox.py::mark_status` 内でも第 2 防御として `path.resolve().is_relative_to(Path(inbox_dir).resolve())` チェックを追加
- テスト: `record_id="../evil"` / `record_id="../../etc/passwd"` で 400 が返ること

##### P005B-4. inbox.html の属性 injection 対策（H-4）

- `bundle/dashboard/templates/partials/inbox.html:28, 32`:
  ```html
  <!-- Before -->
  <form ... hx-vals='{"record_id": "{{ r._id }}"}'>
  <!-- After -->
  <form ... hx-vals="{{ {'record_id': r._id}|tojson|forceescape }}">
  ```
- glob で inbox file 名を取る際に stem を validate:
  ```python
  # bundle/addons/policy_inbox.py::list_requests
  if not _RECORD_ID_RE.match(stem):
      continue  # skip malformed
  ```

##### P005B-5. Content-Security-Policy ヘッダ追加（G-2）

- `bundle/dashboard/app.py` の `@app.after_request`:
  ```python
  response.headers["Content-Security-Policy"] = (
      "default-src 'self'; "
      "style-src 'self' https://cdn.jsdelivr.net; "  # 自前化後は 'self' のみ
      "script-src 'self' https://unpkg.com; "
      "img-src 'self' data:; "
      "connect-src 'self'"
  )
  ```
- **注**: Sprint 007 で自前実装したら CDN ドメインを remove

##### P005B-6. Strict Host middleware（Gemini G3-B2）

- DNS rebinding 対策。`bundle/dashboard/app.py` の `@app.before_request`:
  ```python
  _ALLOWED_HOSTS = {"127.0.0.1", "localhost"}
  @app.before_request
  def check_host():
      host = request.host.split(":")[0]
      if host not in _ALLOWED_HOSTS:
          abort(400, "Invalid Host header")
  ```
- テスト: `Host: evil.com` で 400 が返ること

#### 受入基準（PR B）

- [ ] `FLASK_DEBUG=1` / `flask run` override が削除済
- [ ] CSRF token 無しの全 POST が 400
- [ ] `record_id="../*"` で 400
- [ ] 悪意 file 名の inbox エントリは dashboard から見えない
- [ ] `Content-Security-Policy` ヘッダ付与済
- [ ] `Host: evil.com` で 400
- [ ] 既存 234 unit + 7 E2E P1 全 PASS
- [ ] 新規テスト 4〜5 件追加

---

### PR C: コンテナ hardening（H-3）

#### スコープ

`proxy` / `dashboard` / `dns` コンテナに `cap_drop: [ALL]` + `security_opt: no-new-privileges` + `user:` を追加。

#### 作業単位

##### P005C-1. docker-compose.yml に security 設定追加

- `bundle/docker-compose.yml` の proxy / dashboard / dns service に:
  ```yaml
  cap_drop: [ALL]
  security_opt:
    - no-new-privileges:true
  user: "${HOST_UID:-1001}:${HOST_UID:-1001}"
  ```
- 必要 cap のみ `cap_add:` で復活（mitmproxy が NET_BIND_SERVICE 必要なら追加）

##### P005C-2. 動作確認

- `zoo build` → `zoo run` で全 service 起動できること
- `docker compose exec dashboard whoami` で非 root であること
- `ps aux` で各プロセスが非 root であること

##### P005C-3. maestro E2E P2 で回帰確認

- `tests/e2e/test_proxy_block.py` の 3 ケースが通ること

#### 受入基準（PR C）

- [ ] 全 service が非 root で起動
- [ ] `cap_drop: [ALL]` 適用済
- [ ] `no-new-privileges` 適用済
- [ ] E2E P2 全 PASS

---

### Sprint 005 全体の受入基準

- [ ] PR A, B, C すべて merge
- [ ] 包括レビューの Critical / High すべて resolved
- [ ] user 環境で `zoo build` → `zoo run` が動くこと
- [ ] Alpha release candidate として PyPI publish 可

---

## Sprint 006: Security Hardening（2 日、2 PR）

### ゴール

Medium 指摘をまとめて片付ける。サプライチェーン hardening を含む。

### PR D: ポリシー adjacent セキュリティ

#### 作業単位

##### P006D-1. URL の query strip（M-2, G3-B1）

- `bundle/addons/policy_enforcer.py` で `flow.request.url` 保存前に `urllib.parse.urlsplit` → query 除去版を使う
- 関連: `secret_patterns` を URL にも適用（policy.toml に `apply_to = ["body", "url"]` 追加）
- テスト: `?api_key=secret` 付き URL が DB から secret_patterns で masked / 除外されること

##### P006D-2. `_validate_domain` strict regex 化（M-5）

- `bundle/dashboard/app.py` の `_DOMAIN_RE` を RFC 準拠寄りに:
  ```python
  _LABEL_RE = r"(?!-)[A-Za-z0-9-]{1,63}(?<!-)"
  _DOMAIN_RE = re.compile(
      rf"^(\*\.)?({_LABEL_RE}\.)+{_LABEL_RE}$"
  )
  ```
- テスト: `*.com` / `a..com` / `a-.com` / `localhost` が reject されること

##### P006D-3. mitmproxy `body_size_limit` 設定（M-6）

- `bundle/docker-compose.yml` の proxy service の `command` に `--set body_size_limit=1m` 追加
- テスト: 1 MB 超 request が proxy でブロックされること（E2E に追加、P2）

##### P006D-4. `block_args` 限界 docs 化（M-7）

- `docs/user/policy-reference.md` の tool_use_rules セクションに警告 box:
  > ⚠ `block_args` は文字列マッチで bypass 容易（`rm -rf /` vs `/bin/rm -rf /` 等）。最終防衛は network isolation。

##### P006D-5. `policy_enforcer.load_policy` に LOCK_SH（M-8）

- `bundle/addons/policy_enforcer.py::load_policy` で `fcntl.flock(f, fcntl.LOCK_SH)` を追加
- `policy_edit.py` の `LOCK_EX` と協調
- テスト: 並行 read / write で競合が起きないこと

##### P006D-6. harness.db file 権限 600 強制（Gemini G3-B1）

- `bundle/addons/policy_enforcer.py` で DB ファイル作成後に `os.chmod(db_path, 0o600)`
- テスト: DB ファイルのパーミッションが 600 であること

#### 受入基準（PR D）

- [ ] M-2, M-5, M-6, M-7, M-8, G3-B1 すべて反映
- [ ] 新規テスト 5 件追加
- [ ] 全 unit + E2E PASS

---

### PR E: サプライチェーン hardening

#### 作業単位

##### P006E-1. Docker image SHA pin（M-3）

- `bundle/container/Dockerfile.base`: `FROM node:20-slim@sha256:...`
- `bundle/dashboard/Dockerfile`: `FROM python:3.12-slim@sha256:...`
- `bundle/docker-compose.yml`: `image: mitmproxy/mitmproxy:10@sha256:...`, `coredns/coredns:1.11.4@sha256:...`

##### P006E-2. GitHub Actions SHA pin（M-4）

- `.github/workflows/ci.yml` / `release.yml` の全 `uses:` を commit SHA に変更
- コメントで版数併記: `uses: actions/checkout@abc123  # v5.0.1`

##### P006E-3. Dependabot 設定追加

- `.github/dependabot.yml` 新設:
  ```yaml
  version: 2
  updates:
    - package-ecosystem: "github-actions"
      directory: "/"
      schedule:
        interval: "weekly"
    - package-ecosystem: "docker"
      directory: "/bundle/container"
      schedule:
        interval: "weekly"
    - package-ecosystem: "pip"
      directory: "/"
      schedule:
        interval: "weekly"
  ```

##### P006E-4. pip-audit を CI に統合

- `ci.yml` の `unit` job に step 追加:
  ```yaml
  - name: pip-audit
    run: uv run pip-audit --strict
  ```

#### 受入基準（PR E）

- [ ] 全 image が SHA pin 済
- [ ] 全 GitHub Actions が SHA pin 済
- [ ] `pip-audit` が CI で走る
- [ ] Dependabot PR が週次で立ち始める（運用開始）

---

## Sprint 007: Dashboard 外部依存ゼロ化（1〜2 週間、4 PR + ADR）

### ゴール

pico.css / htmx.org を撤去し、自前 HTML/CSS/vanilla JS に完全移行。規模見積: テンプレート書換 ~500 行、CSS ~300 行、JS ~50 行。

### PR F: ADR 0004 + 設計

#### 作業単位

##### P007F-1. ADR 0004「Dashboard 外部依存ゼロ化」起票

- `docs/dev/adr/0004-dashboard-external-deps-removal.md` 新設
- 内容:
  - Context: サプライチェーンリスク、CSP 厳格化の前提
  - Decision: 自前実装、最小機能に絞る
  - 必要な HTMX 機能のリスト (`hx-post` / `hx-target` / `hx-swap` / `hx-vals` / `hx-confirm` / `hx-trigger`)
  - vanilla JS API 設計:
    ```js
    // form.addEventListener('submit', async (ev) => {
    //   ev.preventDefault();
    //   const res = await fetch(form.action, { method: 'POST', body: new FormData(form) });
    //   document.querySelector(form.dataset.target).innerHTML = await res.text();
    // });
    ```
  - CSS design tokens（spacing scale、color palette）

##### P007F-2. 現行 dashboard の HTMX 属性棚卸し

- `bundle/dashboard/templates/` 配下の全 `hx-*` 属性を列挙
- 各属性の vanilla JS 実装方針を ADR に併記

#### 受入基準（PR F）

- [ ] ADR 0004 merged
- [ ] HTMX 機能棚卸し表が ADR に含まれる

---

### PR G: 自前 CSS + vanilla JS 基盤

#### 作業単位

##### P007G-1. `bundle/dashboard/static/app.css` 作成（~300 行）

- design tokens、layout、component styles（article, table, form, button 等）
- pico の使用 class だけを selective に書き直す

##### P007G-2. `bundle/dashboard/static/app.js` 作成（~50 行）

- `fetch`-based form submission
- `innerHTML` swap
- confirm dialog
- target resolution (`data-target="#id"` で置換)

##### P007G-3. Flask で static serving を有効化

- Flask の default static serving で `/static/app.css` / `/static/app.js` を提供

#### 受入基準（PR G）

- [ ] `/static/app.css` / `/static/app.js` が配信される
- [ ] 単体の JS unit test (jest / playwright script test) で fetch mock テスト 3 件

---

### PR H: テンプレート書換え（メイン作業）

#### 作業単位

##### P007H-1. `index.html` の書換え

- `<link rel="stylesheet" href="https://cdn.jsdelivr.net/...">` → `<link rel="stylesheet" href="/static/app.css">`
- `<script src="https://unpkg.com/htmx.org@2.0.4">` → `<script defer src="/static/app.js"></script>`

##### P007H-2. 各 partial テンプレートの書換え

対象ファイル（予想）:
- `bundle/dashboard/templates/partials/inbox.html`
- `bundle/dashboard/templates/partials/whitelist.html`
- `bundle/dashboard/templates/partials/requests.html`
- `bundle/dashboard/templates/partials/tool_uses.html`

各 `hx-post="/path" hx-target="#id" hx-swap="innerHTML"` を:
```html
<form action="/path" method="POST" data-target="#id">
  ...
</form>
```
に書換え。JS 側で `data-target` を拾って swap。

##### P007H-3. confirm dialog 対応

- `hx-confirm="..."` → `data-confirm="..."`
- JS 側で `if (form.dataset.confirm && !confirm(form.dataset.confirm)) return;`

#### 受入基準（PR H）

- [ ] 全テンプレから `hx-*` 属性完全除去
- [ ] 全テンプレから `pico.css` class 依存完全除去（自前 class 体系に統一）
- [ ] E2E P1 7 ケース全て PASS（selector 調整必要）

---

### PR I: CDN 参照削除 + CSP 厳格化

#### 作業単位

##### P007I-1. CDN link 削除

- `index.html` から `cdn.jsdelivr.net` / `unpkg.com` の link / script 完全除去

##### P007I-2. Content-Security-Policy を厳格化

- PR B (P005B-5) で入れた CSP の `style-src` / `script-src` から CDN ドメインを除去
- `default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'`

##### P007I-3. E2E P1 再検証

- `make e2e` で dashboard 7 ケース全 PASS
- selector の変更があれば調整

##### P007I-4. 包括レビュー M-1 / L-6 を resolved にマーク

- `docs/dev/reviews/2026-04-18-comprehensive-review.md` の M-1 / L-6 に「✅ Sprint 007 で resolved」追記

#### 受入基準（PR I）

- [ ] `grep -r "unpkg\|jsdelivr" bundle/` が 0 件
- [ ] CSP が `'self'` 限定
- [ ] E2E P1 全 PASS
- [ ] オフライン環境（network disable）で dashboard が動くこと

---

### Sprint 007 全体の受入基準

- [ ] 外部 CDN 参照が 0 件
- [ ] `bundle/dashboard/static/` に自前 CSS + JS のみ
- [ ] E2E P1 全 PASS
- [ ] ADR 0004 merged
- [ ] Beta release candidate として PyPI publish 可

---

## Sprint 008: Low Polish + 残務（1 日、1 PR）

### 作業単位

##### P008-1. L-1: host setup.sh PID file symlink 対応
- `bundle/host/setup.sh:51` で `umask 077` + `[ -L "$PID_FILE" ] && rm "$PID_FILE"` 前置

##### P008-2. L-2: `zoo init --force` の symlink 防御
- `src/zoo/api.py:117` で `shutil.rmtree` 前に `if dst.is_symlink(): raise SystemExit(...)`

##### P008-3. L-3: harness.db サイズ上限
- `bundle/policy.toml` の `[general]` に `max_db_size_mb = 500` 追加
- `policy_enforcer.py` で超過時 oldest から truncate

##### P008-4. L-4: SSE parser `_active_tools` 上限
- `bundle/addons/sse_parser.py` に `MAX_ACTIVE_TOOLS = 100` 追加、超過で oldest drop

##### P008-5. L-5: CoreDNS forwarder を env 化
- `bundle/dns/Corefile` の `8.8.8.8` を env 展開可能に
- `bundle/docker-compose.strict.yml` に `DNS_FORWARDER=${DNS_FORWARDER:-8.8.8.8}` 追加

##### P008-6. L-6 (Sprint 007 で自然に消える想定)
- 確認のみ

##### P008-7. CHANGELOG 更新 + Sprint 008 archive

#### 受入基準（Sprint 008）

- [ ] Low 指摘全解消 or defer 明示
- [ ] `docs/dev/reviews/2026-04-18-comprehensive-review.md` の「未 resolved」が 0 件
- [ ] 1.0 release candidate として PyPI publish 可

---

## 並列化と優先度戦略

### ケース A: 早期 Alpha release 重視

1. Sprint 004（半日）→ Sprint 005（2〜3 日）→ **Alpha release** ← ここで publish 可
2. その後 Sprint 006 / 007 を並行で進め → Beta
3. Sprint 008 → 1.0

### ケース B: 一気に仕上げて 1.0

1. Sprint 004 ＋ 005 ＋ 006 を直列（約 5 日）
2. Sprint 007（1〜2 週間、全期間中）
3. Sprint 008（最後に 1 日）
4. **1.0 release**

推奨: **ケース A**。早期 alpha で user feedback を取り、007 の自前実装に反映できる。

---

## 別 phase / deferred

| 項目 | 理由 | いつ |
|---|---|---|
| #31 user 実機 smoke | user 環境依存 | Sprint 005 の alpha release 後 |
| #32 README screenshots | user 環境 dashboard 起動必要 | Sprint 007 完了後（UI が確定してから撮る） |
| #34 E2E P3 real agent | token 必須、CI opt-in 設計が別 | Sprint 007 後 |
| #35 inbox agent script | 要 grooming | Sprint 008 後に別 sprint |
| #3 OpenAI exec_command | 仕様確定待ち | 未定 |

---

## Process 注意事項

- **各 PR は TDD** — まず失敗する test → 実装 → refactor
- **各 PR ごとに self-review + Gemini review**（`/self-review` スキル適用）
- **Medium 以上の指摘は必ず修正**してから merge
- **各 Sprint 終了時に archive** — `docs/dev/sprints/NNN-<theme>.md` に決定事項と学びを記録
- **ADR は設計判断ごとに切る** — 今後 ADR 0004 (Sprint 007) / ADR 0005 (Sprint 005 の fail-closed)

---

## 参照

- 包括レビュー: [docs/dev/reviews/2026-04-18-comprehensive-review.md](../dev/reviews/2026-04-18-comprehensive-review.md)
- BACKLOG: [BACKLOG.md](../../BACKLOG.md)
- ADR 一覧: [docs/dev/adr/](../dev/adr/)
- Sprint 履歴: [docs/dev/sprints/](../dev/sprints/)
