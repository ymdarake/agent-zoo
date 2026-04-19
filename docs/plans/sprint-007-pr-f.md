# Sprint 007 PR F: ADR 0004 + 設計

| 項目 | 値 |
|---|---|
| 作成日 | 2026-04-19 |
| 改訂 | Rev.4（Gemini 再レビュー反映: CSRF token 動的更新明記 + polling backoff + partial endpoint test） |
| Sprint | 007（Dashboard 外部依存ゼロ化） |
| PR | F (本 PR) → G → H → I |
| 関連 issue | 包括レビュー M-1（pico/htmx を CDN から SRI 無しで読込）、L-6（CDN 経由 CSS） |
| 範囲 | **設計のみ**（実装は PR G〜I） |

---

## ゴール

Sprint 007 全体（4 PR）の **設計の正本** として ADR 0004 を起票し、PR G〜I の作業内容を確定させる。
PR G 以降がこの ADR を参照しながら実装するため、本 PR は **コード変更ほぼ無し**（ADR 1 ファイル + Plan doc + sprint 進捗 link のみ）。

### deliverables

1. `docs/dev/adr/0004-dashboard-external-deps-removal.md` 新設
2. ADR 内の「HTMX 属性棚卸し表」（現状 → 新仕様の対応マッピング）
3. ADR 内の「CSS design tokens」（pico の使用変数 → 自前変数への置換表）
4. ADR 内の「vanilla JS API 設計」（fetch + swap の最小 API）
5. ADR 内の「移行戦略」（PR G〜I の各 PR scope を明示）
6. `docs/plans/sprint-007-pr-f.md`（本ファイル）
7. `BACKLOG.md` の Sprint 007 行に PR F 着手中マーク追加（完了後に Sprint G 着手）

### non-goals（本 PR ではやらない）

- 実装（CSS / JS / template 書換）
- CSP の更新（CDN 残存中なので、PR I で行う）
- 既存テストの修正

---

## Context

### 現状の外部依存

- `bundle/dashboard/templates/index.html:9` `<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@picocss/pico@2/css/pico.min.css">`
- `bundle/dashboard/templates/index.html:10` `<script src="https://unpkg.com/htmx.org@2.0.4">`

### 包括レビュー指摘（M-1 / L-6）

- **M-1**: pico/htmx を unpkg / jsdelivr から **SRI 無しで** 読込 → CDN 乗っ取り / タンパリングリスク
- **L-6**: CDN ホストが CSP `style-src` / `script-src` に残存 → exfiltration 経路として悪用余地

> ROADMAP（BACKLOG.md L51）の選定: **「dashboard は数画面規模なので自前 CSS（数百行）+ vanilla JS（fetch + form.addEventListener で HTMX 置換、~50 行）に完全移行する方が、外部ライブラリを self-host するより long-term simple」**

### 規模見積（既存通り）

- テンプレート書換: ~500 行
- CSS: ~300 行
- JS: ~50 行

---

## Sprint 007 全 PR の構成

| PR | 担当範囲 | 規模 | 関連 task |
|---|---|---|---|
| **PR F (本 PR)** | ADR 0004 + 設計 | ADR 1 ファイル | task #13 |
| PR G | 自前 CSS + vanilla JS 基盤 (新規ファイル追加、template はまだ触らない) | CSS ~300 行、JS ~50 行 | task #14 |
| PR H | template 書換え（hx-* → data-* + JS、pico class → 自前 class） | ~500 行 | task #15 |
| PR I | CDN link 削除 + CSP 厳格化 + E2E オフライン確認 | template + app.py + ci.yml | task #16 |

PR G 段階では index.html はまだ pico/htmx を読んでいる（並存）。PR H で template 書換と同時に CDN を見たまま動作する状態を維持し、PR I で初めて CDN link を削除する。これにより各 PR が独立して revertable。

---

## HTMX 属性棚卸し（要点、詳細は ADR 0004 に転記）

`bundle/dashboard/templates/` 配下の使用属性を全列挙し、vanilla JS 移行先を確定する。

### 属性一覧と使用箇所

> **網羅性根拠**: `git grep -n "hx-" bundle/dashboard/templates/` 実測 = **23 出現 / 9 種類**（`hx-target` 9 / `hx-post` 8 / `hx-swap` 9 / `hx-get` 5 / `hx-trigger` 5 / `hx-include` 1 / `hx-confirm` 5 / `hx-ext` 2 / `hx-vals` 2 + body 1 件の `hx-headers`）。`hx-target` を独立カウントして 9 種類に確定（前 Rev.2 の「19 出現 / 10 種類」は誤記）。

