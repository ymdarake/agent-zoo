# 2026-04-18 包括レビュー: 当日作業 + リポジトリ全体セキュリティ監査

| 項目 | 値 |
|---|---|
| 実施日 | 2026-04-18 |
| 対象（作業レビュー） | 直近 11 commit (`7d3101a..HEAD`) — Sprint 003 の全成果 |
| 対象（セキュリティ監査） | リポジトリ全体（`src/`, `bundle/`, `.github/`, `tests/`, `docs/`） |
| レビュアー | Claude subagent（一次） + Gemini 2.5 Pro（セカンドオピニオン） |
| 総合判定（作業） | 🟡 軽微な修正後 OK（H 1〜3 件 + M 6 件） |
| 総合判定（セキュリティ） | 🔴 **リリース前に Critical/High 修正必須** |

---

## エグゼクティブサマリ

### 当日作業（Sprint 003）

- **High** 3〜4 件（Claude 3 + Gemini が M1 を H に格上げ）
- **Medium** 6〜10 件（追加 Gemini 4 件含む）
- **Low** 5〜6 件
- 全体: ADR 0002 / 0003 の方針との整合は取れており、テスト基盤・CI 整備は健全。
- ただし **CLAUDE.md / docs/dev/python-api.md の整合性違反** と **CI E2E P2 の brittle 設定** は早期対応推奨。

### セキュリティ監査

- **Critical** 1〜2 件（C-1 Werkzeug debugger、+ Gemini 追加 G-1: mitmproxy addon 例外でポリシーバイパス）
- **High** 4〜6 件（CSRF / path traversal / cap_drop 未適用 / 属性 injection / dashboard XSS 経路）
- **Medium** 8〜9 件（TOCTOU / SRI 無し / mutable tag / 緩い regex / body_size_limit 等）
- **Low** 6 件
- **「localhost bind だから安全」前提は CSRF と DNS rebinding により破綻**。
- **mitmproxy addon の例外で fail-open する可能性** が最大の懸念。リリース前に必ず fail-closed 化。

---

## 第 I 部: 当日作業レビュー

### レビュー対象 commit（時系列）

```
7d3101a :sparkles: E2E テスト P1+P2 実装 (ADR 0003) + Gemini レビュー反映
74d793f :bug: E2E P1 動作確認: button selector を form 単位に絞る + Chromium を .venv に閉じ込め
c36d9cb :wrench: repo root に Makefile を導入し PLAYWRIGHT_BROWSERS_PATH を強制 export
c2eb258 :fire: bundle/Makefile と repo root data/ を撤去し zoo CLI に一本化
a92c8b0 :memo: zoo test smoke 再実装を正式にやらないことを明記
b659791 :memo: Sprint 003 アーカイブ: E2E Test Foundation + zoo CLI 一本化
9f78e5a :sparkles: GitHub Actions CI (unit + E2E P1/P2) と PR テンプレートを追加 (#33 完了)
54f2b38 :memo: README に CI バッジを追加（日英両方）
36d21f8 :memo: README を利用者目線に再構成
f16ec4f :memo: docs/user/ から開発者向け記述を除去し利用者目線に統一
46b0141 :wrench: ci.yml: docs / LICENSE / logo のみの変更で CI を skip
```

### High（要対応、両レビュアー同意）

#### H1. `docs/dev/python-api.md:52` に削除済 API `zoo.test_smoke()` 記述が残存

`a92c8b0` で `api.test_smoke` / `cli.test_smoke` / `__init__.py` の export を完全削除したが、`docs/dev/python-api.md:52` に
`| zoo.test_unit() / zoo.test_smoke(*, agent) | int | |`
が残ったまま。利用者が `from zoo import test_smoke` で `ImportError` を踏む。

**修正**: 該当行から `/ zoo.test_smoke(*, agent)` を削除（1 行 edit）。

#### H2. `CLAUDE.md` のリポジトリ構造図が実態と乖離（2 箇所）

- L26: `│   ├── Makefile              # maintainer 専用（user 配布物には含めない、ADR 0002 D5）` — `bundle/Makefile` は `c2eb258` で削除済
- L31: `│   └── host/, dns/, certs/, data/` — `bundle/data/` は実在しない（`certs/` 等のみ）

CLAUDE.md は Claude Code が常時参照する project 指示書。実体との乖離はエージェント挙動に影響。

**修正**: L26 の Makefile 行削除、L31 から `data/` 除去。

#### H3. CI `e2e-proxy` job が `bundle/policy.runtime.toml` 不在で失敗の可能性

