# Sprint 007 PR H: テンプレート書換え（メイン作業）

| 項目 | 値 |
|---|---|
| 作成日 | 2026-04-19 |
| 改訂 | Rev.3（self-review + Gemini 反映: cache busting 機能死 (context_processor 追加) + aria-labelledby 修正 / a11y 残課題は Sprint 008 follow-up に） |
| Sprint | 007 |
| PR | F (✅) → G (✅) → **H (本 PR)** → I |
| 親設計 | [ADR 0004](../dev/adr/0004-dashboard-external-deps-removal.md) (Rev.4) |
| 親計画 | [Plan F](sprint-007-pr-f.md) (Rev.4) — pseudo-code 正本 / [Plan G](sprint-007-pr-g.md) (Rev.3) |

> ⚠ **Rev.2 重要追加**: Plan G レビューで見逃された `data-bulk-toggle-all` (全選択 checkbox) の delegation 実装が PR G app.js に **不在** であることが Plan H レビューで発覚。PR H では app.js への補正実装も含める。同時に triggerFrom listener の重複 attach bug も修正。

---

## ゴール

Sprint 007 の **メイン作業**: dashboard の全 template (`index.html` + `partials/*.html`) を `hx-*` から `data-*` + 自前 class に完全書換し、自前 CSS/JS の link を **追加**（CDN htmx/pico は引き続き並存、PR I で削除）。

### Deliverables

1. **`bundle/dashboard/static/app.js` 補正**（PR G の漏れを修正、Rev.2 追加）
   - **`data-bulk-toggle-all` delegation 追加**: change event で `[data-bulk-toggle-all]` の checked 状態を scope 内 `[data-bulk-select]` に伝播（`toggleAllInbox` 代替）
   - **`data-bulk-scope` を `setupPolls` 系の補助属性として data-* スキーマに格上げ**: bulk button が table 全体を `data-bulk-scope` 親要素として参照する
   - **triggerFrom listener の重複 attach bug 修正**: `_triggerListenersByTarget` Map で同 selector に対する listener を 1 回のみ attach する
2. `bundle/dashboard/templates/index.html` 書換
   - 自前 CSS/JS link 追加: **`{% if asset_version %}?v={{ asset_version }}{% endif %}` defensive 形式で全箇所統一**
   - 既存 CDN link (pico/htmx) は **当面維持**（PR I で削除）
   - **`<body hx-headers='{...}'>` の `hx-headers` 属性を削除**（CDN htmx に CSRF header 渡しを止める、自前 JS が `csrf()` で都度送出）
   - inline `<style>`, `<script>`, `onclick=`, `style="..."` を **完全削除**
   - `<meta name="csrf-token">` は `<head>` に **維持**（pseudo-code 必須要件）
   - 4 polling div を `data-poll-url="/path"` + `data-poll-interval="5000"` に置換
   - status-filter `<form>` を `<div id="requests-filter-form" data-poll-url="/partials/requests" data-poll-interval="5000" data-trigger-from="#status-filter:change" data-include="#status-filter" data-swap-target="#requests-container">` に変更（form タグは無くす、submit button が無く form の意味が無いため）
   - tab nav `<a onclick="showTab('...')">` を `<a data-tab="..." href="#">` に置換
   - **tab content 初期 hidden を `class="hidden"` で表現**（`style="display:none"` は削除、`.hidden { display: none; }` は PR G の app.css に既存）
   - **アクセシビリティ補強（Plan G G3 follow-up）**: tab nav に `role="tablist"`、tab nav `<a>` に `role="tab"` + `aria-selected="true|false"`、tab content `<div>` に `role="tabpanel"` + `aria-labelledby` 付与。polling target に `aria-live="polite"` 付与
