# Sprint 007 PR G: 自前 CSS + vanilla JS 基盤

| 項目 | 値 |
|---|---|
| 作成日 | 2026-04-19 |
| 改訂 | Rev.3（実装 self-review 反映: 実態 line 数 + data-bulk-scope 補注 + fetch 失敗時 UI swap follow-up） |
| Sprint | 007 |
| PR | F (✅ merged) → **G (本 PR)** → H → I |
| 親設計 | [ADR 0004](../dev/adr/0004-dashboard-external-deps-removal.md) (Rev.4) |
| 親計画 | [Plan F](sprint-007-pr-f.md) (Rev.4) — pseudo-code 正本 |

---

## ゴール

PR F で確定した設計に基づき、**自前 CSS + vanilla JS の基盤ファイルを追加**する。
**index.html はまだ link しない**（PR H で link）。Flask の static serving 確認のみ。

### Deliverables

1. `bundle/dashboard/static/app.css` — 自前 CSS (~250〜350 行のレンジ、超過時は PR H で追加 commit OK)。design tokens / layout / table / form / button / status badge / spinner。**`:root` 変数はフラット定義** (将来 dark theme で `@media (prefers-color-scheme: dark)` 内で同名変数を上書き可能な構造に)
2. `bundle/dashboard/static/app.js` — Plan F pseudo-code を実体化 (**実装後 ~240 行**: 実 logic ~165 行 + コメント・正本リンク 50 行 + IIFE wrap + defensive guards 20 行。Plan G Rev.2 では 120〜150 を見積もったが、Plan F Rev.4 の Critical 要素 (backoff / MutationObserver 子孫走査 / defensive guard / IIFE / 仕様正本リンクコメント) を全部含めると 240 行になる)。**防御的設計**: `if (!el.dataset.pollUrl) return;` ガード、`isNaN(baseInterval)` 時 fallback (5000ms)
3. `bundle/dashboard/app.py` — `app.config["ASSET_VERSION"] = os.environ.get("ASSET_VERSION", "")` default 設定 (Jinja UndefinedError 回避)
4. `tests/test_dashboard_static.py`(新規) — `/static/app.css`、`/static/app.js` の 200 配信確認 + **重要 API 識別子 (MutationObserver / removedNodes / _pollTimers / document.hidden) の含有 assert** で pseudo-code 必須要素の欠落を防止
5. `tests/test_dashboard_asset_version.py`(新規) — `ASSET_VERSION` config の default 確認

### Non-goals

- index.html / partials の書換（PR H）
- CDN link 削除 / CSP 厳格化（PR I）
- E2E test の selector 変更（PR H）

---

## 作業順 (TDD)

### 1. Red: テスト追加 (PASS しない)

`tests/test_dashboard_static.py`:

```python
class TestStaticAssets(unittest.TestCase):
    def setUp(self):
        app.config["TESTING"] = True
        app.config["WTF_CSRF_ENABLED"] = False
        self.client = app.test_client()

    def test_app_css_served(self):
        rv = self.client.get("/static/app.css")
        self.assertEqual(rv.status_code, 200)
        self.assertIn("text/css", rv.headers["Content-Type"])
        # design token が含まれる (sanity check)
        self.assertIn(b"--color-primary", rv.data)

    def test_app_js_served(self):
        rv = self.client.get("/static/app.js")
        self.assertEqual(rv.status_code, 200)
        # 重要 API 識別子が含まれる (Rev.4 の Critical 要素が抜けないことを保証)
        for ident in (
            b"data-poll-url",
            b"data-swap-target",
            b"setupPolls",
            b"X-CSRFToken",
            b"MutationObserver",
            b"removedNodes",
            b"_pollTimers",
            b"document.hidden",
        ):
            self.assertIn(ident, rv.data, f"missing: {ident!r}")

    def test_static_files_have_correct_mime(self):
        rv = self.client.get("/static/app.css")
        self.assertTrue(rv.headers["Content-Type"].startswith("text/css"))
```

`tests/test_dashboard_asset_version.py`:

```python
class TestAssetVersion(unittest.TestCase):
    def test_default_asset_version_is_empty_string(self):
        # default は空文字（PR I で git sha 等を入れる予定）
        self.assertEqual(app.config.get("ASSET_VERSION", "MISSING"), "")

    def test_asset_version_can_be_overridden(self):
        # Plan review (Claude) #6: old が None でも復元で壊れないように pop ベースに
        had_key = "ASSET_VERSION" in app.config
        old = app.config.get("ASSET_VERSION")
        try:
            app.config["ASSET_VERSION"] = "abc123"
            self.assertEqual(app.config["ASSET_VERSION"], "abc123")
        finally:
            if had_key:
                app.config["ASSET_VERSION"] = old
            else:
                app.config.pop("ASSET_VERSION", None)
```

### 2. Green: 実装

#### 2a. `bundle/dashboard/app.py` — ASSET_VERSION 注入

```python
# 既存 SECRET_KEY 設定の近くに
app.config["ASSET_VERSION"] = os.environ.get("ASSET_VERSION", "")
```

`SECRET_KEY` と同じ env-driven パターンを採用。

#### 2b. `bundle/dashboard/static/app.js` — pseudo-code 実体化

Plan F の「コア API（pseudo-code、実装は PR G）」節をそのままコピーし、`buildIncludeQuery` と `swapInto` の helper も実装。

ファイル冒頭にライセンス / 説明 comment 必要:

```javascript
/**
 * agent-zoo dashboard — vanilla JS (Sprint 007 PR G)
 *
 * HTMX 互換の declarative API:
 *   data-poll-url / data-poll-interval / data-swap-target / data-trigger-from
 *   data-include / data-confirm / data-json-body / data-tab
 *   data-bulk-action / data-bulk-select / data-bulk-target / data-suggest-target
 *
 * 設計の正本: docs/dev/adr/0004-dashboard-external-deps-removal.md
 *           docs/plans/sprint-007-pr-f.md (pseudo-code)
 */
```

#### 2c. `bundle/dashboard/static/app.css` — 自前 CSS

設計順:

1. `:root` 変数 (design tokens、9 変数)
2. base reset (body / box-sizing)
3. `.layout-container` (max-width breakpoints)
4. typography (h1〜h5)
5. `.card` (article 代替)
6. table styling
7. form / input / button (`.btn-sm` / `.btn-secondary` / `.btn-contrast` / `.btn-outline`)
8. `.status-badge` + `.status-ALLOWED` / `.status-BLOCKED` 等の単独 selector
9. tab nav (`[data-tab]` styling)
10. spinner (aria-busy 代替)
11. utility classes (display, gap, margin)

300 行を超えないよう、汎用 utility は最小限に絞る。

### 3. Refactor

新規ファイルなので大きな refactor 無し。lint:
- `app.css`: stylelint があれば run
- `app.js`: 構文 check (`node -c app.js` 相当)

### 4. テスト全 PASS 確認

```bash
make unit  # 既存 380+ 件 + 新規 5〜6 件
```

---

## 既存テストへの影響

| テスト | 影響 | 対応 |
|---|---|---|
| `tests/test_dashboard.py` | 無し | そのまま |
| `tests/test_dashboard_csrf.py` | 無し | そのまま |
| `tests/test_dashboard_security_headers.py` | 無し | そのまま (CSP は PR I まで未変更) |
| `tests/test_dashboard_domain_validation.py` | 無し | そのまま |
| `tests/e2e/test_dashboard.py` | 無し（CDN htmx は引き続き動作、自前 JS は link 無し） | そのまま |

---

## Risk register

| リスク | 軽減策 |
|---|---|
| 自前 JS のロジックバグが PR H link で発覚 | 単体 test で `data-poll-url` 含むか / `setupPolls` 関数が存在するか等の構文 sanity check |
| CSS が後で template 書換時に過不足 | PR H で逐次 partial 単位に確認、必要なら CSS 追加 commit |
| `app.config["ASSET_VERSION"] = ""` で `?v=` query が空 | 初回 cache miss 1 回のみ、運用上問題無し (Gemini レビュー Low 確認済) |
| Flask static serving の MIME type が ブラウザで CSS/JS と認識されないリスク | test で Content-Type を assert |