`bundle/docker-compose.yml:131` で proxy service が `./policy.runtime.toml:/config/policy.runtime.toml:ro` を bind mount するが、`bundle/policy.runtime.toml` は git 管理外（`zoo init` 時に `.zoo/policy.runtime.toml` を `touch` するだけ）。CI workflow には `touch bundle/policy.runtime.toml` step が無い。

Docker は不在ファイルの bind mount でホスト側を**ディレクトリとして自動作成**するため、proxy 内で `tomllib.loads(read_text())` が `IsADirectoryError` で失敗する。base policy は維持されるが brittle で fail に至る。

**両レビュアー一致**で agree（Gemini も独自確認）。

**修正**: `e2e-proxy` job の `Build base image` 直前に `- run: touch bundle/policy.runtime.toml` を追加、または `tests/e2e/test_proxy_block.py::proxy_up` fixture 冒頭で `(BUNDLE / "policy.runtime.toml").touch(exist_ok=True)`。

#### H4 (Gemini が M1→H に格上げ). `paths-ignore: '**.md'` が `bundle/templates/HARNESS_RULES.md` も skip

`HARNESS_RULES.md` は **agent の behavior を規定する指示テンプレート**。これを編集した PR では CI が走らないため、誤字や構文エラーで agent 誤動作を test で検出できない。

**Gemini コメント**: 「セキュリティや動作の根幹に関わる変更がテストされずにマージされるリスク」のため High 相当。

**修正**: `paths-ignore` を以下のいずれかに変更:
- 明示列挙: `['README*.md', 'CHANGELOG.md', 'BACKLOG.md', 'CLAUDE.md', 'docs/**/*.md']`
- またはネガティブパターン併用（GitHub Actions は negate サポート）

### Medium（対応推奨）

#### M1. `tests/e2e/conftest.py::_init_db_schema` が `policy_enforcer.py` と drift する可能性

`_init_db_schema` は `CREATE TABLE` のみで `CREATE INDEX` (line 88-91 の 4 本) が欠落。enforcer 側でカラム追加した時に conftest 手動 sync が必要。

**修正**: `policy_enforcer._init_schema()` を test から直接呼ぶ、または共通 SQL 定数化（Single Source of Truth）。

#### M2. `tests/e2e/test_proxy_block.py::proxy_up` で healthcheck 失敗時に `pytest.fail` しない

L56-67 で 30 秒 healthcheck loop を回すが、unhealthy のまま loop 抜けても `yield` する → 後続テストが proxy 不在で謎の fail。デバッグ困難。

**修正**: loop 末尾に `else: pytest.fail("proxy did not become healthy in 30s")`。

#### M3. `proxy_up` fixture の `__import__("os")` 4 連発はスタイル悪

`from __future__ import annotations` 直下で `import os` が無いため `__import__("os")` で凌いでいる。

**修正**: module top に `import os` を追加。

#### M4. PR テンプレート checklist の「CI 自動実行」と「作者 manual」のすれ違い

`[ ] make unit が PASS する（CI で自動実行）` は CI が自動実行するなら作者の checkmark は冗長。逆にローカル確認を求めるなら「CI で自動実行」注記は不要。

**修正**: ローカル確認 required にし CI 注記を削除する、または checklist 全削除して動作確認は CI に委ねる（Gemini も同意）。

#### M5. Sprint 003 archive の commit log にプレースホルダー `<next>` 残存

`docs/dev/sprints/003-e2e-foundation-and-zoo-cli-unification.md:113` に
`<next>  :sparkles: GitHub Actions ci.yml + PR テンプレ追加（#33 完了条件の最後の 1 項目）`
が残存。実 commit (`9f78e5a`) で置換すべきだった。

**修正**: `<next>` → `9f78e5a`。

#### M6 (Gemini G-1). CI: `e2e-dashboard` ジョブの手動実行不可

`workflow_dispatch` トリガー無しのため、flaky test 再確認等で手動再実行できない。

**修正**: `on:` に `workflow_dispatch: {}` 追加。

#### M7 (Gemini G-2). CI: `uv` キャッシュキーが Python バージョンを考慮していない

`actions/setup-uv@v7` の `enable-cache` を Python matrix で使うと、バージョン間で cache 共有が起きる可能性。将来 Python 依存パッケージで解決エラー誘発リスク。

**修正**: 明示的に Python ver を含む key を Cache action に渡す（setup-uv の enable-cache を切って独自 cache に）。

#### M8 (Gemini G-3). root の `Makefile` の責務が曖昧