3. `bundle/dashboard/templates/partials/inbox.html` 書換
   - 各 form を `<form action="/api/inbox/{accept|reject}" method="POST" data-swap-target="#tab-inbox" data-confirm="..." data-json-body="{{ {'record_id': r._id}|tojson|forceescape }}">` に置換
     - **重要**: `data-json-body` は **`{{ {'record_id': r._id}|tojson|forceescape }}` パターン**で属性値を生成（既存 hx-vals と同じ escape 戦略、attribute injection / XSS 防止）
   - `<script>bulkInbox/toggleAllInbox</script>` 削除、bulk button を `<button type="button" data-bulk-action="/api/inbox/bulk-{accept|reject}" data-bulk-target="#tab-inbox" data-bulk-confirm="...">` に置換
   - 全選択 checkbox を `<input type="checkbox" id="inbox-select-all" data-bulk-toggle-all data-bulk-toggle-scope="[data-bulk-scope='inbox']">` に置換（id 維持で e2e 互換）
   - **table 全体を `<table data-bulk-scope="inbox">` で囲む**（または table の親 `<div>` に付与、bulk button もこの scope 内に配置）
   - 個別 checkbox を `<input type="checkbox" class="bulk-cb" data-bulk-select value="{{ r._id }}">` に置換
   - inline `style="..."` を class 化
4. `bundle/dashboard/templates/partials/whitelist.html` 書換
   - 各 form (allow / dismiss / restore / revoke / allow-path) を `<form action="/api/whitelist/..." method="POST" data-swap-target="#tab-whitelist" data-confirm="...">` に置換（hx-confirm 有り版のみ data-confirm 付与）
   - URL suggest IIFE `<script>` 削除
   - **既存 `<li data-url=... data-target="path-{{ host|replace('.', '-') }}" onclick=...>` を `<li class="url-suggest-item" data-url="{{ url }}" data-suggest-target="#path-{{ host|replace('.', '-') }}">` に rename**（`data-target` 完全削除、`#` prefix 追加、`onclick` 削除）
   - inline `style="..."` を class 化（最も多い、~30 箇所）
5. `bundle/dashboard/templates/partials/requests.html` / `stats.html` / `tool-uses.html` 書換
   - inline `style="..."` を class 化（path-cell / status-badge は既存 PR G CSS で対応）
6. `tests/test_dashboard_inline_assets.py` (新規) — BS4 ベースで `<script>` / `<style>` / `style=` / `onclick=` / `onsubmit=` 等不在を assert
   - 全 6 endpoint (/, /partials/{stats,requests,tool-uses,inbox,whitelist}) で個別 assert
   - csrf-token meta 存在
   - 不要な `data-bulk-toggle-all` のような fixture 依存テストは本 PR では skip（fixture は別 PR）
7. `tests/e2e/test_dashboard.py` selector 追従 — `form[hx-post*=]` → `form[action*=]` 等
8. `docs/plans/sprint-007-pr-h.md`（本ファイル）

### Non-goals

- CDN link 削除（PR I）
- CSP `'self'` 厳格化（PR I）
- E2E オフライン動作確認（PR I）
- dark theme 対応（Sprint 007 後の follow-up）
- error UI swap（Plan G I3 で PR H 検討事項とした、本 PR で着手するか判断）

---

## 重要な設計原則（Plan F / Plan G から継承）

1. **両持ち禁止**: PR H の commit 単位で `hx-*` と `data-*` を **同 form で並走させない**。CDN htmx と自前 JS が両方同 form を submit すると二重 POST する。partial 単位で「commit 1: hx-* 削除 + data-* 追加」を完結させる。
2. **自前 JS link 追加は最後**: 各 partial の書換 commit が完了してから、index.html commit で `<script src=".../static/app.js">` を追加。これにより、自前 JS が load される瞬間には全 partial の data-* が揃っている。
3. **CDN htmx は当面維持**: 自前 JS の bug が出ても CDN htmx が並走して機能する保険。template の `hx-*` は削除済なので CDN htmx は実質 no-op だが、HTMX core の event 監視は走る。CSP も `'unsafe-inline'` を当面維持で安全網。
4. **`<meta name="csrf-token">` 維持**: pseudo-code の `csrf()` が依存。index.html `<head>` から削除しないこと。

---

## Commit 分割案

PR H 内で以下の commit 順を想定:

| # | Commit | 内容 |
|---|---|---|
| 0 | **app.js 補正** (Plan H 追加) | data-bulk-toggle-all delegation、data-bulk-scope 補助属性、triggerFrom listener 重複 attach 修正 |
| 1 | partials/stats.html / requests.html / tool-uses.html 書換 + tests/test_dashboard_inline_assets.py 追加（該当 partial の test のみ enable、他 partial は skip） | 簡易 partial と test を 1:1 で同時 commit、CI 緑維持 |
| 2 | partials/inbox.html 書換 + bulk action / json-body 対応 + tests 該当 partial enable | bulk action / json-body / data-bulk-toggle-all 動作 |
| 3 | partials/whitelist.html 書換 + url-suggest rename + tests 該当 partial enable | form 数最多、url-suggest IIFE 削除、`data-target` → `data-suggest-target` rename |
| 4 | index.html 書換 + 自前 CSS/JS link 追加 + tab nav data-tab + hx-headers 削除 + tests 該当 partial enable | 中核、自前 JS が初めて load される、aria-* 補強、`{% if asset_version %}?v={{ ... }}{% endif %}` 統一 |
| 5 | tests/e2e/test_dashboard.py selector 追従 | E2E が新仕様で動くこと確認 |

> **Commit 0 が必要な理由（Rev.2 重要）**: PR G app.js には `data-bulk-toggle-all` delegation が無く、PR H で template だけ書換えても全選択 checkbox が機能しない。app.js を template 書換より **先に** 補正することで、各 partial 書換時に全機能が揃った状態で動作確認できる。
>
> **中間 commit の機能性について**: 各 partial 書換 commit (1〜3) では、書換済 partial は自前 JS で動作するが、まだ書換えていない partial は CDN htmx で動作（hx-* がまだ残っている）。index.html commit (4) で自前 JS が初めて全画面に link されるが、それまでは CDN htmx のみで全機能が壊れない。**dashboard は中間 commit でもブラウザ操作可能**。

実際は 1 PR / 1 squash merge なので commit 単位は柔軟（GitHub の squash で 1 commit に集約）。ただしレビュー時に commit 履歴で書換ステップを追えるように分割する。

---

## TDD: tests 追加（Red → Green）

`tests/test_dashboard_inline_assets.py`:

```python
"""Sprint 007 PR H: dashboard template が inline JS / CSS を含まないことを保証。

ADR 0004 (Dashboard 外部依存ゼロ化) の必須要件。PR I の CSP 'self' only 厳格化の
前提条件として、全 partial / index.html から <script> / <style> / style="..." /
onclick= / onsubmit= 等の inline event handler を完全に削除する。

raw template grep ではなく Flask test client で render 後の HTML を BeautifulSoup
で parse することで、Jinja コメント等の false positive を回避する。
"""

import os
import sys
import unittest

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bundle", "dashboard"))

from app import app

bs4 = pytest.importorskip("bs4")
BeautifulSoup = bs4.BeautifulSoup


_INLINE_HANDLERS = (
    "onclick", "onsubmit", "onchange", "onload", "onerror",
    "onmouseover", "onmouseout", "onfocus", "onblur",
)


class TestDashboardInlineAssets(unittest.TestCase):
    """全 endpoint の render 結果に inline asset が含まれないこと。"""

    @classmethod
    def setUpClass(cls) -> None:
        # tests 用の inbox / policy / DB を最小設定
        # (各 endpoint が render できる程度の env が必要)
        ...  # 実装時に必要分だけ準備

    def setUp(self) -> None:
        app.config["TESTING"] = True
        app.config["WTF_CSRF_ENABLED"] = False
        self.client = app.test_client()

    def _get_soup(self, path: str) -> "BeautifulSoup":
        rv = self.client.get(path)
        self.assertEqual(rv.status_code, 200, f"GET {path} → {rv.status_code}")
        return BeautifulSoup(rv.data, "html.parser")

    def _assert_no_inline_assets(self, soup: "BeautifulSoup", endpoint: str) -> None:
        # <script> 子要素 (text 含む) は禁止、<script src="..."> は OK
        for s in soup.find_all("script"):
            self.assertFalse(
                (s.string or "").strip(),
                f"{endpoint}: inline <script> found: {s.string[:50]!r}",
            )

        # <style> element は完全禁止
        styles = soup.find_all("style")
        self.assertEqual(
            len(styles), 0,
            f"{endpoint}: <style> element found ({len(styles)})",
        )

        # 全要素の style="..." 属性禁止
        with_style = soup.find_all(attrs={"style": True})
        self.assertEqual(
            len(with_style), 0,
            f"{endpoint}: style=\"...\" attr found on {len(with_style)} elements",
        )

        # inline event handler 禁止
        for handler in _INLINE_HANDLERS:
            els = soup.find_all(attrs={handler: True})
            self.assertEqual(
                len(els), 0,
                f"{endpoint}: {handler}=\"...\" attr found on {len(els)} elements",
            )

    def test_index_no_inline_assets(self) -> None:
        soup = self._get_soup("/")
        self._assert_no_inline_assets(soup, "/")

    def test_index_csrf_meta_present(self) -> None:
        soup = self._get_soup("/")
        meta = soup.find("meta", attrs={"name": "csrf-token"})
        self.assertIsNotNone(meta, "<meta name=\"csrf-token\"> missing in <head>")
        self.assertTrue(meta.get("content"), "csrf-token content empty")

    def test_partial_stats_no_inline_assets(self) -> None:
        soup = self._get_soup("/partials/stats")
        self._assert_no_inline_assets(soup, "/partials/stats")

    def test_partial_requests_no_inline_assets(self) -> None:
        soup = self._get_soup("/partials/requests")
        self._assert_no_inline_assets(soup, "/partials/requests")

    def test_partial_tool_uses_no_inline_assets(self) -> None:
        soup = self._get_soup("/partials/tool-uses")
        self._assert_no_inline_assets(soup, "/partials/tool-uses")

    def test_partial_inbox_no_inline_assets(self) -> None:
        soup = self._get_soup("/partials/inbox")
        self._assert_no_inline_assets(soup, "/partials/inbox")

    def test_partial_whitelist_no_inline_assets(self) -> None:
        soup = self._get_soup("/partials/whitelist")
        self._assert_no_inline_assets(soup, "/partials/whitelist")

    def test_data_swap_target_present_on_inbox_forms(self) -> None:
        """inbox の accept/reject form に data-swap-target が存在。"""
        # inbox 空 (= "未承認のリクエストはありません") では form は出ないので
        # これは inbox が空でない fixture 前提。簡易には skip も可。
        ...
```

