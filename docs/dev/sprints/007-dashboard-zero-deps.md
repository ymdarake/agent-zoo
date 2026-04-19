# Sprint 007: Dashboard 外部依存ゼロ化 (pico/htmx → 自前 HTML/CSS/vanilla JS)

| 項目 | 値 |
|---|---|
| 期間 | 2026-04-19（1 日、ADR 0004 起票 → PR I CI green まで） |
| テーマ | [2026-04-18 包括レビュー](../reviews/2026-04-18-comprehensive-review.md) **M-1 / L-6** (CDN 経由 SRI 無し pico/htmx) を解消し、dashboard を **完全に外部依存ゼロ** にする |
| 親計画 | [2026-04-18 統合作業ブレークダウン](../../plans/2026-04-18-consolidated-work-breakdown.md) Sprint 007 |
| ADR | [ADR 0004: Dashboard 外部依存ゼロ化](../adr/0004-dashboard-external-deps-removal.md) |
| 完了 PR | #48 (F), #49 (G), #50 (H), #51 (I) |
| 関連 plan docs | [PR F plan](../../plans/sprint-007-pr-f.md) (Rev.4), [PR G plan](../../plans/sprint-007-pr-g.md) (Rev.3), [PR H plan](../../plans/sprint-007-pr-h.md) (Rev.3), [PR I plan](../../plans/sprint-007-pr-i.md) (Rev.3) |
| Milestone | **Beta release candidate 到達** |

---

## Sprint Goal

Sprint 006 で Medium / Supply chain / TOCTOU が片付いた状態に対し、**dashboard 層に残った最大の外部依存** (pico.css 2.x + htmx.org 2.0.4 を CDN から SRI 無しで読み込み) を完全に撤去し、自前 HTML/CSS/vanilla JS に置換する。

- **PR F**: ADR 0004 起票 + 設計（HTMX 属性棚卸し / CSS design tokens / vanilla JS API / 移行戦略）
- **PR G**: 自前 CSS (~284 行) + vanilla JS (~268 行) の基盤追加（template への link 追加は PR H）
- **PR H**: template 全書換（`hx-*` → `data-*`、inline `<script>`/`<style>`/`style=`/`onclick=` 完全削除、a11y 補強）
- **PR I**: CDN link 削除 + CSP `'self'` 厳格化 + Permissions-Policy 追加（M-1 / L-6 完全 resolved）

---

## Decisions

### PR F: ADR 0004 起票 + 設計（#48）

| # | 決定 | 結果 |
|---|---|---|
| F1 | self-host (代替 A) ではなく **自前実装** を選択 | ✅ ADR 0004 Alternatives で「dashboard は数画面規模、自前 552 行 vs ライブラリ全部」のトレードオフ評価、長期 simple |
| F2 | swap 先 attribute は **`data-swap-target`** | ✅ 既存 whitelist.html:121 が `data-target="path-..."` を id 文字列で使用済との命名衝突回避 (self-review R3) |
| F3 | polling 周期は `data-poll-url` + `data-poll-interval` 分離 | ✅ path 内の `:` 衝突回避、`interval=0` で「load only」semantics (HTMX hx-trigger=load 互換) |
| F4 | エラー時 exponential backoff | ✅ `base × 2^failures`、最大 60s。連続失敗で負荷増回避 (Gemini G3) |
| F5 | MutationObserver で `addedNodes` / `removedNodes` 両方走査 | ✅ removedNodes は再帰しないので明示的に `n.matches` + `n.querySelectorAll` 両方処理 (Gemini G2) |
| F6 | CSRF token は毎 fetch ごとに `<meta name=\"csrf-token\">` から読む | ✅ rotation 対応、抽出保持禁止 (Gemini G1) |
| F7 | inline `<script>` / `<style>` / `style=\"...\"` / `onclick=` を完全排除 | ✅ PR I の CSP `'self'` only 達成のため、`<meta name=\"csrf-token\">` だけは `<head>` に維持 |
| F8 | pico の値（色 hex / size px / breakpoint px）は事実情報として参考、selector 構造 / class 名は独自実装 | ✅ MIT LICENSE 派生著作物境界を明確に分離 |

### PR G: 自前 CSS + vanilla JS 基盤（#49）