`bundle/Makefile` を撤去して zoo CLI に寄せた直後に root に Makefile を再導入したのは一見矛盾。`PLAYWRIGHT_BROWSERS_PATH` の強制 export が目的という意図がコードコメントから読み取れる程度。

**修正**: Makefile 冒頭コメントに「dev 環境専用 / 配布物は zoo CLI 一本化」をより明確に記載。direnv との比較等を README/Sprint archive に追記。

### Low（任意）

- **L1**: `tests/e2e/__init__.py` の生成経緯が git rename detection で `data/.gitkeep => tests/e2e/__init__.py` に。両方 0 byte なので git の自動検出。論理的には別物だが CHANGELOG 記載済で問題なし。
- **L2**: `pytest_collection` 時の `_docker_available()` の `shutil.which("docker")` I/O が毎回走る。session-scope cache で微小高速化可能。
- **L3**: CHANGELOG の `### Added` で `paths-ignore` (`46b0141`) の個別記載なし。
- **L4**: `_curl_via_proxy` の `--cacert` 指定だが CI 側で cert 事前生成 step なし（mitmdump 起動時に作る挙動依存）。
- **L5**: Gemini G-4 - CI `e2e-proxy` の `HOST_UID: "1001"` ハードコード。Ubuntu runner UID が将来変わると問題。
- **L6**: `Makefile` の `e2e-all` target が `pytest tests/e2e/` で `norecursedirs` を上書き（動作 OK だが暗黙）。

### Positive（強み）

1. **Sprint 003 archive の完全性が高い** — Decision 表 (D1〜D8 + F1〜F4)、commit log、検証結果、学び 4 点が網羅。
2. **ADR 0002 Follow-up note** — D5 の当初判断（bundle/Makefile 維持）→ 撤去への変更を上書きせず Follow-up section で記録。Decision 履歴の信頼性。
3. **CI cache 戦略** — `setup-uv@v7` の `enable-cache` + Playwright を `actions/cache@v4` で `hashFiles('uv.lock')` キーで cache。Chromium ~150 MB を skip。
4. **`paths-ignore` で CI cost 削減** — docs typo PR で 3 job 走らない。
5. **PLAYWRIGHT_BROWSERS_PATH の二重防御** — `Makefile` で export + `conftest.py` で `setdefault`。
6. **`e2e-proxy` の post-merge gate** — PR では走らず main push のみ、image build 重さを各 PR に課さない判断。
7. **Selector の form 単位絞り込み** — `74d793f` の bulk button 衝突解消、実機検証ベース。
8. **`test_smoke` 削除の 3 段論理** — 同等カバレッジ E2E P2、Makefile 撤去で動かない、BACKLOG ROADMAP 同期削除で「やらない」明示。
9. **README (ja/en) の利用者目線統一** — Maintainer 注記 / issue 番号 (`#27`) 除去で readability 向上。
10. **`api.py` の `# type: ignore[union-attr]` 適切追加** — `subprocess.Popen.stdin` の None ガード補強。

### Gemini 全体所感（要約）

> Sprint 003 は ADR 0003 沿いの E2E 基盤導入と ADR 0002 沿いの zoo CLI 集約を着実に進めており、プロジェクトの健全性向上に大きく貢献。`bundle/Makefile` 廃止のトレードオフは zoo CLI 機能拡充で吸収する必要あり。CI に関しては `paths-ignore` (M1/H) が最もクリティカル。リリースに向けた基盤は整いつつあるが、CI の信頼性・安定性をもう一段引き上げる調整が必要。

---

## 第 II 部: リポジトリ全体セキュリティ監査

### Critical

#### C-1 (Claude=Critical, Gemini=High に修正提案). dashboard が Werkzeug デバッグモードで起動

**ファイル**: `bundle/docker-compose.yml:141-142`

```yaml
- FLASK_DEBUG=1
command: ["python", "-m", "flask", "run", "--host=0.0.0.0", "--port=8080"]
```

Dockerfile の `gunicorn` CMD を override し、`FLASK_DEBUG=1` で Werkzeug デバッガを有効化。`/console` エンドポイントが exposed され、PIN 入力で対話 Python REPL → 任意コード実行。

**Gemini 評価**: 「`127.0.0.1` バインドにより外部直接 RCE は不可だが、後述 H-1 (CSRF) と組合せでローカルブラウザ経由 RCE 経路が成立する」→ Critical → **High に格下げ**を提案。
**結論**: それでも極めて危険。実害評価は CSRF 経路の成立次第だが、本番（user 環境配布）想定で `FLASK_DEBUG=1` は許容不可。