| 属性 | 使用箇所 (file:line) | 役割 | vanilla JS 置換方針 |
|---|---|---|---|
| `hx-headers='{...}'` | `index.html:32` body | 全 HTMX request に X-CSRFToken header 付与 | JS の `fetch` ヘッダで送出。CSRF token は `<meta name="csrf-token">` から取得 |
| `hx-get="/path"` + `hx-trigger="load, every 5s"` + `hx-swap="innerHTML"` | `index.html:40, 78, 85, 92` (stats / tool-uses / inbox / whitelist の 4 polling div) | 周期 polling、自身の innerHTML を置換 | `data-poll-url="/path"` + `data-poll-interval="5000"`。初回即時 + setInterval。`document.hidden` 中 skip。**`data-swap-target` 未指定時は polling element 自身に swap** |
| `hx-get` + `hx-trigger="change from:#status-filter, load, every 5s"` + `hx-include="#status-filter"` | `index.html:60-61` requests filter form | 外部 element change で fetch + 周期 polling + 外部 input 値 querystring | `data-poll-url` + `data-poll-interval` + `data-trigger-from="#status-filter:change"` + `data-include="#status-filter"` + `data-swap-target="#requests-container"` |
| `hx-post` (with `hx-confirm`) | `inbox.html:29, 34`、`whitelist.html:14, 51, 102` | confirm 必要な submit | form `submit` delegation で fetch + swap。`data-confirm="..."` 付与 |
| `hx-post` (without `hx-confirm`) | `whitelist.html:107` (dismiss)、`whitelist.html:179` (restore) | confirm **不要** な submit | form `submit` delegation で fetch + swap。**`data-confirm` 付けない**（既存 UX 維持） |
| **`hx-target="#id"`（独立扱い、9 出現）** | get/post 共通 | swap 先 selector | **`data-swap-target="#id"`**（既存 whitelist.html:121 の `data-target="path-..."` (id 文字列) との命名衝突回避のため `data-swap-target` に rename）。post form 必須、polling 側未指定なら自身 |
| **`hx-swap="innerHTML"`（独立扱い、9 出現）** | 全箇所固定 | swap mode | **innerHTML 固定**（outerHTML/beforeend 等は使わない、将来仕様追加で対応） |
| `hx-confirm="..."` (5 出現) | inbox.html / whitelist.html の **一部 form のみ** | submit 前 confirm dialog | `data-confirm="..."` + JS の `if (!confirm(form.dataset.confirm)) preventDefault()`。**confirm 不要 form (Restore / dismiss) には付けない** |
| `hx-ext="json-enc"` + `hx-vals='{...|tojson|forceescape}'` | inbox.html:30, 31, 35, 36 (accept / reject の record_id) | record_id を JSON body 送出 | `data-json-body='{"record_id": "..."}'` + `Content-Type: application/json` |
| `onclick="showTab(...)"` (inline JS) | `index.html:51-54` tab nav | tab 切替 | **CSP `'unsafe-inline'` 要求のため除去**。`data-tab="inbox"` + body click delegation |

### 既存の inline JS（**partial 内 `<script>` の完全削除が必須**）

> ⚠ **Critical**: `innerHTML = ...` で swap した HTML 内の `<script>` は **W3C HTML5 仕様で実行されない**。HTMX は独自に MutationObserver で再評価しているが、自前 fetch + innerHTML では実行されない。さらに PR I の CSP `'self'` 厳格化で inline `<script>` は CSP 違反になる。
> **したがって PR H で全 partial / index.html から `<script>` ブロック / `onclick=...` 属性を完全に剥がし、`static/app.js` に集約する必要がある。**

| 既存 inline JS の場所 | 役割 | 移植先 / 置換方針 |
|---|---|---|
| `index.html:99-104` `showTab(name, el)` | tab 切替（onclick 直呼出） | `static/app.js` 内で `data-tab="inbox"` に対する body 全体の `click` delegation |
| `index.html:11-30` `<style>...</style>` ブロック | inline CSS（status badge、tab nav 等） | `static/app.css` に全部移植 |
| `partials/inbox.html:56-77` `toggleAllInbox` / `bulkInbox` | bulk action 用 fetch | `static/app.js` で `data-bulk-action="/api/inbox/bulk-accept"` 等の declarative 属性 + delegation |
| `partials/whitelist.html:140-156` URL→path-pattern サジェスト IIFE | `<li data-url=...>` クリックで input value セット | `static/app.js` で `[data-url][data-target]` への body 全体の `click` delegation |
| 全 template の `style="..."` 属性（grep で 70 箇所超） | inline 装飾 | **全部 class 化**。PR H で `style="..."` を剥がし、`class="..."` で表現。CSS attribute も CSP `style-src-attr 'unsafe-inline'` を要求するため、これを許可しない厳格な CSP を狙うなら必須 |

---

## CSS design tokens（要点、詳細は ADR 0004 に転記）