| # | 決定 | 結果 |
|---|---|---|
| G1 | `bundle/dashboard/static/app.css` 新設 (~284 行) | ✅ design tokens 9 + status badge tokens 6 を `:root` に flat 定義（dark theme で同名変数を `@media (prefers-color-scheme: dark)` で上書きできる構造）|
| G2 | `bundle/dashboard/static/app.js` 新設 (~240 行) | ✅ Plan F pseudo-code 実体化、IIFE wrap + 'use strict'、defensive guards (isNaN / pollUrl 欠落) |
| G3 | `app.config[\"ASSET_VERSION\"]` env 注入 | ✅ default 空文字、`{% if asset_version %}?v={{ ... }}{% endif %}` defensive Jinja で空時 query 省略 |
| G4 | template への link 追加は **PR H で**（PR G では未 link） | ✅ revert 戦略、PR G が独立 revertable |
| G5 | `tests/test_dashboard_static.py` で Critical API 識別子 (MutationObserver / removedNodes / `_pollTimers` / document.hidden) の含有を assert | ✅ Plan F Rev.4 の Critical 要素が抜けないことを保証 |
| G6 | `form.method || 'POST'` bug fix | ✅ HTMLFormElement.method は未指定時 `'get'` 返却で truthy → `getAttribute('method') || 'POST'` に変更 (Gemini レビュー G-G1) |

### PR H: テンプレート書換え（#50）

| # | 決定 | 結果 |
|---|---|---|
| H1 | app.js に **`data-bulk-toggle-all` delegation 追加** | ✅ PR G の漏れ。Plan H レビューで発覚し本 PR で実装、id="inbox-select-all" 維持で e2e 互換 |
| H2 | `_triggerListenersByTarget` Map で **triggerFrom 重複 attach 防止** | ✅ setupPolls 再呼出で listener 数 N→2N→4N 問題を解消 |
| H3 | tab nav click で **aria-selected 更新** 追加 | ✅ a11y 仕様準拠 (Plan G G3 follow-up) |
| H4 | `data-poll-interval=\"0\"` を **「load only」semantics 化** | ✅ HTMX hx-trigger=\"load\" 互換、setInterval 設定なし |
| H5 | **`data-json-body`** は `{{ {'record_id': r._id}|tojson|forceescape }}` で attribute injection / XSS 完全防御 | ✅ Plan H Plan review High で発覚した escape pattern を明示 |
| H6 | bulk button + table を `<div data-bulk-scope=\"inbox\">` で包む | ✅ btn.closest が table 内 [data-bulk-select] にアクセス可能、E2E test_inbox_bulk_accept で動作実証 |
| H7 | whitelist.html の `data-target` を `data-suggest-target` に rename + `#` prefix 追加 | ✅ 命名衝突解消、url-suggest 機能維持 |
| H8 | `<body hx-headers='{...}'>` を削除 | ✅ CDN htmx 経由の CSRF header 渡しを排除、self.js のみ送出 |
| H9 | tab content 初期 hidden を `class=\"hidden\"` で表現 | ✅ inline `style=\"display:none\"` 削除、`.hidden { display: none; }` は PR G app.css 既存 |
| H10 | role=\"tablist\"/tab/tabpanel + aria-labelledby + aria-live=\"polite\" 完備 | ✅ tab nav `<a>` に `id=\"tabnav-{name}\"` 付与、各 tabpanel が正しく参照 |
| H11 | `tests/test_dashboard_inline_assets.py` 新規 8 件 (BS4 ベース) | ✅ 全 6 endpoint で hx-* / inline asset / data-target 不在を保証、Jinja コメント false positive 回避 |
| H12 | `@app.context_processor` で **`asset_version`** を Jinja に注入 | ✅ self-review H-1 で発覚した「app.config だけでは Jinja 参照不可」を fix、cache busting 機能を実動作化 |
| H13 | E2E selector を `form[hx-post*=]` → `form[action*=]` に追従 | ✅ 7 ケース全 PASS |

### PR I: CDN 完全削除 + CSP 'self' 厳格化（#51）