**修正**: 配布 default は `gunicorn` (Dockerfile 通り) に。`FLASK_DEBUG=1` は開発専用 `docker-compose.override.yml` に分離、または env opt-in に。

#### C-2 (Gemini G-1, NEW Critical). mitmproxy addon の未捕捉例外でポリシーバイパス（fail-open）

**根拠**: mitmproxy のデフォルト挙動として、addon 内で未捕捉例外が発生するとイベント処理がスキップされ、**トラフィックがそのまま通過する**（fail-open）。すなわち、`bundle/addons/policy.py` / `policy_enforcer.py` / `sse_parser.py` 等で `KeyError` / `TypeError` 等が発生すると、すべてのセキュリティポリシー（許可リスト、ブロックルール等）が完全にバイパスされ、agent は野放しで外部通信できる。

現状の addon 実装に `request()` / `response()` 等のイベントハンドラを top-level で広範に `try...except` で囲む構造が無い。

**実害評価**: 攻撃者（または不慣れな user の policy.toml 編集ミス）が addon 内で例外を誘発する request を送れば、policy 遮断を完全 bypass。本ハーネスの根本機能を無効化する致命的経路。

**修正**: すべての mitmproxy event handler を top-level `try...except` でラップし、`except` ブロックでは error log + `flow.kill()` で fail-closed 化（安全側に倒す）。

> **これがリリース判断の最重要 blocker**。Gemini の独自検出。

### High

#### H-1. dashboard 全 POST に CSRF 対策が無い

**ファイル**: `bundle/dashboard/app.py` 全体（grep 結果ゼロ）

`/api/whitelist/*`, `/api/inbox/*` のすべての POST が CSRF token 未検証。Flask-WTF も未使用。Origin / Referer 検証も無し。`HX-Request` ヘッダ存在チェック（line 362, 385 等）も認可ではなく view 切替なので bypass 自由。

`_get_json_body()` (`app.py:340-342`) は **JSON でも form でも** 受け付けるため、攻撃者は `Content-Type: application/x-www-form-urlencoded` で同オリジン外から送信可能（CORS preflight 不要）。

**攻撃シナリオ**: ユーザーが dashboard 起動中に悪意 webpage を開く → 隠し form auto-submit → 任意ドメインを `domains.allow.list` に追加（exfiltration ホスト）/ inbox 全件 accept。

**Gemini 補足**: DNS rebinding でも同等の攻撃が成立し得るため「localhost bind = 安全」前提は崩れる。

**修正**: Flask-WTF CSRFProtect 導入、最低でも `Origin` / `Sec-Fetch-Site` 全 POST/DELETE 検証。HTMX 側は `hx-headers` で token 同梱。

#### H-2. inbox reject／bulk-reject に path traversal の余地

**ファイル**:
- `bundle/dashboard/app.py:492-509` (`api_inbox_reject`)
- `bundle/dashboard/app.py:538-547` (`api_inbox_bulk_reject`)
- `bundle/addons/policy_inbox.py:203` (`mark_status`)

```python
# policy_inbox.py:203
path = Path(inbox_dir) / f"{record_id}.toml"
```

`api_inbox_reject` は `record_id` を `inbox_list_requests` で照合せず直接 `mark_status` へ。`record_id="../config/policy.runtime"` で `/inbox/../config/policy.runtime.toml` = `/config/policy.runtime.toml` に誘導可能。

**実害評価**:
- 拡張子は `.toml` 固定だが、`policy.runtime.toml` (rw mount) は破壊的編集成立、`status` 等のトップレベルキー injection
- CSRF (H-1) と組み合わせるとブラウザ経由で外部 trigger 可能

**修正**: `record_id` を strict regex (`^[A-Za-z0-9T:_-]+$`) でホワイトリスト検証、または `mark_status` 内で `path.resolve().is_relative_to(Path(inbox_dir).resolve())` チェック。`api_inbox_reject` は accept 側と同様に `inbox_list_requests` で存在確認してから渡す。

#### H-3. proxy / dashboard / dns コンテナに `cap_drop` ／ `security_opt` 未適用、root 実行

**ファイル**: `bundle/docker-compose.yml:106-160`

`x-agent-common` の `cap_drop: [ALL]` は YAML anchor で agent service にしか展開されない。proxy / dashboard / dns / unified は `cap_drop` も `security_opt: [no-new-privileges:true]` も `user:` 指定も無し → すべて root 動作。

dashboard RCE (C-1 / H-2) 成立時に container escape ／ ポリシー改変容易。