pico の CSS 変数を grep で抽出 → 自前トークンにマッピング:

| pico 変数 | 用途 | 自前変数（提案） | 値（提案） |
|---|---|---|---|
| `--pico-font-size` | 全体 font-size | `--font-size-base` | `14px` |
| `--pico-muted-color` | 補足テキスト | `--color-muted` | `#6b7280` |
| `--pico-primary` | リンク・border | `--color-primary` | `#1a73e8` |
| `--pico-color` | 通常テキスト | `--color-text` | `#1f2937` |
| `--pico-del-color` | 削除/アラート | `--color-danger` | `#d11a2a` |
| `--pico-ins-color` | 追加/許可 | `--color-success` | `#188038` |

カラーパレットは pico の light theme 値を踏襲（dark theme は本 PR scope 外、PR I 後の follow-up）。

### ハードコード色（status badge）も design tokens 化

`index.html:18-20` の hardcoded 色を変数化:

| 既存ハードコード | 用途 | 自前変数（提案） | 値 |
|---|---|---|---|
| `#d4edda` / `#155724` | `.status-ALLOWED` 背景 / 文字 | `--badge-allowed-bg` / `--badge-allowed-fg` | `#d4edda` / `#155724` |
| `#f8d7da` / `#721c24` | `.status-BLOCKED` / `.status-PAYLOAD_BLOCKED` / `.status-URL_SECRET_BLOCKED` / `.status-BODY_TOO_LARGE` | `--badge-blocked-bg` / `--badge-blocked-fg` | `#f8d7da` / `#721c24` |
| `#fff3cd` / `#856404` | `.status-RATE_LIMITED` | `--badge-rate-limited-bg` / `--badge-rate-limited-fg` | `#fff3cd` / `#856404` |

`partials/stats.html:8,15` の `<h2 class="status-BLOCKED">` も同 class を流用しているため、`.status-*` class 群が "badge 装飾 + 数値強調" の二役になる点は維持（互換性のため）。

### `.layout-container` の責務（pico の `.container` 互換）

pico の `.container` は **max-width によるレスポンシブ wrapper**（mobile = 100% / tablet = 768px / desktop = 1024px / wide = 1280px）。これに準拠する自前定義:

```css
.layout-container {
  width: 100%;
  margin-inline: auto;
  padding-inline: 1rem;
  max-width: 1280px;  /* lg 以上で固定 */
}
@media (min-width: 768px)  { .layout-container { max-width: 720px; } }
@media (min-width: 1024px) { .layout-container { max-width: 960px; } }
@media (min-width: 1280px) { .layout-container { max-width: 1200px; } }
```

PR G で実装。

### 自前 class 体系（提案）

pico の `<article>`, `class="container|grid|secondary|contrast|outline"` 等を以下に置換:

| pico | 自前 |
|---|---|
| `<article>` | `<section class="card">` |
| `class="container"` | `class="layout-container"` |
| `class="secondary"` | `class="btn-secondary"` |
| `class="contrast"` | `class="btn-contrast"` |
| `class="outline"` | `class="btn-outline"` |
| `aria-busy="true"` | `<span class="spinner" role="status">` + CSS animation |

---

## vanilla JS API 設計（要点、詳細は ADR 0004 に転記）

### モジュール構成

`bundle/dashboard/static/app.js`（~80〜100 行）一本。ESM / モジュールバンドラ無し（Flask が静的配信、ブラウザは ES2017+ サポート前提）。
当初見積 ~50 行から拡張: change-from delegation / data-include / poll 再 attach / data-tab / data-bulk-action / URL→path-pattern サジェストを集約するため。

### data-* 属性スキーマ（declarative API）

> **命名衝突の回避（self-review R3）**: 既存 `whitelist.html:121` が `data-target="path-{{ host|replace('.', '-') }}"` を **id 文字列**として使用済（`<li data-url=... data-target="path-..." onclick=...>` で URL→path-pattern サジェスト）。新仕様で `data-target` を **swap 先 selector** に転用すると衝突する。よって新仕様は **`data-swap-target="#sel"`** に rename。既存の url-suggest 側も PR H で `data-suggest-target` に rename して semantics を分離。