## E2E test selector 追従

`tests/e2e/test_dashboard.py`:

| 既存 selector | 新 selector |
|---|---|
| `form[hx-post*="accept"] button:has-text("許可")` | `form[action*="/accept"] button:has-text("許可")` |
| `form[hx-post*="reject"] button:has-text("却下")` | `form[action*="/reject"] button:has-text("却下")` |
| `button:has-text("選択を一括許可")` | 同左 (text-based、selector 影響無し) |
| `#inbox-select-all` | 同左 (id ベース) |

E2E test 用の data-* 属性が必要なら `[data-test-action="accept"]` 等の追加も検討（過剰なら避ける）。

---

## Risk register

| リスク | 軽減策 |
|---|---|
| **両持ち**: 同 form に hx-post と data-swap-target が並走で二重 POST | partial 単位 commit で hx-* を **完全削除** してから data-* を追加。レビュー時に diff を見て両持ちの行が無いか確認 |
| **`<meta name="csrf-token">` 削除事故** | `tests/test_dashboard_inline_assets.py::test_index_csrf_meta_present` で防衛 |
| **partial の inline `<script>` 削除漏れ** | BS4 ベース test で全 partial を render して assert |
| **whitelist.html の `data-target` rename 漏れ** (Rev.2 強化) | template に `data-target` が **0 件** であることを test で assert (`soup.find_all(attrs={"data-target": True})` == []) |
| **inline style class 化漏れ** | BS4 ベース test で `attrs={"style": True}` を 0 件 assert |
| **`<body hx-headers='{...}'>` 削除漏れ** (Rev.2 追加) | BS4 test で body element に `hx-headers` 属性が無いことを assert |
| **bulk-toggle-all 機能不全** (Rev.2 重要) | PR G app.js への補正 commit を本 PR 最初に置く。E2E P1 の `test_inbox_bulk_accept` で動作検証 |
| **`data-json-body` 内の attribute injection / XSS** (Rev.2 High) | `{{ {'record_id': r._id}|tojson|forceescape }}` パターンで Jinja escape を強制。属性値全体を `data-json-body="..."` で double quote 包囲（hx-vals と同戦略）|
| **triggerFrom listener 重複 attach** (Rev.2 追加) | `_triggerListenersByTarget` Map で同 selector への listener attach を 1 回に制限 |
| **CDN htmx が削除済 hx-* を見つけられず動作変化** | hx-* を完全削除すれば htmx は no-op。`hx-headers` も削除しているので CSRF header 渡しの干渉も無し。並存期間は htmx が完全 idle |
| **Flask static MIME** | PR G で test 確認済 |
| **asset_version cache busting** | `{% if asset_version %}?v={{ asset_version }}{% endif %}` defensive (Plan G review G3 反映、本 PR で **全箇所統一**) |
| **E2E が壊れる** | 6 ケース x P1 のみ、selector 追従で再 PASS、`make e2e` で確認 |
| **tab content 初期 hidden** | `style="display:none"` 削除と `class="hidden"` 付与を同時、tab-requests のみ active 状態（class なし）、他 3 tab は class="hidden" |
| **a11y (aria-*)** | tab nav に `role="tablist"` / `role="tab"` / `aria-selected`、tab content に `role="tabpanel"`、polling target に `aria-live="polite"`。app.js の click delegation で `aria-selected` を更新する追加実装 |
| **M-1 ステータス**: PR H 完了時点ではまだ resolved していない | Plan H と CHANGELOG の文言で「PR I で M-1 完了」と明記、誤認回避 |

