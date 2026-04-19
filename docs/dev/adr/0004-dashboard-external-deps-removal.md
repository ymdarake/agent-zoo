# ADR 0004: Dashboard 外部依存ゼロ化（pico/htmx → 自前 HTML/CSS/JS）

| 項目 | 値 |
|---|---|
| 日付 | 2026-04-19 |
| 改訂 | Rev.4（Plan review + self-review + Gemini 再レビュー反映後） |
| ステータス | Accepted（実装は Sprint 007 PR G〜I） |
| 起点 | [2026-04-18 包括レビュー](../reviews/2026-04-18-comprehensive-review.md) M-1 / L-6、[BACKLOG ROADMAP](../../../BACKLOG.md) L51 |
| 実装 Sprint | Sprint 007（PR F = 本 ADR / PR G = 基盤 / PR H = template 書換 / PR I = CDN 削除 + CSP 厳格化） |

---

## Context

Dashboard は Flask + Jinja2 で実装され、UI 層に **pico.css** と **htmx.org** を使用している。両者を **CDN（jsdelivr / unpkg）から SRI 無しで動的 link** している現状は、以下のリスクを伴う。

### 包括レビュー指摘

- **M-1 (Medium)**: CDN 乗っ取り / タンパリングで悪意 JS / CSS が dashboard ブラウザコンテキストで実行可能。CSP の `style-src` / `script-src` に CDN ホストが許可されている = exfiltration 経路としても利用される
- **L-6 (Low)**: CDN 経由 CSS は同様にタンパリング対象、装飾だけでも UI なりすましで操作誘導が可能

### 現状の依存（具体）

```html
<!-- bundle/dashboard/templates/index.html -->
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@picocss/pico@2/css/pico.min.css">
<script src="https://unpkg.com/htmx.org@2.0.4"></script>
```

```python
# bundle/dashboard/app.py:122-131 (現行 CSP)
"style-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; "
"script-src 'self' https://unpkg.com 'unsafe-inline'; "
```

### 規模実態

dashboard は **5 partial** + **1 index** + **app.py 700 行**。HTMX 属性使用は 19 箇所、pico 変数 6 種類、inline `style="..."` 70 箇所超、inline `<script>` 4 ブロック。**self-host より自前実装の方が長期的に simple** との判断（BACKLOG ROADMAP L51）。

---

## Decision

dashboard を **自前 HTML/CSS/vanilla JS に完全移行** し、外部 CDN への依存を 0 にする。

### 設計原則

1. **declarative data-* 属性**: 全 HTMX 機能を `data-poll-url` / `data-poll-interval` / `data-swap-target` / `data-trigger-from` / `data-include` / `data-confirm` / `data-json-body` / `data-tab` / `data-bulk-action` / `data-bulk-select` / `data-bulk-target` / `data-suggest-target` で表現。**swap 先 selector は `data-swap-target`** で確定（`data-target` は既存 url-suggest が id 文字列で使用済のため命名衝突回避）
2. **event delegation 中心**: `document.body.addEventListener('submit'/'click'/'change', ...)` で partial swap 後も再 attach 不要
3. **MutationObserver で `data-poll-url` 再 attach + cleanup**: setInterval は要素紐付き。`addedNodes` で `setupPolls(n)` 再呼出、`removedNodes` で `clearInterval` してメモリ leak 防止。`_pollTimers` WeakMap で二重 attach 防止
4. **inline `<script>` / `style="..."` / `onclick=` を完全排除**: PR I の CSP `'self'` only 達成のため必須。CSP 3 の `style-src-attr` / `script-src-attr` も `'self'` のみ。**`<meta name="csrf-token">` だけは index.html `<head>` に維持**（pseudo-code の `csrf()` が依存）
5. **HX-Request: true ヘッダ送出**: 既存 app.py の UI/API 判別ロジックを維持（互換性優先）
6. **innerHTML swap 固定**: outerHTML / beforeend 等は使わない（将来必要なら別 swap mode を追加）
7. **pico 値の事実情報のみ参照**: 色 hex / size px / breakpoint px は事実情報として参考にするが、selector 構造 / cascade ロジック / class 名は独自実装（MIT LICENSE の派生著作物境界を明確に分離。pico の `.container` / `.secondary` を直接コピーせず `.layout-container` / `.btn-secondary` 等の独自命名）

### HTMX 属性棚卸し → vanilla JS マッピング