**修正**:
- proxy / dashboard / dns に `cap_drop: [ALL]` + 必要 cap のみ `cap_add`
- `security_opt: ["no-new-privileges:true]` 全 service
- dashboard / proxy で `user: "${HOST_UID}:${HOST_UID}"` 明示

#### H-4. agent が任意 file 名で `/harness/inbox/*.toml` を書け、dashboard 側で属性 injection 余地

**ファイル**:
- `bundle/docker-compose.yml:36, 56, 77, 103` (`./inbox:/harness/inbox` rw)
- `bundle/dashboard/templates/partials/inbox.html:28, 32`

```html
<form ... hx-vals='{"record_id": "{{ r._id }}"}'>
```

`r._id` は inbox dir glob で取れた任意 file stem。agent は mount 経路で任意名 `.toml` を直接 cp 可能。`_id` に `'` を含めれば属性 injection（Jinja autoescape は `<>&"` のみ、`'` 素通し）→ XSS 成立可能。

**Gemini G-2 (新規 High)**: `inbox.html` 内で `r.value` / `r.reason` / `r.agent` も agent 任意設定可能で同様の XSS リスク。autoescape 無効化や `|safe` 誤追加で温床化。Content Security Policy (CSP) 未設定。

**修正**:
- glob 取得時に `re.fullmatch(r"[\w:T-]+", stem)` で filter
- `hx-vals` を `|tojson` で JSON-safe literal 化
- HTTP response に `Content-Security-Policy` ヘッダ追加（インライン script ブロック）

### Medium

#### M-1. dashboard が外部 CDN を SRI 無しで読み込み

**ファイル**: `bundle/dashboard/templates/index.html:7-8`

```html
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@picocss/pico@2/css/pico.min.css">
<script src="https://unpkg.com/htmx.org@2.0.4"></script>
```

`integrity=` / `crossorigin=` 無し → CDN 乗っ取り / unpkg リダイレクト改ざんで任意 JS 注入。

**修正**: ベンダ JS/CSS を `bundle/dashboard/static/` に同梱 self-host、または SRI ハッシュ追加。

#### M-2. log DB に Authorization ヘッダ／クエリ token 含む URL が永続化

**ファイル**: `bundle/addons/policy_enforcer.py:101-103, 200`

`agent` が `https://api.openai.com/v1/x?api_key=secret` のような URL を出した場合、URL 全体が `harness.db` に記録される。`secret_patterns` は body のみ対象、URL は対象外。

**修正**: URL 保存時に `urllib.parse.urlsplit` → query strip / token マスキング。policy.toml に「URL にも secret_patterns 適用」設定を追加。

#### M-3. Dockerfile base が mutable tag

**ファイル**:
- `bundle/container/Dockerfile.base:13` (`FROM node:20-slim`)
- `bundle/dashboard/Dockerfile:1` (`FROM python:3.12-slim`)
- `bundle/docker-compose.yml:107` (`mitmproxy/mitmproxy:10`)

メジャータグのみ pin → silently update でバグ・脆弱性混入リスク。

**修正**: image digest (`@sha256:...`) で pin。Dependabot / Renovate で自動 PR。

#### M-4. GitHub Actions third-party action が tag pinning（SHA pin 推奨）

**ファイル**: `.github/workflows/release.yml`, `ci.yml`

`pypa/gh-action-pypi-publish@release/v1` は branch 参照（強制 push で書換可能）。`@v5` 等のメジャータグも mutable。

**修正**: `actions/checkout@<commit-sha>` 形式で pin、`# v5.x.y` コメント併記。

#### M-5. `_validate_domain` の正規表現が緩い

**ファイル**: `bundle/dashboard/app.py:326`

```python
_DOMAIN_RE = re.compile(r"^(\*\.)?[a-zA-Z0-9]([a-zA-Z0-9.-]*[a-zA-Z0-9])?$")
```

`*.com` 通る（TLD wildcard）、`a..com` 通る（連続 dot）、`a-.com` 通る（trailing hyphen）、`localhost` 通る。

CSRF (H-1) 組合せで `*.com` を allow に push できれば実質ブロックバイパス。

**修正**: ラベルごとに `^(?!-)[A-Za-z0-9-]{1,63}(?<!-)$`、TLD は最低 1 ラベル、`*.` の後ろは 2 ラベル以上強制。

#### M-6. mitmproxy `body_size_limit` 未設定 → 巨大 payload で memory 圧迫

**ファイル**: `bundle/docker-compose.yml:111-116`、`bundle/addons/policy.py:233-266`

`mitmdump` に `body_size_limit` 未指定。`check_payload` は `body.decode("utf-8")` で全文読み。SSE parser には `MAX_LINE_BUF=1MB` あるが request body 側は無し。