---

## 受入基準（Rev.2）

- [ ] 全 template から `hx-*` 属性が消える（grep で 0 件、`hx-headers` も含む）
- [ ] 全 template から inline `<script>` ブロック / `onclick=` / `style=` / `<style>` が消える（BS4 test で確認）
- [ ] 全 template から `data-target=` が消える（whitelist の url-suggest が `data-suggest-target` に rename 完了）
- [ ] index.html `<head>` に `<meta name="csrf-token">` が **残る**
- [ ] index.html に自前 CSS/JS link 追加、`{% if asset_version %}?v={{ asset_version }}{% endif %}` 形式で統一
- [ ] CDN htmx / pico の link は **当面維持**（PR I で削除）
- [ ] **app.js に `data-bulk-toggle-all` delegation 追加** + triggerFrom listener 重複 attach 修正
- [ ] **app.js に aria-selected 更新ロジック追加**（tab nav の click delegation 内）
- [ ] `tests/test_dashboard_inline_assets.py` 新規 7+ 件 PASS
- [ ] 既存 391 unit 全 PASS
- [ ] `tests/e2e/test_dashboard.py` selector 追従、6 ケース全 PASS（特に `test_inbox_bulk_accept` で全選択動作確認）
- [ ] dashboard 起動、ブラウザで全 tab 動作確認（手動 + E2E）

---

## Rev.2 反映マッピング（Plan review High/Medium）

| # | Sev | 指摘 | 反映先 |
|---|---|---|---|
| H1 | High | `data-json-body` の Jinja escape pattern が抜けて attribute injection / XSS リスク | deliverables 3 に `{{ {'record_id': r._id}|tojson|forceescape }}` パターン明示、Risk register に追加 |
| H2 | High | `toggleAllInbox` 代替の `data-bulk-toggle-all` delegation が PR G app.js に **未実装** | **commit 0 で PR G app.js を補正**、deliverables 1 に追加 |
| M1 | Medium | Commit 順序で test Red 中間 commit が CI 緑にならない | commit 1〜4 で「partial 書換 + 該当 partial の test enable」を 1:1 でセット、未書換 partial の test は skip |
| M2 | Medium | body の `hx-headers='{...}'` 削除が deliverables に無い | deliverables 2 に明示、Risk register に追加 |
| M3 | Medium | onclick 削除明記 | deliverables 4 で `<li>` の onclick 削除を明記、BS4 test で全 partial 検証 |
| M4 | Medium | form submit handler 競合 (個別 form + bulk button 同 form 内混在) | bulk button は `<button type="button">` で submit event 発火しない、form submit は `[data-swap-target]` のみ起動するため競合無し（受入基準で動作確認） |
| M5 | Medium | triggerFrom listener 重複 attach bug | commit 0 で app.js 補正 |
| M6 | Medium | record_id の文字種前提 | inbox.py の `_RECORD_ID_RE` で `[A-Za-z0-9:T_-]+` に制限済（既存 H-2 対策）。`tojson|forceescape` で多重防御 |
| L1 | Low | partial 単位 commit の中間機能性 | 中間 commit でも CDN htmx が動くため操作可能、明文化 |
| L2 | Low | `data-target` rename の `#` prefix | deliverables 4 に明示 |
| L3 | Low | tab nav 初期 hidden | deliverables 2 で `class="hidden"` 明示 |
| L4 | Low | status filter form vs div | deliverables 2 で `<div>` 化を明示 |
| L5 | Low | asset_version 表記統一 | deliverables 2 で `{% if ... %}` 形式に統一 |
| L6 | Low | Flask url_for vs ?v= 直書き | 現状の `{% if asset_version %}?v={{ asset_version }}{% endif %}` で十分、url_for は将来検討 |
| L7 | Low | href="#" スクロール問題 | `preventDefault()` で抑止、現状 OK |
| L8 | Low | aria-live / aria-selected | deliverables 2 で role/aria-* 付与、app.js で aria-selected 更新 |
| L9 | Low | 未実装 test (`...`) | data-swap-target 系の fixture 依存 test は本 PR で **skip**（fixture は Sprint 008 follow-up）|
| L10 | Low | M-1 status | Plan H と CHANGELOG で「PR I で M-1 完了」明記 |