---

## 受入基準

- [ ] `bundle/dashboard/static/app.css` 新設、design tokens 9 変数 + layout + components で ~300 行以内
- [ ] `bundle/dashboard/static/app.js` 新設、Plan F pseudo-code を実体化、**~200〜260 行 (コメント・IIFE・defensive 込)**
- [ ] `bundle/dashboard/app.py` に `ASSET_VERSION` env 注入
- [ ] `tests/test_dashboard_static.py` 新規 3 件 PASS
- [ ] `tests/test_dashboard_asset_version.py` 新規 2 件 PASS
- [ ] 既存 380+ unit + e2e 全 PASS（影響無し前提）
- [ ] index.html は **未変更**（CDN htmx のままで動作継続を確認）

---

## Rev.3 self-review 反映 (Low/Medium 補注)

| # | Sev | 指摘 | 反映 |
|---|---|---|---|
| I1 | Low | Plan F pseudo-code に登場する `data-bulk-scope` が data-* スキーマ表 (Plan F L179-194) に未記載 | Plan F (PR H 着手前) に追記、または data-* 表は ADR の data-* 設計原則の中で「補助属性」として注記 |
| I2 | Low | JS line 240 行は Rev.2 の 120〜150 見積を超過 | 受入基準を 200〜260 行に緩和、実態は 165 行 logic + 50 行コメント + 20 行 defensive。コメントは仕様正本 link を保つため削除しない |
| I3 | Medium | form submit / bulk action で fetch 失敗時 `swapInto` 非呼出 → swap 先が古い状態で残る | **PR H で検討**: `<small class="text-danger">エラー</small>` 等の error swap UI 追加、または `_pollTimers` のような retry 仕組み |
| I4 | Low | IIFE wrap によるグローバル汚染ゼロ + デバッグ容易性のトレードオフ | **PR H 以降で検討**: `if (window.__DEBUG__) window.__dashboard = {...};` の opt-in expose 機構 |

## Rev.3 Gemini 実装レビュー反映

| # | Sev | 指摘 | 反映 |
|---|---|---|---|
| G-G1 | Medium | `form.method || 'POST'` は **常に form.method 採用** (HTML form の method property は未指定時 'get' 返却で truthy)。POST fallback が効かない | **本 PR で fix**: `form.getAttribute('method') || 'POST'` に変更 (`null` で fallback 効く)。コメントで意図明記 |
| G-G2 | Medium | HTTP 401/403/404 時 backoff で再試行継続 → 無駄な負荷 | **PR H で検討**: 4xx (特に 401/403/404) を non-recoverable として polling 即停止、ユーザーに reload 促す |
| G-G3 | Medium | XSS / a11y: `innerHTML` swap は server エスケープに依存、`aria-live="polite"` 未配置 | **PR H で検討**: server 側エスケープは既に Jinja autoescape で対応、a11y 対応 (aria-live / aria-selected) は PR H で template 書換と同時 |
| G-G4 | Low | `console.warn` を URL constructor 失敗時にも出すと debug 容易 | 任意の改善、本 PR では skip (silent skip が UX 妥当) |
| G-G5 | Low | bulk action の `alert()` がメインスレッドブロック | 将来 toast UI に置換 (PR H 以降の UX 改善 follow-up) |
| G-G6 | Low | MutationObserver `subtree:true` は dashboard 規模で OK だが、PR H 後の 5s 周期再描画で `#main-content` 等に observe 範囲を限定する余地 | PR H で計測後に判断、本 PR では `document.body` のまま |

## 参照

- ADR 0004 (設計の正本): `docs/dev/adr/0004-dashboard-external-deps-removal.md`
- Plan F (pseudo-code 正本 + レビュー履歴): `docs/plans/sprint-007-pr-f.md`