| 属性 | 配置 | 役割 |
|---|---|---|
| `data-poll-url="/path"` | div / form / 任意 element | 周期 fetch の URL。GET 固定。**path に `:` を含むケース対応のため interval と分離**（self-review R5） |
| `data-poll-interval="5000"` | 同上 | 周期 fetch の interval (ms)。省略時は 5000 |
| `data-swap-target="#id"` | poll / form element | swap 先 selector。**未指定なら poll element 自身に innerHTML swap**（仕様統一、self-review R4/R15） |
| `data-trigger-from="#sel:event"` | poll element | 外部 element の event でも即時 fetch（`hx-trigger="change from:..."` 互換） |
| `data-include="#sel"` | poll element / form | fetch 時に外部 input の name/value を querystring/FormData にマージ |
| `data-confirm="文言"` | form | submit 前 confirm dialog |
| `data-json-body='{...}'` | form | JSON body で POST。`Content-Type: application/json` 自動 |
| `data-tab="name"` | tab nav `<a>` | 同 name の `#tab-name` を表示、他を hide |
| `data-bulk-action="/path"` | button | 同 form 内 `[data-bulk-select]:checked` の値を集めて JSON POST |
| `data-bulk-select="value"` | checkbox | `data-bulk-action` の集計対象 |
| `data-bulk-confirm="文言"` | button | bulk 用 confirm dialog |
| `data-bulk-target="#id"` | button | bulk action 後の swap 先 |
| `data-suggest-target="#input-id"` | `<li data-url=...>` 等 | クリックで input value を path-pattern 形式に書込（既存 url-suggest 機能、命名衝突回避で rename） |

### コア API（pseudo-code、実装は PR G）

```js
// === Helpers ===
// CSRF token は **毎 fetch ごと** に meta tag から読む（rotation 対応）。
// Gemini レビュー High: 抽出して保持するパターンは server 側 token 更新を取りこぼす。
const csrf = () => document.querySelector('meta[name="csrf-token"]')?.content || '';

function buildIncludeQuery(includeSel) {
  if (!includeSel) return '';
  const params = new URLSearchParams();
  document.querySelectorAll(includeSel).forEach(el => {
    if (el.name) params.append(el.name, el.value);
  });
  const qs = params.toString();
  return qs ? '?' + qs : '';
}

async function swapInto(targetSel, html) {
  const el = targetSel ? document.querySelector(targetSel) : null;
  if (el) el.innerHTML = html;
}

// === GET polling (data-poll-url + data-poll-interval) ===
// _pollTimers: element → { intervalId, failures, baseInterval }
// failures カウントで exponential backoff（Gemini レビュー Medium）
const _pollTimers = new WeakMap();
const _MAX_BACKOFF_MS = 60 * 1000;

async function pollOnce(el) {
  const url = el.dataset.pollUrl + buildIncludeQuery(el.dataset.include);
  try {
    const res = await fetch(url, { headers: { 'HX-Request': 'true' } });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const html = await res.text();
    // self-review R4/R15: target 未指定なら poll element 自身に swap
    if (el.dataset.swapTarget) {
      await swapInto(el.dataset.swapTarget, html);
    } else {
      el.innerHTML = html;
    }
    // 成功時に failures をリセット → 通常 interval に復帰
    const state = _pollTimers.get(el);
    if (state && state.failures > 0) {
      state.failures = 0;
      _rescheduleInterval(el, state.baseInterval);
    }
  } catch (e) {
    console.warn('poll failed', url, e);
    const state = _pollTimers.get(el);
    if (state) {
      state.failures += 1;
      // 指数バックオフ: base × 2^failures、最大 60s
      const next = Math.min(state.baseInterval * Math.pow(2, state.failures), _MAX_BACKOFF_MS);
      _rescheduleInterval(el, next);
    }
  }
}

function _rescheduleInterval(el, ms) {
  const state = _pollTimers.get(el);
  if (!state) return;
  clearInterval(state.intervalId);
  state.intervalId = setInterval(() => {
    if (document.hidden) return;
    pollOnce(el);
  }, ms);
}

function setupPolls(root = document) {
  root.querySelectorAll('[data-poll-url]').forEach(el => {
    if (_pollTimers.has(el)) return;  // 二重 attach 防止
    const baseInterval = parseInt(el.dataset.pollInterval || '5000', 10);
    _pollTimers.set(el, { intervalId: 0, failures: 0, baseInterval });
    pollOnce(el);  // 即時
    _rescheduleInterval(el, baseInterval);

    // change from external element
    if (el.dataset.triggerFrom) {
      const [sel, ev] = el.dataset.triggerFrom.split(':');
      document.body.addEventListener(ev || 'change', e => {
        if (e.target.closest(sel)) pollOnce(el);
      });
    }
  });
}

// === Form submit (data-swap-target) ===
document.body.addEventListener('submit', async (ev) => {
  const form = ev.target;
  if (!form.matches('form[data-swap-target]')) return;
  ev.preventDefault();
  if (form.dataset.confirm && !confirm(form.dataset.confirm)) return;
  const headers = { 'X-CSRFToken': csrf(), 'HX-Request': 'true' };
  let body;
  if (form.dataset.jsonBody) {
    body = form.dataset.jsonBody;
    headers['Content-Type'] = 'application/json';
  } else {
    body = new FormData(form);
  }
  const res = await fetch(form.action, { method: form.method || 'POST', headers, body });
  await swapInto(form.dataset.swapTarget, await res.text());
});

// === Tab nav (data-tab) ===
document.body.addEventListener('click', (ev) => {
  const tab = ev.target.closest('[data-tab]');
  if (tab) {
    ev.preventDefault();
    const name = tab.dataset.tab;
    document.querySelectorAll('[id^="tab-"]').forEach(t => t.style.display = 'none');
    document.getElementById('tab-' + name).style.display = '';
    document.querySelectorAll('[data-tab]').forEach(a => a.classList.remove('active'));
    tab.classList.add('active');
  }
});

// === Bulk action (data-bulk-action) ===
document.body.addEventListener('click', async (ev) => {
  const btn = ev.target.closest('[data-bulk-action]');
  if (!btn) return;
  ev.preventDefault();
  const scope = btn.closest('[data-bulk-scope]') || document;
  const ids = Array.from(scope.querySelectorAll('[data-bulk-select]:checked')).map(cb => cb.value);
  if (ids.length === 0) { alert('選択してください'); return; }
  if (btn.dataset.bulkConfirm && !confirm(btn.dataset.bulkConfirm)) return;
  const res = await fetch(btn.dataset.bulkAction, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'HX-Request': 'true', 'X-CSRFToken': csrf() },
    body: JSON.stringify({ record_ids: ids }),
  });
  await swapInto(btn.dataset.bulkTarget, await res.text());
});

// === URL suggest (data-suggest-target, partial whitelist) ===
document.body.addEventListener('click', (ev) => {
  const li = ev.target.closest('li[data-url][data-suggest-target]');
  if (!li) return;
  try {
    const u = new URL(li.dataset.url);
    const p = u.pathname;
    const v = p.lastIndexOf('/') > 0 ? p.substring(0, p.lastIndexOf('/')) + '/*' : p + '*';
    document.querySelector(li.dataset.suggestTarget).value = v;
    li.classList.add('suggest-applied');  // CSS で色変化（inline style 回避）
  } catch (_) {}
});

// === Auto re-attach on partial swap (MutationObserver) ===
// addedNodes: 自身 + 子孫の [data-poll-url] に setupPolls を再呼出
// removedNodes: 自身 + 子孫の interval を clearInterval してメモリ leak 防止
//   (Gemini レビュー Medium: removedNodes は再帰しないので明示的に subtree 走査必須)
const mo = new MutationObserver(muts => {
  muts.forEach(m => {
    m.addedNodes.forEach(n => {
      if (n.nodeType === 1) setupPolls(n);
    });
    m.removedNodes.forEach(n => {
      if (n.nodeType !== 1) return;
      // 自身 + 子孫を全部走査
      const targets = [];
      if (n.matches?.('[data-poll-url]')) targets.push(n);
      n.querySelectorAll?.('[data-poll-url]').forEach(el => targets.push(el));
      targets.forEach(el => {
        const state = _pollTimers.get(el);
        if (state) { clearInterval(state.intervalId); _pollTimers.delete(el); }
      });
    });
  });
});
mo.observe(document.body, { childList: true, subtree: true });

// === Boot ===
document.addEventListener('DOMContentLoaded', () => setupPolls());
```