---

## Rev.3 self-review + Gemini 反映

### Claude self-review (Phase 1)

| # | Sev | 指摘 | 対応 |
|---|---|---|---|
| H-1 | High | `app.config["ASSET_VERSION"]` だけでは Jinja から参照不可 → cache busting 機能死 | **本 PR で fix**: `app.py` に `@app.context_processor` 追加。tests に template render 検証 +2 件 (?v=test-sha-abc が link href に出る、空時は ?v= 自体が出ない) |
| M-1 | Medium | `aria-labelledby="tabs"` (tablist の id) は ARIA 仕様違反、tab 要素の id を指すべき。他 3 tabpanel は aria-labelledby 自体無し | **本 PR で fix**: tab nav `<a>` に `id="tabnav-{name}"` 付与、各 tabpanel `aria-labelledby="tabnav-{name}"` 完備 |
| M-2 | Medium | `data-poll-interval=0` semantics が Plan F/H 未仕様化 | app.js コメントには明記済、Plan F は次 PR で正本化 (Sprint 008 か follow-up issue) |
| L-4 | Low | `_triggerListenersByTarget` Map cleanup なし (removedNodes hook 未対応) | dashboard では polling element がほぼ静的、実害小、Sprint 008 follow-up |
| L-5 | Low | partial swap 後の master checkbox 状態リセット | 意図通り (許可後リスト変化に追従)、修正不要 |
| L-6 | Low | `data-suggest-target="#path-{{ host|replace('.', '-') }}"` の id 衝突 (Gemini M-3 と同根) | Sprint 008 follow-up |

### Gemini 再レビュー (Phase 3)

| # | Sev | 指摘 | 対応 |
|---|---|---|---|
| GM-1 | Medium | tabindex の動的制御欠如 (WAI-ARIA Authoring Practices: active のみ tabindex=0、他は -1) | **Sprint 008 a11y follow-up**: app.js の tab click delegation に tabindex 更新追加 |
| GM-2 | Medium | id 衝突 (`c.host|replace('.', '-')` だけでは `:` `[` 等の特殊文字に対応不足) | **Sprint 008 follow-up**: slugify or hash 化 |
| GM-3 | Medium | `data-bulk-toggle-all` の `checkbox.checked = true` は change event 発火しない → スクリーンリーダー通知不足 | **Sprint 008 a11y follow-up**: `dispatchEvent(new Event('change'))` 追加 |
| GL-1 | Low | `data-poll-interval="0"` を `data-poll-once="true"` 等の明示的属性に | M-2 と同根、Sprint 008 で属性名再設計 |
| GL-2 | Low | `url_for('static', filename=..., v=asset_version)` 採用検討 | 単一 app 構成では実害なし、現状維持 |

### 判定

- Claude self-review: 修正必要 → H-1/M-1 修正で **通過**
- Gemini self-review: **merge OK** (Medium 3 は Sprint 008 follow-up)

a11y 残課題 (GM-1, GM-3) は **Sprint 008 で `dashboard a11y polish` task** として独立扱い (`#tabindex` / `dispatchEvent` / `slugify host id` の 3 fix で完結する小規模 task)。

---

## 参照

- ADR 0004: `docs/dev/adr/0004-dashboard-external-deps-removal.md`
- Plan F: `docs/plans/sprint-007-pr-f.md` (pseudo-code + data-* schema)
- Plan G: `docs/plans/sprint-007-pr-g.md` (CSS / JS 実装の line 数 + 設計 follow-up)