| # | 決定 | 結果 |
|---|---|---|
| I1 | index.html から CDN link 完全削除 | ✅ `cdn.jsdelivr.net` / `unpkg.com` 文字列が template から 0 件 |
| I2 | CSP 設定を **`response.headers[\"Content-Security-Policy\"] = ...`** で強制上書き | ✅ `setdefault` から変更、他 layer の弱い CSP 防衛 (review H-1) |
| I3 | CSP から `'unsafe-inline'` / CDN ドメインを完全削除、`'self'` のみに | ✅ default-src/style-src/script-src 等を全 `'self'` 化 |
| I4 | **`form-action 'self'`** 明示追加 | ✅ default-src の fallback 対象外 (CSP3)、attribute injection によるデータ外部送信を防御 |
| I5 | **`Permissions-Policy: camera=(), microphone=(), geolocation=(), payment=()`** 追加 | ✅ defense-in-depth、不要 Browser API 全 deny |
| I6 | `tests/test_dashboard_csp.py` 新規 11 件 | ✅ CSP value parse + 'unsafe-inline'/CDN 不在 + each directive self-only + form-action + Permissions-Policy + 強制上書き snapshot |
| I7 | `tests/test_dashboard_inline_assets.py` 拡張 | ✅ CDN URL / `<base>` / dns-prefetch・preconnect to CDN 不在 assert |
| I8 | `tests/test_dashboard_security_headers.py` に厳格化 assert (review H-2) | ✅ 既存 test 側でも `'unsafe-inline'` / CDN ドメイン不在を防衛 (二重防御) |
| I9 | `tests/e2e/test_dashboard_offline.py` 新規 3 件 | ✅ Playwright route で CDN を強制 abort、block 件数 == 0 (request すら飛んでいない) を実証 |
| I10 | `docs/dev/reviews/2026-04-18-comprehensive-review.md` の M-1 / L-6 を resolved マーク | ✅ M-1: Sprint 007 PR F〜I で resolved、L-6: H-4 + PR I の 2 段で resolved |
| I11 | `docs/dev/security-notes.md` に「dashboard 外部依存ゼロ化」セクション追加 | ✅ Before/After 比較表、攻撃面消滅効果、Sprint 008 follow-up、設計判断 |

---

## Commit Log（main への merge 履歴）

```
0f03e3f :lock: Sprint 007 PR I: CDN 完全削除 + CSP 'self' 厳格化 (M-1 / L-6 resolved) (#51)
41284ca :recycle: Sprint 007 PR H: dashboard template を hx-* から data-* に全書換 (#50)
a391aeb :sparkles: Sprint 007 PR G: 自前 CSS + vanilla JS 基盤追加 (#49)
bb3b828 :memo: Sprint 007 PR F: ADR 0004 起票 + Plan doc 作成 (#48)
```

---

## 検証

### CI / テスト

| Phase | unit tests | E2E P1 | 備考 |
|---|---|---|---|
| Sprint 006 完了時 | 287 | 7 | baseline |
| PR F merge 後 | 287 | 7 | docs only、変化なし |
| PR G merge 後 | 391 (+5) | 7 | static asset / asset_version test 追加 |
| PR H merge 後 | 396 (+5) | 7 | inline_assets BS4 test + asset_version 拡張 |
| PR I merge 後 | **413 (+17)** | **10 (+3)** | CSP test 11 + inline_assets +3 + security_headers +2 + offline E2E 3 |

CI: 全 PR で Unit (Python 3.11/3.12/3.13) + Audit + Compose digest verify + E2E P1 全 PASS、regression なし。

### 包括レビュー解決状況

| ID | Severity | 内容 | 状態 |
|---|---|---|---|
| **M-1** | Medium | dashboard が外部 CDN を SRI 無しで読み込み | ✅ Sprint 007 PR F〜I で **完全 resolved** (CDN link 削除 + CSP 'self' only) |
| **L-6** | Low | inbox.html 属性内未エスケープ | ✅ H-4 (Sprint 005) で `\\|tojson\\|forceescape` 適用 + PR I で CSP 'self' only により script 注入経路完全封鎖、2 段で resolved |

### 残課題（Sprint 008 follow-up）

| # | 内容 | Severity | Sprint |
|---|---|---|---|
| F1 | a11y polish (tab nav の `tabindex` 動的更新、WAI-ARIA Authoring Practices) | Low | 008 |
| F2 | bulk-toggle-all で `dispatchEvent(new Event('change'))` 追加 (スクリーンリーダー通知) | Low | 008 |
| F3 | `data-suggest-target=\"#path-{{ host|replace('.', '-') }}\"` の id 生成を slugify or hash 化 | Low | 008 |
| F4 | `data-poll-interval=\"0\"` semantics を `data-poll-once=\"true\"` 等の明示属性に再設計 | Low | 008 |
| F5 | `_triggerListenersByTarget` Map の removedNodes hook 対応 (memory leak 防止、polling element がほぼ静的なため実害小) | Low | 008 |
| F6 | dark theme 対応 (`@media (prefers-color-scheme: dark)`) | Low | 008+ |
| F7 | COOP `same-origin` / CORP `same-origin` 追加 (defense-in-depth) | Low | 008 |
| F8 | X-Frame-Options 等の hardening を `setdefault` から `=` 強制上書きに統一 (一貫性) | Low | 008 |
| F9 | E2E test での CSP violation capture (`page.on('console', ...)` で `Refused to apply inline style`) | Low | 008 |