**修正**: `command:` に `--set body_size_limit=1m` 追加。

#### M-7. `tool_use_rules.block_args` がワード境界マッチで bypass 容易

**ファイル**: `bundle/addons/policy.py:365-368`、`bundle/policy.toml:95-102`

`rm -rf /` を `rm  -rf /`（spaces 2 つ）/ `rm -rf  /` / `/bin/rm -rf /` / `R="rm -rf"; eval "$R /"` 等で bypass。LLM 生成コマンドの完全検知は本質的に困難だが docs で過信されるリスク。

**修正**: docs に「bypass 容易、最終防衛は network isolation」と explicit warning。base policy も「block_args は example」コメント追加。

#### M-8 (Gemini G-3). `policy.toml` の TOCTOU 競合状態

**ファイル**: `bundle/addons/policy_edit.py` (write 側 fcntl LOCK_EX) vs `bundle/addons/policy_enforcer.py::load_policy` (lock 無し)

dashboard からポリシー編集中に enforcer が不完全な `policy.toml` を読む競合。atomic write + rename で部分読み込みは防いでも、リロードタイミングで「古い + 新しい」混在判断の余地。

**修正**: enforcer 側 read 時に `fcntl.LOCK_SH` を取得し、edit 側 `LOCK_EX` と協調。

### Low

- **L-1**: `bundle/host/setup.sh:51` の PID file に symlink 攻撃の理論的余地（`echo "$MITM_PID" > "$PID_FILE"`）。
- **L-2**: `src/zoo/api.py:117` の `zoo init --force` で `shutil.rmtree(dst)` が symlink 先を辿る Python version 依存挙動。
- **L-3**: `harness.db` のサイズ上限なし、rotation は時間ベースのみ（30 日 + heavy traffic で多 GB 化）。
- **L-4**: `bundle/addons/sse_parser.py:141, 197, 434` の `_active_tools` / `_active_tool_calls` dict にエントリ数上限なし。
- **L-5**: `bundle/dns/Corefile:7` で `8.8.8.8` ハードコード（社内 DNS 必要な企業環境で問題、override 手順 docs 無し）。
- **L-6**: `inbox.html:28, 32` の `'` クォート属性内未エスケープ（H-4 と関連）。

### Positive（既存の強み、両レビュアー一致）

1. **subprocess 全箇所が list 引数 + `shell=False`** — shell injection ゼロ
2. **SQL は全て parameterized** — `bundle/dashboard/app.py`, `bundle/addons/policy_enforcer.py`
3. **CA private key が git 履歴に commit 無し** — `.gitignore` で `bundle/certs/*` 除外、`.gitkeep` のみ keep
4. **wheel 配布物に CA 関連ファイル含まれず** — `uv build --wheel` で実証
5. **sdist も `.gitignore` 尊重** — hatchling VCS-aware
6. **`internal: true` intnet と `extnet` 分離** — agent の外部経路は proxy 1 本に強制
7. **agent コンテナ `cap_drop: [ALL]` + 非 root + `--dangerously-skip-permissions`** — 「読めても送れない」を実装
8. **release workflow OIDC trusted publishing** — API token を secrets に入れず、本番 PyPI tag push 専用
9. **PR は `pull_request`（fork に secret 渡らない）** — `pull_request_target` 未使用
10. **CI / release で concurrency group + cancel-in-progress 使い分け**
11. **`policy.toml` の atomic write + fcntl ロック**（write 側のみ、M-8 で read 側も推奨）
12. **sqlite を `mode=ro` で開く** — dashboard 誤書込ガード
13. **inbox file 名 atomic create (`O_CREAT|O_EXCL`)** — race file system level
14. **依存バージョン新しめ** — flask 3.1.3 / werkzeug 3.1.6 / jinja2 3.1.6 等で既知 CVE なし
15. **HARNESS_RULES.md で agent 自身に inbox 提出フロー案内** — human-in-the-loop の摩擦最小化

### Gemini 設計レビューの要点

#### dashboard 127.0.0.1 bind の十分性

「localhost 専用のため認証不要」という README 主張は **不十分かつ危険**:
1. **CSRF (H-1)** — ブラウザ経由攻撃成立
2. **DNS Rebinding** — 悪意サイトが自ドメインの DNS を `127.0.0.1` に変更 → 同一オリジンポリシー回避
3. **ローカルプロセスの脅威** — 同一ホスト上の他プロセス（マルウェア等）が `http://127.0.0.1:8080` 直接到達