### `HX-Request: true` ヘッダ送出

既存の app.py は `request.headers.get("HX-Request")` で UI 経由か API 経由を判別している（whitelist.html の各エンドポイント）。同じ判定を維持するため、自前 fetch でも `HX-Request: true` を送る。**API 互換性が崩れない設計**。

### `event delegation` を採用する理由

`form.addEventListener` を全 form に個別 attach すると、partial swap 後の新 form に listener が付かない。`document.body.addEventListener('submit'/'click'/'change', ...)` で event delegation すれば再 attach 不要。
ただし `data-poll` だけは setInterval が要素に紐付くため、**MutationObserver で `addedNodes` を監視**して `setupPolls(n)` を再呼出（`_pollTimers` WeakMap で二重 attach 防止）。

### Static cache 戦略（PR G で実装）

Werkzeug デフォルト `SEND_FILE_MAX_AGE_DEFAULT = 12h` のまま並存期間に入ると、PR H/I 移行時に古い app.js が残る → CDN htmx と二重実行リスク。対応:

- **方針 A（採用）**: `index.html` で `<script src="/static/app.js?v={{ asset_version }}">` の query 付与。`asset_version` は `app.config["ASSET_VERSION"]` に git short sha or `pyproject.toml` version を入れて Jinja で展開。
- 方針 B（不採用）: `SEND_FILE_MAX_AGE_DEFAULT=0`。CDN bypass で reload 速度低下、開発のしやすさは上がるが本番運用で重い。