> **網羅性根拠**: `git grep -n "hx-" bundle/dashboard/templates/` 実測 = **23 出現 / 9 種類**。詳細 line 番号と PR H 移行手順は [Plan doc Rev.3](../../plans/sprint-007-pr-f.md#htmx-属性棚卸し要点詳細は-adr-0004-に転記) を正本とする。

| 属性 | 使用箇所 | 役割 | vanilla JS 置換 |
|---|---|---|---|
| `hx-headers='{X-CSRFToken}'` | `index.html:32` body | 全 HTMX request に CSRF token | `fetch` ヘッダで送出。`<meta name="csrf-token">` から取得 |
| `hx-get` + `hx-trigger="load, every 5s"` + `hx-swap="innerHTML"` | `index.html:40, 78, 85, 92`（4 polling div） | 周期 polling、自身 innerHTML 置換 | `data-poll-url="/path"` + `data-poll-interval="5000"`。初回即時 + setInterval。`document.hidden` 中 skip。**`data-swap-target` 未指定 → 自身に swap** |
| `hx-get` + `hx-trigger="change from:#status-filter, load, every 5s"` + `hx-include="#status-filter"` | `index.html:60-61` requests filter | 外部 element change で fetch + 周期 polling + 外部 input 値 querystring | `data-poll-url` + `data-poll-interval` + `data-trigger-from="#status-filter:change"` + `data-include="#status-filter"` + `data-swap-target="#requests-container"` |
| `hx-post` (with `hx-confirm`) | inbox.html:29, 34 / whitelist.html:14, 51, 102 | confirm 必要な submit | `data-swap-target` + `data-confirm` 付与 |
| `hx-post` (without `hx-confirm`) | whitelist.html:107 (dismiss) / whitelist.html:179 (restore) | confirm **不要** な submit | `data-swap-target` のみ、**`data-confirm` 付けない** |
| `hx-target="#id"`（独立扱い、9 出現） | get/post 共通 | swap 先 selector | **`data-swap-target="#id"`**（既存 whitelist.html:121 の `data-target="path-..."` (id 文字列) との命名衝突を回避するため `data-swap-target` に rename）。url-suggest 側は `data-suggest-target` に rename |
| `hx-swap="innerHTML"`（独立扱い、9 出現） | 全箇所固定 | swap mode | **innerHTML 固定**（outerHTML/beforeend 等は使わない） |
| `hx-confirm="..."` (5 出現) | 一部 form のみ | submit 前 confirm dialog | `data-confirm="..."` + JS の preventDefault。**confirm 不要 form (Restore / dismiss) には付けない** |
| `hx-ext="json-enc"` + `hx-vals='{...|tojson|forceescape}'` | inbox.html:30, 31, 35, 36 | record_id を JSON body 送出 | `data-json-body='{"record_id": "..."}'` + `Content-Type: application/json` |
| `onclick="showTab(...)"` (inline) | `index.html:51-54` tab nav | tab 切替 | `data-tab="inbox"` + body click delegation。CSP `'unsafe-inline'` 不要 |

### 既存 inline JS の取扱（**完全削除 → static/app.js に移植**）

> ⚠ **Critical**: `innerHTML = ...` swap した HTML 内の `<script>` は **W3C HTML5 仕様で実行されない**。HTMX は独自 MutationObserver で再評価しているが、自前 fetch+innerHTML では実行されない。さらに PR I の CSP `'self'` only で inline `<script>` は CSP 違反。**全 partial / index.html から `<script>` ブロック / `onclick=` 属性を完全に剥がし `static/app.js` に集約する**。

| 既存 inline | 役割 | 移植先 |
|---|---|---|
| `index.html:99-104` `showTab` | tab 切替 (`onclick`) | `static/app.js` の click delegation (`[data-tab]`) |
| `index.html:11-30` `<style>...</style>` | inline CSS（status badge / tab nav 等） | `static/app.css` |
| `partials/inbox.html:56-77` `toggleAllInbox` / `bulkInbox` | bulk fetch | `static/app.js` の `[data-bulk-action]` delegation |
| `partials/whitelist.html:140-156` URL→path-pattern サジェスト IIFE | `<li data-url=...>` クリックで input セット | `static/app.js` の `[data-url-suggest]` delegation |
| 全 template の `style="..."` 属性（grep で 70 箇所超） | inline 装飾 | **全 class 化** + `static/app.css` |

### CSS design tokens（pico → 自前変数）

| pico 変数 | 自前変数 | 値 |
|---|---|---|
| `--pico-font-size` | `--font-size-base` | `14px` |
| `--pico-muted-color` | `--color-muted` | `#6b7280` |
| `--pico-primary` | `--color-primary` | `#1a73e8` |
| `--pico-color` | `--color-text` | `#1f2937` |
| `--pico-del-color` | `--color-danger` | `#d11a2a` |
| `--pico-ins-color` | `--color-success` | `#188038` |

### ハードコード色（status badge）も tokens 化

| 既存 | 自前変数 | 値 |
|---|---|---|
| `#d4edda`/`#155724` | `--badge-allowed-bg`/`fg` | 同左 |
| `#f8d7da`/`#721c24` | `--badge-blocked-bg`/`fg` | 同左 |
| `#fff3cd`/`#856404` | `--badge-rate-limited-bg`/`fg` | 同左 |

### `.layout-container`（pico `.container` 互換）

```css
.layout-container { width:100%; margin-inline:auto; padding-inline:1rem; max-width:1280px; }
@media (min-width: 768px)  { .layout-container { max-width: 720px; } }
@media (min-width: 1024px) { .layout-container { max-width: 960px; } }
@media (min-width: 1280px) { .layout-container { max-width: 1200px; } }
```

### vanilla JS API（コア API、実装は PR G）

> **正本性**: 完全な pseudo-code は [Plan doc Rev.3 の「コア API」節](../../plans/sprint-007-pr-f.md#コア-apipseudo-code実装は-pr-g) を **正本** とする。本 ADR には PR G 実装者が読むべき要旨のみ抜粋。

```js
// === Helpers ===
// CSRF token は **毎 fetch ごと** meta tag から読む (rotation 対応、抽出保持禁止)
const csrf = () => document.querySelector('meta[name="csrf-token"]')?.content || '';

// === GET polling (with exponential backoff on error) ===
// state: { intervalId, failures, baseInterval } で連続失敗時の負荷増を回避
const _pollTimers = new WeakMap();
async function pollOnce(el) {
  try {
    const res = await fetch(el.dataset.pollUrl + buildIncludeQuery(el.dataset.include),
                            { headers: { 'HX-Request': 'true' } });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const html = await res.text();
    if (el.dataset.swapTarget) document.querySelector(el.dataset.swapTarget).innerHTML = html;
    else el.innerHTML = html;  // target 未指定なら自身に swap
    // 成功 → failures reset、interval を base に戻す
  } catch (e) {
    // 失敗 → failures++、interval を base × 2^failures (最大 60s) に reschedule
  }
}

// === Form submit ===
document.body.addEventListener('submit', async (ev) => {
  const f = ev.target;
  if (!f.matches('form[data-swap-target]')) return;
  ev.preventDefault();
  if (f.dataset.confirm && !confirm(f.dataset.confirm)) return;
  // fetch + swap into f.dataset.swapTarget
});

// === click delegation: data-tab / data-bulk-action / data-suggest-target ===
// === MutationObserver: addedNodes / removedNodes 両方で自身+子孫を走査 ===
//   addedNodes → setupPolls 再呼出
//   removedNodes → clearInterval + _pollTimers.delete (Gemini 指摘で明示)
```

実装規模見積: **JS ~80〜100 行**（当初 50 行から拡張、change-from / data-include / poll 再 attach + cleanup / tab / bulk / suggest を集約）。

### Static cache 戦略

Werkzeug デフォルト `SEND_FILE_MAX_AGE_DEFAULT = 12h` のまま並存期間に入ると古い app.js が残り CDN htmx と二重実行リスク。
**採用**: `<script src="/static/app.js?v={{ asset_version }}">` で query cache busting。`asset_version` は Flask `app.config["ASSET_VERSION"]` に git short sha or pyproject version を入れて Jinja で展開。PR G で実装。

### 移行戦略（並存 + 各 PR 独立 revert）

| PR | 内容 | revert 影響 |
|---|---|---|
| **G** | `static/app.css` + `static/app.js` 追加。index.html は **link しない**。`app.config["ASSET_VERSION"]` default `""` 注入（Jinja UndefinedError 回避）。Flask static serving 確認のみ | revert で追加ファイルが消えるだけ。挙動影響無し |
| **H** | index.html / partials を新仕様に書換（CDN と自前を **両方 link**、自前 CSS 後勝ち）。inline `<script>`/`style=`/`onclick=` 完全削除（`<meta name="csrf-token">` だけ維持）。**commit 単位で完全置換、`hx-*` と `data-*` を両持ちしない**（二重 POST リスク回避）。E2E selector 追従 | revert で template が pico/htmx-only に戻る。app.css/.js は残るが未使用 |
| **I** | CDN link 削除、CSP `'self'` のみに厳格化、E2E オフライン確認 | revert で CDN link が復活、CSP は CDN 許容に戻る |

各 PR は自己完結、本番に出ても問題が起きない単位で merge 可能。

---

## Alternatives Considered

### A. pico / htmx をローカル self-host（CDN 削除のみ、ライブラリ使用継続）

- 利点: 移行コスト最小（CSS/JS を `static/` に置くだけ）、UI 挙動完全互換
- 欠点:
  - 依存ライブラリのバージョン追従コストが残る（Dependabot で監視必要、追加 ecosystem）
  - htmx 拡張 (`json-enc` 等) を含む total ~20KB が継続。dashboard はそのほぼ 1% しか使わない
  - audit 対象が「pico の全機能 + htmx の全機能」のままで縮小しない
  - **長期的 simple ではない**: BACKLOG ROADMAP L51 の「自前 50〜300 行 vs ライブラリ全部」のトレードオフで自前優位
- **採用しなかった理由**: 中期的に「dashboard 拡張時に pico/htmx の知識が前提」という暗黙コストが残る。自前なら 100 行を読めば全貌

### B. Tailwind CSS / utility-first framework に移行

- 利点: モダン、書き味良い
- 欠点: build step（postcss / cli）が必要、Python-only repo に node toolchain 入れる、依存大幅増
- **採用しなかった理由**: 規模ミスマッチ（dashboard 数画面に過剰）

### C. Alpine.js 等の軽量 framework に移行

- 利点: HTMX 互換に近い declarative API、~15KB
- 欠点: 新たな external dep を増やす（M-1 振り出しに戻る）、Alpine 自体の lifecycle 学習コスト
- **採用しなかった理由**: 「外部依存ゼロ」の goal に反する

### D. SPA（React / Vue / Svelte）に書直し

- 言語道断（規模ミスマッチ + ビルド + Node toolchain + SSR/CSR 議論）

---

## Consequences

### Positive

- **CDN 依存ゼロ**: M-1 / L-6 完全 resolved、サプライチェーン攻撃面消滅
- **CSP 厳格化が可能に**: `default-src 'self'` のみ（`'unsafe-inline'` 不要）、XSS の影響半径が劇的縮小
- **オフライン動作**: airgap 環境でも dashboard が機能（agent-zoo は localhost で完結する設計のため整合）
- **audit 対象縮小**: 評価対象が pico + htmx の数 KLOC + 自前 100 行 → 自前 ~500 行のみ
- **依存追跡コスト 0**: Dependabot の docker / pip ecosystem 1 件減（CDN は外形 audit 不可だったので元々不在）

### Negative

- **PR H の規模が大きい**: ~500 行の template 書換。レビューコスト高、ミスリスク。各 partial 単位で commit 分割必須
- **E2E test selector 同 PR で書換必須**: `form[hx-post*=]` → `form[data-target][action*=]`。同 PR で連動修正
- **pico の小機能（dropdown, tooltip 等）が未使用なら影響なし、もし使い始めたら自前実装コスト**: 現状 dashboard は使っていないため OK、新機能追加時に判断
- **dark theme 未対応**: pico はデフォルトで media query で dark を切り替える。本 ADR scope 外 → PR I 後に follow-up

### Neutral

- HTMX の高度機能（hx-boost, OOB swap 等）は dashboard で未使用、影響なし
- 既存 `_get_json_body()` の form/JSON 両対応はそのまま流用、API 互換が自動的に保たれる

### Known Limitations（follow-up）

#### swap mode が innerHTML 固定

将来 `outerHTML` / `beforeend` 等が必要になった場合は、`data-swap="outerHTML"` 等の attribute を追加して `app.js` を拡張。現 dashboard では innerHTML で十分。

#### dark theme

PR I 完了後の follow-up として、`prefers-color-scheme: dark` media query で `--color-*` を切り替える設計を別 PR で追加する。

#### MutationObserver パフォーマンス

`document.body` 全体を `subtree: true` で監視するため、大量 DOM 更新時に overhead が出る可能性。dashboard の partial swap 頻度（5s 周期 × 4 partial）では実害無いが、計測して問題があれば observe 範囲を `[data-poll-root]` 等の特定 container に限定する。

#### CSP `style-src-attr` の扱い

PR I で `default-src 'self'` のみ + `style-src-attr 'self'` を狙うと、Browser によっては default-src を fallback しない（特に古い iOS Safari）。実機検証で問題が出た場合のみ `style-src-attr 'self'` を明示追加する（許容できる範囲、`'unsafe-inline'` は使わない）。

#### DOM API による style 設定は CSP 対象外

`element.style.display = 'none'` のような **DOM API 経由の style 設定** は CSP `style-src-attr` の制約対象外（CSP3 仕様: HTML attribute の inline style のみ評価）。show/hide や URL suggest クリック時の色変化を JS 経由でやる限り CSP 違反にならない。
ただし将来 maintainer が「style.cssText で複数プロパティを一気に設定」のようなコードを書く場合、保守性のため class toggle に統一する方針を本 ADR で推奨。

#### `onclick` を data-tab 化したことによる accessibility

`<a href="#" onclick=...>` を `<a href="#" data-tab=...>` に変更。`href="#"` は keyboard focusable で、`<a>` のロールも保たれる。click delegation で preventDefault しているので URL に `#` が積まれる問題も回避。

#### LICENSE / pico 派生著作物境界

pico は MIT。**事実値（色 hex / size px / breakpoint px）は事実情報として参考にする**が、selector 構造 / cascade ロジック / class 名は独自設計（pico の `.container` / `.secondary` 等を直接コピーしない、`.layout-container` / `.btn-secondary` 等の独自命名）。これにより MIT の derivative-work 境界を明確に超えない。

---

## Test Strategy

### PR G（基盤追加）

- `tests/test_dashboard_static.py`（新規 2〜3 件）:
  - `/static/app.css` が 200 で配信される
  - `/static/app.js` が 200 で配信される
  - `<script src=".../static/app.js?v=...">` の query が Jinja 展開される

### PR H（template 書換）

- 既存 `tests/test_dashboard.py` 全 PASS（API レベル、template 不依存）
- 既存 `tests/test_dashboard_csrf.py` 全 PASS（**`<meta name="csrf-token">` が `<head>` に維持されていること**を assert する追加 1 件）
- 既存 `tests/test_dashboard_security_headers.py` 全 PASS（CSP は PR I まで未変更）
- `tests/e2e/test_dashboard.py` の `form[hx-post*=]` selector を `form[data-swap-target][action*=]` に書換、全 PASS
- `tests/test_dashboard_inline_assets.py`（新規 6〜10 件、**BeautifulSoup ベース**で raw template grep の false positive 回避）:
  - Flask test client で `/`, `/partials/stats`, `/partials/inbox`, `/partials/whitelist`, `/partials/requests`, `/partials/tool-uses` を render、BS4 で parse
  - 各 endpoint で:
    - `<script>` 子要素を持たない（外部 src の `<script src=...>` のみ許可）
    - `<style>` element が存在しない
    - 全要素に `style="..."` 属性が無い
    - 全要素に `onclick=` / `onsubmit=` 等の inline event handler が無い
  - `/` (index.html) で `<meta name="csrf-token">` が `<head>` に存在
  - 想定 `data-swap-target` / `data-poll-url` / `data-confirm` 属性が想定箇所に存在

### PR I（CSP 厳格化 + CDN 削除）

- `tests/test_dashboard_csp.py`（新規 2〜3 件、CSP value を `;` split → directive ごと parse）:
  - CSP ヘッダが `'unsafe-inline'` を含まない（全 directive で）
  - CSP ヘッダに `cdn.jsdelivr.net` / `unpkg.com` を含まない
  - `default-src` が `'self'` のみ
- `tests/e2e/test_dashboard.py` のオフライン動作確認（Playwright の `route` で `cdn.jsdelivr.net` / `unpkg.com` を block、全テスト PASS）

---

## References

- 包括レビュー [M-1 / L-6](../reviews/2026-04-18-comprehensive-review.md)
- BACKLOG ROADMAP L51: 「dashboard を外部依存ゼロの自前 HTML/CSS/vanilla JS に書き直す」
- 統合作業計画 [Sprint 007 節](../../plans/2026-04-18-consolidated-work-breakdown.md#sprint-007-dashboard-外部依存ゼロ化1〜2-週間4-pr--adr)
- Plan doc [docs/plans/sprint-007-pr-f.md](../../plans/sprint-007-pr-f.md) — 設計詳細・pseudo-code・review 反映履歴の正本
- ADR 0005 (fail-closed addons): フォーマットテンプレート参照
- W3C HTML5 spec: [Scripting `script` element](https://html.spec.whatwg.org/multipage/scripting.html#the-script-element) — innerHTML 後 script 非実行の根拠
- CSP3 spec: [Content Security Policy Level 3](https://www.w3.org/TR/CSP3/) — `style-src-attr` / `script-src-attr` の定義