→ localhost binding は認証の代替にならず、CSRF 対策と起動時生成トークン要求等を導入すべき。

#### agent コンテナ escape vectors

- `docker.sock` 非マウントは高評価
- bind mount 主要リスク:
  - `/workspace`: agent が任意先 symlink を置けばホスト FS アクセス
  - `/inbox`: ファイル名 injection（H-4）+ `ln -s /etc/passwd /inbox/leaked.txt` でホスト任意 file の間接読取り

#### TLS 信頼チェーン

- `update-ca-certificates` で CA を agent に信頼させる仕組みは適切
- **最大の弱点は CA 秘密鍵の保護** — `bundle/certs/mitmproxy` のパーミッション管理が緩いとホスト他 user / プロセスに鍵漏洩 → agent 通信の全解読リスク
- `setup.sh` のパーミッション設定をより厳格に

### 監査範囲外 / 今後の課題

- 依存パッケージの transitive CVE スキャン未実施 — `pip-audit` / Snyk / Dependabot Alerts いずれか有効化推奨
- 動的解析（実環境攻撃 PoC）未実施 — CSRF PoC、`/console` PIN brute force、werkzeug debugger PIN 計算可能性
- mitmproxy 10.x 自身の CVE 追跡
- コンテナイメージ脆弱性スキャン未実施 — Trivy / Grype を CI 統合推奨
- agent CLI 自体（claude-code, codex, gemini-cli）の挙動レビュー外（npm latest install）
- policy.toml の TOML injection / DoS テスト未実施
- Inbox `mark_status` と `cleanup_expired` の並行実行（CSRF 攻撃と組合せ）
- `zoo proxy <agent>` の任意 binary 起動（仕様だが docs warning 推奨）

---

## 第 III 部: 統合アクションリスト（優先度順）

### Phase 1: リリース blocker（即時着手必須）

1. **C-2 [Critical, Gemini G-1]** mitmproxy addon の例外で fail-closed 化
   - 全 event handler を top-level `try...except` でラップ → `flow.kill()` で安全側
   - 影響: `bundle/addons/policy.py`, `policy_enforcer.py`, `sse_parser.py`
2. **C-1 [Critical/High]** dashboard を gunicorn (Dockerfile 通り) に戻す、`FLASK_DEBUG=1` を `docker-compose.override.yml` に分離
   - 影響: `bundle/docker-compose.yml`
3. **H-1 + H-2 + H-4 + G-2** dashboard セキュリティ一括対応:
   - Flask-WTF CSRFProtect 導入、または Origin / Sec-Fetch-Site 検証
   - `record_id` strict regex 検証 + `path.resolve().is_relative_to` チェック
   - `inbox.html` の `hx-vals` を `|tojson` 化、`r._id` glob 取得時に strict filter
   - Content-Security-Policy ヘッダ追加（インライン script ブロック）
   - 影響: `bundle/dashboard/app.py`, `templates/`, `bundle/addons/policy_inbox.py`
4. **H-3** proxy / dashboard / dns に `cap_drop: [ALL]` + `security_opt: [no-new-privileges:true]` + `user:` 追加
   - 影響: `bundle/docker-compose.yml`

### Phase 2: 当日作業の不整合修正（小コミット）

5. **H1** `docs/dev/python-api.md:52` から `zoo.test_smoke(*, agent)` 削除
6. **H2** `CLAUDE.md` 構造図の `bundle/Makefile` 行と `bundle/data/` 削除
7. **H3** CI `e2e-proxy` で `touch bundle/policy.runtime.toml` 追加
8. **H4 (=旧 M1)** `paths-ignore` を明示列挙化、`HARNESS_RULES.md` を CI 対象に戻す
9. **M2** `proxy_up` healthcheck loop に `else: pytest.fail(...)`
10. **M5** Sprint 003 archive の `<next>` を `9f78e5a` に置換

### Phase 3: セキュリティ Hardening（次 PR でまとめて）

11. **M-1** dashboard の CDN を self-host or SRI 追加
12. **M-2** URL からの secret strip + secret_patterns を URL にも適用
13. **M-3** Docker image を `@sha256:` で pin、Renovate / Dependabot 導入
14. **M-4** GitHub Actions の third-party action を SHA pin
15. **M-5** `_validate_domain` を strict regex に置換 + ユニットテスト追加
16. **M-6** mitmproxy `body_size_limit=1m` 設定
17. **M-7** docs に `block_args` 限界と「最終防衛は network isolation」明記
18. **M-8** `policy_enforcer.load_policy` に `fcntl.LOCK_SH` 追加