PR G で `asset_version` 注入を Flask に組み込み、index.html で参照。

---

## 移行戦略 / リスク

### 並存期間（PR G 完了 〜 PR I 完了まで）

- PR G: `static/app.css` / `static/app.js` を追加するが、index.html は **読み込まない**。Flask static serving が動くことだけ確認。
- PR H: index.html で **CDN と自前を両方 link**（CDN を先に、自前を後に）。template は自前 class + data-* に書き換え。pico の class を残しても自前 CSS が後勝ちで上書き。E2E P1 で動作確認。
- PR I: CDN link を削除、CSP を `'self'` のみに、E2E オフライン確認。

### Risk register

| リスク | 軽減策 |
|---|---|
| HTMX の出すリクエストフォーマット (form-encoded vs JSON) と app.py 受信側が微妙に違う | 既存 `_get_json_body()` は form/JSON 両対応。新 JS でも form / JSON 両方を送る経路を実装し既存テストで確認 |
| HTMX `hx-trigger="load, every 5s"` の load 即時実行と、自前 `setInterval` の挙動差 | data-poll 初回も即時 fetch、その後 interval。`fetch` 失敗時は console.warn のみで続行。`document.hidden` 中は skip |
| event delegation で form 以外の要素が submit される | `form.matches('form[data-target]')` で gating |
| CSRF token のローテーション | 既存と同じく meta tag を毎回読む（form 送出ごとに最新） |
| **E2E P1 selector が `hx-*` 属性に依存** | `tests/e2e/test_dashboard.py:49,67,98` の `form[hx-post*="accept"]` を **PR H で `form[data-target][action*="/accept"]` 等に書き換え**。PR H 受入基準に明記 |
| **partial swap 後の新 `data-poll` 要素が polling されない** | MutationObserver で `addedNodes` を監視 → `setupPolls(n)` 再呼出。`_pollTimers` WeakMap で二重 attach 防止 |
| **partial 内 inline `<script>` が swap 後に実行されない（W3C HTML5 仕様）** | PR H で全 partial の `<script>` を完全削除し `static/app.js` に移植。Critical 注意事項として ADR の Decision 節に明記 |
| **inline `style="..."` 属性 70 箇所超が CSP `style-src-attr 'unsafe-inline'` を要求** | PR H で全 `style="..."` を class 化。PR I の CSP は `style-src-attr` も `'self'` のみ（attr 系を許可しない厳格 CSP）|
| **`onclick="showTab(...)"` が CSP `script-src 'unsafe-inline'` を要求** | PR H で `data-tab="..."` + click delegation に書き換え。PR I で `'unsafe-inline'` を script-src から外す |
| **ブラウザ static cache (Werkzeug 12h)** | `<script src="/static/app.js?v={{ asset_version }}">` で cache busting。PR G で実装 |
| `_get_json_body()` 互換: 自前 JS の form は `body: FormData`、json route は `body: JSON.stringify(...)` + `Content-Type: application/json` | app.py 既存実装で両対応済（変更不要）|
| **PR H 中間状態で `hx-*` と `data-*` を両持ち → 二重 POST** | PR H 受入基準に「commit 単位で完全置換、両持ち禁止」を明記。CDN htmx と自前 JS が同じ form を二重に submit してしまうリスクを排除 |
| **`<meta name="csrf-token">` が PR H で `<head>` から消える** | ADR Decision + PR H 受入基準に「meta tag は維持」を明記。pseudo-code の `csrf()` が依存するため必須 |
| **`data-target` 既存使用との命名衝突**（whitelist.html:121 url-suggest） | swap 先 attribute を `data-swap-target` に rename、既存 url-suggest 側を `data-suggest-target` に rename。ADR + Plan の data-* スキーマで明記 |
| **MutationObserver の removedNodes で interval が leak** | pseudo-code 側で `removedNodes` も処理して `clearInterval` + `_pollTimers.delete(el)`（partial 全置換 pattern で element 消えるケース） |
| **`test_dashboard_inline_assets.py` を raw template grep で書くと Jinja コメント等の false positive** | Test Strategy に「BeautifulSoup で render 後の HTML を parse」を明記。raw template grep ではなく Flask test client 経由 |
| **`asset_version` 未注入の Jinja UndefinedError** | PR G で `app.config["ASSET_VERSION"] = ""` を default 設定、`{{ asset_version|default('') }}` で defensive |
| **`<h2 class="status-BLOCKED">` 単独 selector** (stats partial の数値強調) | 自前 CSS で `.status-BLOCKED { background: var(--badge-blocked-bg); color: var(--badge-blocked-fg); padding: 2px 8px; border-radius: 4px; }` 単独 selector を採用（`.status-badge.status-BLOCKED` のような複合 class を要求しない設計）|
| **DOM API の `style.display = 'none'` は CSP 対象外** | JS で設定する style は CSP `style-src-attr` の制約対象外（CSP は **HTML attribute の inline style のみ評価**）。show/hide は JS 経由で安全。ADR Known Limitations に明記 |