---

## 学び / 気づき

### Plan review pattern が引き続き機能

各 PR で Plan を作って **Claude subagent + Gemini 並行レビュー** に出すことで、実装着手前に High blocker を多数検出:

- **PR F**: data-target 命名衝突 (既存 whitelist.html が id 文字列で使用済) を発見、`data-swap-target` に rename
- **PR G**: form.method || 'POST' の bug (HTML 未指定時 'get' 返却で fallback 効かず)
- **PR H**: data-json-body の Jinja escape pattern 漏れ (XSS リスク)、PR G app.js の bulk-toggle-all 実装漏れを Plan review で発見、PR H で補正
- **PR I**: setdefault → 強制上書きの sabotage リスク、form-action が default-src fallback 対象外

### self-review pattern も引き続き機能

各 PR で実装 self-review (Claude subagent + Gemini 並行) を実施:
- **PR H** で **app.config だけでは Jinja 参照不可** という致命バグ (cache busting 機能死) を発見、`@app.context_processor` 追加で fix
- **PR H** で aria-labelledby が ARIA 仕様違反 (tablist の id を指していた) を発見し fix

### a11y との整合は「PR で同時にやる」のが正解

PR G 段階で a11y 関連属性を全部取り込まなくても、PR H で template 書換時に `role="tablist"/tab/tabpanel` + `aria-selected` + `aria-live` をまとめて入れる方が一貫性のある設計になった。Plan G のスコープ責任分担 (「実装は基盤だけ、a11y は template と一緒」) が機能した。

### CDN block test は「動作テスト」ではなく「実装証明テスト」

`test_dashboard_loads_with_cdn_blocked` の `assert blocked[0] == 0` は「CDN block しても動く」ではなく **「block する余地が無い (CDN への request がそもそも発生していない)」** を assert する。これにより「CDN 削除完了」を E2E レベルで実証する。docstring に明記。

### ADR と Plan doc の役割分担

| | ADR | Plan |
|---|---|---|
| 役割 | 設計の正本 | プロセス記録 + Rev 履歴 + 実装詳細 |
| 読者 | 将来の maintainer (なぜこの設計か) | 同 PR の実装者 (何を作るか / レビュー対応履歴) |
| 寿命 | 永続 | PR merge 後はアーカイブ |
| 内容 | 抜粋 + 設計判断の justify | 完全な pseudo-code / 全レビュー指摘の取込履歴 |

PR F で ADR 0004 内に「pseudo-code は Plan F を正本」と明示し、ADR には 30 行抜粋のみ載せる方式が機能した。

### 規模見積の校正

| 項目 | 当初見積 (BACKLOG ROADMAP) | 実装後 |
|---|---|---|
| CSS | 300 行 | 284 行 ✓ |
| JS | 50 行 | **268 行** (5.4×) |
| Template 書換 | 500 行 | 500 行前後 ✓ |

JS が 5× に膨らんだ理由:
- exponential backoff の state management
- MutationObserver の addedNodes / removedNodes 両方走査
- defensive guards (isNaN / pollUrl 欠落 / form.matches 防御)
- triggerFrom listener 重複 attach 防止
- bulk-toggle-all delegation
- IIFE wrap + 'use strict' + コメント (仕様正本リンク)

「最小 50 行」という当初見積は HTMX 互換性を妥協した場合の概算で、Plan review / self-review でレビュアーから「ロジックを 100 行に詰めると可読性低下 + バグの温床」と指摘され適切な ~270 行に着地。

---

## 参照

- ADR 0004: `docs/dev/adr/0004-dashboard-external-deps-removal.md`
- 包括レビュー: `docs/dev/reviews/2026-04-18-comprehensive-review.md`
- Plan F: `docs/plans/sprint-007-pr-f.md` (pseudo-code 正本)
- Plan G: `docs/plans/sprint-007-pr-g.md`
- Plan H: `docs/plans/sprint-007-pr-h.md`
- Plan I: `docs/plans/sprint-007-pr-i.md`
- security-notes (dashboard 外部依存ゼロ化セクション): `docs/dev/security-notes.md`