### Phase 4: 品質改善（任意・次 sprint 候補）

- **M1 (test)** `_init_db_schema` を `policy_enforcer._init_schema()` に共通化
- **M3 (style)** `__import__("os")` → `import os`
- **M4 (PR template)** checklist 文言を実態に合わせる
- **M6 (CI)** `e2e-dashboard` に `workflow_dispatch: {}` 追加
- **M7 (CI)** uv cache key に Python ver 含める
- **M8 (style)** root `Makefile` のコメントで責務明記
- **L1〜L6** 個別 issue 化 or 余裕で対応

### Phase 5: 監査外領域の継続対応

- 依存 CVE スキャン CI 統合（`pip-audit`）
- コンテナ脆弱性スキャン（Trivy/Grype）
- 動的解析・PoC（CSRF / debugger PIN）
- agent CLI 自体（claude-code, codex, gemini-cli）のロックファイル化検討

---

## 全体総評

### 当日作業（Sprint 003）

- 方針整合性は良好。E2E 基盤導入と zoo CLI 一本化が同 sprint 内で達成。
- `bundle/Makefile` 完全撤去は設計判断として正しいが、当日の docs 群（CLAUDE.md / python-api.md）の追従が不足 → H1/H2 で要修正。
- CI 設定は brittle な箇所があり、特に `e2e-proxy` の前提ファイル不在（H3）と `paths-ignore` の `**.md` 過大スコープ（M1→H4）は実害誘発前に修正推奨。
- Sprint 003 archive の品質（Decision 表 / 学び）は高く、後の振り返り用ドキュメントとして十分機能。

### セキュリティ姿勢

> **Gemini 全体所感（要約）**:
> agent-zoo はコンテナ分離、非 root 実行、権限削除など現代的セキュリティプラクティスを意識し、エージェント実行環境のベースラインは強固。一方、mitmproxy と連携する **Web ダッシュボード実装に典型的 Web 脆弱性（CSRF, XSS, Path Traversal）が複数残存**。「localhost だから安全」という想定がセキュリティホールの根本原因。さらに **mitmproxy addon の堅牢性（例外処理）にクリティカルな見落とし** あり、これが現在の最大の懸念。
>
> **これらの最優先項目修正前は、製品リリースは推奨できない**。修正後はセキュリティハーネスとして非常に価値あるツールとなるポテンシャルを秘めている。

### リリース判断

| 項目 | 判定 |
|---|---|
| Sprint 003 の merge 妥当性 | 🟡 H1〜H4 修正後 OK |
| 配布リリース (PyPI publish) 妥当性 | 🔴 **Phase 1 (C-1, C-2, H-1〜H-4) 完了後でないと不可** |
| dogfood / 内部利用 | 🟢 mitmproxy 例外時の fail-open リスクを認識した上で OK |

---

## 付録: レビュー手法の差分

| 観点 | Claude subagent | Gemini 2.5 Pro |
|---|---|---|
| アプローチ | git diff + Read で各 commit を逐一確認、grep で危険パターン検索 | 同様 + 設計面での独立検証（DNS rebinding / TOCTOU / fail-open 等） |
| 検出件数（作業） | H 3 + M 6 + L 5 | + G 4 件追加 + M1 を H に格上げ |
| 検出件数（セキュリティ） | C 1 + H 4 + M 7 + L 6 | + G 3 件追加（うち 1 件 Critical） |
| 共通強み | 既存指摘の独立検証で agree、根拠 file:line 提示 | 設計面での「想定の妥当性」を独立評価（127.0.0.1 bind 神話の崩壊指摘） |
| 各々の独自貢献 | 当日 commit の細部（commit log placeholder、PR template 文言）を網羅 | mitmproxy addon の fail-open（最重要 Critical）、TOCTOU、DNS rebinding 想定 |

両者ともに `git` コマンドと file Read を駆使し、根拠ベースで指摘。**互いに見落としを補完しており、片方だけでは Critical 1 件 + High 1 件を見逃していた**。

---

## 参照

- ADR 0001 [Policy Inbox](../adr/0001-policy-inbox.md)
- ADR 0002 [.zoo/ Workspace Layout](../adr/0002-dot-zoo-workspace-layout.md) — Follow-up (2026-04-18)
- ADR 0003 [E2E Test Strategy](../adr/0003-e2e-test-strategy.md)
- Sprint 003 [E2E Foundation + zoo CLI 一本化](../sprints/003-e2e-foundation-and-zoo-cli-unification.md)
- レビュー対象 commit range: `7d3101a..46b0141` (本日 11 commit)