### Rollback 手順

各 PR は独立 merge。問題が出たら直近 PR を `git revert`:

- PR G を revert: 自前 css/js が無くなるだけ（index.html は読んでいないので影響無し）
- PR H を revert: template が CDN-only に戻る（PR G の追加ファイルは残るが未使用）
- PR I を revert: CDN link が復活（template は自前 class 体系のままだが、pico も並走で読まれる）

---

## Plan review チェックポイント（Rev.1 → Rev.2 で反映済）

### Rev.1 review 結果（Claude subagent + Gemini 並行）

両レビュアーとも **修正必要** 判定。High 5 件 / Medium 4 件 / Low 3 件。Rev.2 で全件取込。

| # | Severity | 指摘（要約） | Rev.2 での反映箇所 |
|---|---|---|---|
| R1 | High | `hx-target` が独立行として表に無い、post/get target 仕様が曖昧 | 棚卸し表に `hx-target` / `hx-swap` 独立行追加 |
| R2 | High | `hx-trigger="change from:#sel"` + `hx-include` が pseudo-code に無い | `data-trigger-from` / `data-include` を data-* スキーマと pseudo-code に追加 |
| R3 | High | inline `<script>` (partials/inbox の bulkInbox 等) が partial swap 後に実行されない、CSP 違反 | 「既存 inline JS」節を全面書き換え（partial 内 `<script>` 完全削除を Critical 明記）+ `data-bulk-action` declarative 設計追加 |
| R4 | High | inline `style="..."` 属性 70 箇所超が CSP `style-src-attr 'unsafe-inline'` を要求 | Risk register + 棚卸し表に追記、PR H で全 class 化を必須要件化 |
| R5 | High | `onclick="showTab(...)"` が CSP `'unsafe-inline'` を要求 | 棚卸し表に `onclick` 行追加 + `data-tab` + click delegation 設計 |
| R6 | High | E2E `form[hx-post*=]` selector 依存、PR H で書き換え必須 | Risk register に明記、PR H 受入基準に追加 |
| R7 | Medium | `setupPolls()` の中身が空 | コア API pseudo-code を全展開（即時 fetch + interval + document.hidden + WeakMap 二重 attach 防止） |
| R8 | Medium | partial swap 後の新 `data-poll` element が polling されない | MutationObserver で `addedNodes` 監視 → `setupPolls(n)` 再呼出 |
| R9 | Medium | ハードコード色 `#d4edda` 等が design tokens 化漏れ | CSS design tokens 節に追加 |
| R10 | Medium | ブラウザ static cache (Werkzeug 12h) で並存期間に問題 | `?v={{ asset_version }}` cache busting 戦略を設計に追加（PR G で実装） |
| R11 | Low | `hx-include` の汎用置換方針が無い | `data-include="#sel"` で querystring/FormData マージ、pseudo-code に実装 |
| R12 | Low | pico `.container` の max-width 値が未定 | `.layout-container` に max-width breakpoints (720/960/1200) を確定 |
| R13 | Low | LICENSE / pico 値参照方針 | ADR Decision 節に「事実値（色 hex / size px）は参考可、selector 構造は独自実装」を明記（ADR 起草で対応） |

### Rev.2 で残る検討事項（軽微）

- `hx-swap` は全箇所 innerHTML 固定。将来 `outerHTML` / `beforeend` 等が必要になった場合の拡張余地は ADR の Known Limitations に記録（実装は不要）
- dark theme は本 PR scope 外、PR I 後の follow-up

### Rev.4 Gemini 再レビュー反映（追加 High 1 / Medium 3）

| # | Sev | 指摘 | 反映先 |
|---|---|---|---|
| G1 | High | CSRF token 動的更新 (server 側 rotation 対応) | pseudo-code の `csrf()` ヘルパに「毎 fetch ごと meta 読む、抽出保持パターン禁止」コメント追加 |
| G2 | Medium | MutationObserver `removedNodes` は再帰しないので **自身 + 子孫** を明示走査 | pseudo-code 修正: `n.matches('[data-poll-url]')` で自身 + `n.querySelectorAll('[data-poll-url]')` で子孫を両方処理 |
| G3 | Medium | Polling のネットワークエラー時 exponential backoff（連続失敗で負荷増回避） | `_pollTimers` を `{intervalId, failures, baseInterval}` 拡張、`pollOnce` で成功時 reset / 失敗時 `failures++` + `Math.min(base × 2^failures, 60s)` で reschedule |
| G4 | Medium | Test Strategy で **各 partial endpoint** を Flask test client で直接叩いて BS4 parse | Test Strategy: index.html だけでなく `/partials/stats` `/partials/inbox` `/partials/whitelist` `/partials/requests` `/partials/tool-uses` も BS4 で検証 |

