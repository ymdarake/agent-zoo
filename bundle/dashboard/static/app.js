/**
 * agent-zoo dashboard — vanilla JS (Sprint 007 PR G)
 *
 * 設計の正本:
 *   docs/dev/adr/0004-dashboard-external-deps-removal.md
 *   docs/plans/sprint-007-pr-f.md (pseudo-code)
 *
 * Declarative API (data-* 属性):
 *   data-poll-url / data-poll-interval / data-swap-target
 *   data-trigger-from / data-include
 *   data-confirm / data-json-body
 *   data-tab
 *   data-bulk-action / data-bulk-select / data-bulk-target / data-bulk-confirm
 *   data-suggest-target
 */
(function () {
  'use strict';

  // === Helpers ===
  // CSRF token は **毎 fetch ごと** meta tag から読む (rotation 対応、抽出保持禁止)
  const csrf = () => {
    const m = document.querySelector('meta[name="csrf-token"]');
    return m ? m.content : '';
  };

  function buildIncludeQuery(includeSel) {
    if (!includeSel) return '';
    const params = new URLSearchParams();
    document.querySelectorAll(includeSel).forEach((el) => {
      if (el.name) params.append(el.name, el.value);
    });
    const qs = params.toString();
    return qs ? '?' + qs : '';
  }

  function swapInto(targetSel, html) {
    if (!targetSel) return;
    const el = document.querySelector(targetSel);
    if (el) el.innerHTML = html;
  }

  // === GET polling (with exponential backoff on error) ===
  // _pollTimers: element → { intervalId, failures, baseInterval }
  const _pollTimers = new WeakMap();
  const MAX_BACKOFF_MS = 60 * 1000;

  function _scheduleInterval(el, ms) {
    const state = _pollTimers.get(el);
    if (!state) return;
    if (state.intervalId) clearInterval(state.intervalId);
    state.intervalId = setInterval(() => {
      if (document.hidden) return;
      pollOnce(el);
    }, ms);
  }

  async function pollOnce(el) {
    if (!el.dataset.pollUrl) return;
    const url = el.dataset.pollUrl + buildIncludeQuery(el.dataset.include);
    try {
      const res = await fetch(url, { headers: { 'HX-Request': 'true' } });
      if (!res.ok) throw new Error('HTTP ' + res.status);
      const html = await res.text();
      if (el.dataset.swapTarget) {
        swapInto(el.dataset.swapTarget, html);
      } else {
        el.innerHTML = html;
      }
      const state = _pollTimers.get(el);
      if (state && state.failures > 0) {
        state.failures = 0;
        _scheduleInterval(el, state.baseInterval);
      }
    } catch (e) {
      console.warn('poll failed', url, e);
      const state = _pollTimers.get(el);
      if (state) {
        state.failures += 1;
        const next = Math.min(
          state.baseInterval * Math.pow(2, state.failures),
          MAX_BACKOFF_MS
        );
        _scheduleInterval(el, next);
      }
    }
  }

  function setupPolls(root) {
    root = root || document;
    const nodes = root.querySelectorAll
      ? root.querySelectorAll('[data-poll-url]')
      : [];
    nodes.forEach((el) => {
      if (_pollTimers.has(el)) return;
      let baseInterval = parseInt(el.dataset.pollInterval || '5000', 10);
      // baseInterval = 0 → 「load only」(HTMX hx-trigger="load" 互換)
      // 負値 / NaN → 5000 ms に fallback
      if (isNaN(baseInterval) || baseInterval < 0) baseInterval = 5000;
      _pollTimers.set(el, { intervalId: 0, failures: 0, baseInterval });
      pollOnce(el); // 即時
      if (baseInterval > 0) {
        _scheduleInterval(el, baseInterval);
      }

      if (el.dataset.triggerFrom) {
        // Plan H レビュー M5: 同 selector + event の listener を 1 度だけ attach。
        // 重複 attach すると MutationObserver で setupPolls 再呼出時に
        // listener 数が N→2N→4N と倍増する。
        const [sel, ev] = el.dataset.triggerFrom.split(':');
        const evName = ev || 'change';
        const key = evName + ':' + sel;
        let bucket = _triggerListenersByTarget.get(key);
        if (!bucket) {
          bucket = new Set();
          _triggerListenersByTarget.set(key, bucket);
          document.body.addEventListener(evName, (e) => {
            if (!(e.target.closest && e.target.closest(sel))) return;
            // bucket 内の全 polling element に通知 (多対 1 trigger をサポート)
            bucket.forEach((targetEl) => pollOnce(targetEl));
          });
        }
        bucket.add(el);
      }
    });
  }

  // Plan H レビュー M5: triggerFrom の重複 attach 防止用 registry。
  // key = "{event}:{selector}", value = Set<polling element>
  const _triggerListenersByTarget = new Map();

  // === Form submit (data-swap-target) ===
  document.body.addEventListener('submit', async (ev) => {
    const form = ev.target;
    if (!form.matches || !form.matches('form[data-swap-target]')) return;
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
    try {
      // Gemini レビュー Medium #4: form.method (property) は HTML 未指定時 'get' を返す
      // ため、`form.method || 'POST'` は常に form.method 採用で POST fallback が効かない。
      // form.getAttribute('method') は未指定時 null → 'POST' fallback 正常動作。
      const method = (form.getAttribute('method') || 'POST').toUpperCase();
      const res = await fetch(form.action, { method, headers, body });
      const html = await res.text();
      swapInto(form.dataset.swapTarget, html);
    } catch (e) {
      console.warn('form submit failed', form.action, e);
    }
  });

  // === Tab nav (data-tab) ===
  document.body.addEventListener('click', (ev) => {
    const tab = ev.target.closest && ev.target.closest('[data-tab]');
    if (!tab) return;
    ev.preventDefault();
    const name = tab.dataset.tab;
    document.querySelectorAll('[id^="tab-"]').forEach((t) => {
      t.classList.add('hidden');
    });
    const target = document.getElementById('tab-' + name);
    if (target) target.classList.remove('hidden');
    // Plan H L8: a11y、aria-selected を更新
    document.querySelectorAll('[data-tab]').forEach((a) => {
      a.classList.remove('active');
      a.setAttribute('aria-selected', 'false');
    });
    tab.classList.add('active');
    tab.setAttribute('aria-selected', 'true');
  });

  // === Bulk toggle-all (data-bulk-toggle-all): 全選択 checkbox の delegation ===
  // Plan H H2: PR G では実装漏れだった toggleAllInbox 代替。
  // change event で [data-bulk-toggle-all] の checked 状態を
  // data-bulk-toggle-scope (selector) 内の [data-bulk-select] に伝播する。
  document.body.addEventListener('change', (ev) => {
    const master = ev.target.closest && ev.target.closest('[data-bulk-toggle-all]');
    if (!master) return;
    const scopeSel = master.dataset.bulkToggleScope;
    const scope = scopeSel ? document.querySelector(scopeSel) : document;
    if (!scope) return;
    scope
      .querySelectorAll('[data-bulk-select]')
      .forEach((cb) => { cb.checked = master.checked; });
  });

  // === Bulk action (data-bulk-action) ===
  document.body.addEventListener('click', async (ev) => {
    const btn = ev.target.closest && ev.target.closest('[data-bulk-action]');
    if (!btn) return;
    ev.preventDefault();
    const scope =
      (btn.closest && btn.closest('[data-bulk-scope]')) || document;
    const ids = Array.from(
      scope.querySelectorAll('[data-bulk-select]:checked')
    ).map((cb) => cb.value);
    if (ids.length === 0) {
      alert('選択してください');
      return;
    }
    if (btn.dataset.bulkConfirm && !confirm(btn.dataset.bulkConfirm)) return;
    try {
      const res = await fetch(btn.dataset.bulkAction, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'HX-Request': 'true',
          'X-CSRFToken': csrf(),
        },
        body: JSON.stringify({ record_ids: ids }),
      });
      const html = await res.text();
      swapInto(btn.dataset.bulkTarget, html);
    } catch (e) {
      console.warn('bulk action failed', btn.dataset.bulkAction, e);
    }
  });

  // === URL suggest (data-suggest-target on <li data-url=...>) ===
  document.body.addEventListener('click', (ev) => {
    const li =
      ev.target.closest &&
      ev.target.closest('li[data-url][data-suggest-target]');
    if (!li) return;
    try {
      const u = new URL(li.dataset.url);
      const p = u.pathname;
      const v =
        p.lastIndexOf('/') > 0
          ? p.substring(0, p.lastIndexOf('/')) + '/*'
          : p + '*';
      const target = document.querySelector(li.dataset.suggestTarget);
      if (target) target.value = v;
      li.classList.add('suggest-applied');
    } catch (_) {
      /* invalid URL → silently skip */
    }
  });

  // === MutationObserver: addedNodes / removedNodes 両方で自身+子孫を走査 ===
  const mo = new MutationObserver((muts) => {
    muts.forEach((m) => {
      m.addedNodes.forEach((n) => {
        if (n.nodeType === 1) setupPolls(n);
      });
      m.removedNodes.forEach((n) => {
        if (n.nodeType !== 1) return;
        const targets = [];
        if (n.matches && n.matches('[data-poll-url]')) targets.push(n);
        if (n.querySelectorAll) {
          n.querySelectorAll('[data-poll-url]').forEach((el) =>
            targets.push(el)
          );
        }
        targets.forEach((el) => {
          const state = _pollTimers.get(el);
          if (state) {
            clearInterval(state.intervalId);
            _pollTimers.delete(el);
          }
        });
      });
    });
  });
  mo.observe(document.body, { childList: true, subtree: true });

  // === Boot ===
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => setupPolls());
  } else {
    setupPolls();
  }
})();