### Rev.3 self-review 反映（追加 High 4 / Medium 6 / Low 5）

| # | Sev | 指摘 | 反映先 |
|---|---|---|---|
| S1 | High | `hx-*` 出現数 **19→23**、種類 **10→9** の誤記 | 棚卸し節冒頭に修正、`hx-target` を独立カウント |
| S2 | High | `data-target` 命名衝突（既存 whitelist.html:121 が id 文字列として使用済） | `data-swap-target` に rename、既存 url-suggest 側を `data-suggest-target` に rename |
| S3 | High | 棚卸し: `hx-confirm` を持たない form (Restore / dismiss) が「各 form」一括化で誤読リスク | 棚卸し表で `hx-post (with confirm)` / `hx-post (without confirm)` 行を分離 |
| S4 | High | `<meta name="csrf-token">` 保持の deliverable 化漏れ | ADR Decision + PR H 受入基準で明記必須 |
| S5 | Medium | pseudo-code の `el.dataset.target || #${el.id}` fallback が仕様と乖離 | pseudo-code を修正: target 未指定なら **自身に swap** に統一 |
| S6 | Medium | `data-poll="/path:5000"` の path に `:` を含むケース未考慮 | `data-poll-url` + `data-poll-interval` の 2 属性に分離 |
| S7 | Medium | PR G で `asset_version` 未注入時の Jinja UndefinedError | `app.config["ASSET_VERSION"] = ""` default + `{{ ...|default('') }}` defensive |
| S8 | Medium | PR H 中間状態で `hx-*` と `data-*` 両持ちで二重 POST | PR H 受入基準: 「commit 単位で完全置換、両持ち禁止」 |
| S9 | Medium | `test_dashboard_inline_assets.py` の grep ベースは Jinja コメント等で false positive | Test Strategy に「BeautifulSoup で render 後を parse」明記 |
| S10 | Medium | stats partial `<h2 class="status-BLOCKED">` 単独 selector の自前 CSS 設計 | `.status-BLOCKED` 単独 selector を採用、`.status-badge.status-BLOCKED` のような複合不要 |
| S11 | Low | MutationObserver の `removedNodes` で interval leak | pseudo-code に `clearInterval` + `_pollTimers.delete()` を追加 |
| S12 | Low | DOM API による style 設定が CSP 対象か | CSP は HTML attribute の inline style のみ評価 → JS 経由は安全。ADR Known Limitations に明記 |
| S13 | Low | url-suggest の `li.style.color = ...` 設定 | `li.classList.add('suggest-applied')` に変更し CSS 側で色定義 |
| S14 | Low | CSP 構文の正規化（whitespace 等）| Test Strategy に「`;` split → directive ごと parse」明記 |
| S15 | Low | ADR / Plan の pseudo-code 正本性 | Plan を正本、ADR には要点 30 行抜粋（PR G 実装者は ADR だけで実装可、深掘りは Plan へ） |

---

## 受入基準（PR F）

- [ ] `docs/dev/adr/0004-dashboard-external-deps-removal.md` が merged
- [ ] HTMX 属性棚卸し表（全使用属性 + 置換方針）が ADR 内に含まれる
- [ ] CSS design tokens 表が ADR 内に含まれる
- [ ] vanilla JS API のサンプルコード（~50 行）が ADR 内に含まれる
- [ ] 移行戦略（並存期間 + Rollback）が ADR 内に含まれる
- [ ] BACKLOG.md の Sprint 007 行が PR F 着手中マーク
- [ ] PR description にレビュー対応サマリ（Plan review 結果 + self-review 結果）

---

## Out of scope（本 PR で扱わない）

- 実装そのもの（PR G〜I）
- dark theme（PR I 後の follow-up）
- pico をローカル self-host する代替案（ADR の Alternatives に却下理由を併記するに留める）
- E2E テストの拡張（PR H で必要分のみ追従）

---

## 参照

- 包括レビュー: [docs/dev/reviews/2026-04-18-comprehensive-review.md](../dev/reviews/2026-04-18-comprehensive-review.md)（M-1 / L-6）
- 統合作業計画: [docs/plans/2026-04-18-consolidated-work-breakdown.md](2026-04-18-consolidated-work-breakdown.md) Sprint 007 節
- ADR 0005 (fail-closed addons): [docs/dev/adr/0005-fail-closed-addons.md](../dev/adr/0005-fail-closed-addons.md) — 構成のテンプレートとして参照
