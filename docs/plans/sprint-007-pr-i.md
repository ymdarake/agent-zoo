# Sprint 007 PR I: CDN 削除 + CSP `'self'` 厳格化

| 項目 | 値 |
|---|---|
| 作成日 | 2026-04-19 |
| 改訂 | Rev.3（実装 self-review (Claude + Gemini) で両者 merge OK 判定、Low 改善余地は Sprint 008 follow-up） |
| Sprint | 007 |
| PR | F (✅) → G (✅) → H (✅) → **I (本 PR、最終)** |
| 親設計 | [ADR 0004](../dev/adr/0004-dashboard-external-deps-removal.md) (Rev.4) |
| 親計画 | [Plan F](sprint-007-pr-f.md) / [Plan G](sprint-007-pr-g.md) / [Plan H](sprint-007-pr-h.md) |

---

## ゴール

Sprint 007 の最終 PR。**外部 CDN 参照を 0 件にし、CSP を `'self'` のみに厳格化** して包括レビュー M-1 / L-6 を完全 resolved する。Beta release candidate に到達。

### Deliverables

1. **`bundle/dashboard/templates/index.html` から CDN link / script 完全削除**
   - `<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@picocss/pico@2/css/pico.min.css">` 削除
   - `<script src="https://unpkg.com/htmx.org@2.0.4">` 削除
2. **`bundle/dashboard/app.py` の CSP を `'self'` のみに厳格化 + form-action 追加**
   - **`setdefault` → `=` 強制代入** (review H-1: 他 layer での弱い CSP inject を防ぐ)
   - 既存:
     ```
     "default-src 'self'; "
     "style-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; "
     "script-src 'self' https://unpkg.com 'unsafe-inline'; "
     ...
     ```
   - 新 (Rev.2):
     ```
     "default-src 'self'; "
     "style-src 'self'; "
     "script-src 'self'; "
     "img-src 'self' data:; "
     "connect-src 'self'; "
     "frame-ancestors 'none'; "
     "base-uri 'none'; "
     "object-src 'none'; "
     "form-action 'self'"          ← Rev.2 追加 (default-src の fallback 対象外、CSP3)
     ```
   - **`'unsafe-inline'` / CDN ドメインは完全除去**
   - **`Permissions-Policy: camera=(), microphone=(), geolocation=(), payment=()`** を追加 (defense-in-depth)
3. **`tests/test_dashboard_security_headers.py` に厳格化 assert を追加** (review H-2、新規 test と既存 test を両方守る)
   - `'unsafe-inline' not in csp`
   - `cdn.jsdelivr.net not in csp` / `unpkg.com not in csp`
   - `form-action 'self'` の存在
   - `Permissions-Policy` ヘッダの存在
4. **`tests/test_dashboard_csp.py` 新規** (Plan H Test Strategy 準拠)
   - CSP value を `;` split → directive ごと parse
   - `'unsafe-inline'` を全 directive で含まない assert
   - `cdn.jsdelivr.net` / `unpkg.com` を含まない assert
   - `default-src` が `'self'` のみ
   - `form-action 'self'` の存在
   - `Permissions-Policy` の存在
   - **強制代入の証明** (review H-1): test client が CSP を `setdefault` で先に立てたケースを simulate し、response が新 CSP で上書きされていることを assert
5. **`tests/test_dashboard_inline_assets.py` 拡張**
   - index.html に CDN URL が含まれない assert (`cdn.jsdelivr.net` / `unpkg.com` 文字列が無い)
   - **`<base>` 要素の不在** (review M-3): `soup.find("base") is None`
   - **`<link rel="dns-prefetch">` / `<link rel="preconnect">` の CDN 向け不在** (Gemini L-5): `for link in soup.find_all("link"): rel = (link.get("rel") or [""])[0]; if rel in ("dns-prefetch", "preconnect"): assert "cdn.jsdelivr.net" not in (link.get("href") or "") and "unpkg.com" not in ...`
6. **`tests/e2e/test_dashboard.py` オフライン動作確認** (Playwright で CDN ドメイン block)
   - **正確な route pattern** (review M-1): `page.route(re.compile(r"https?://(cdn\\.jsdelivr\\.net|unpkg\\.com)/.*"), lambda r: r.abort())`
   - `page.goto(dashboard)` の **前** に setup
   - 既存 7 ケースが全 PASS することを確認 (自前 CSS/JS のみで動作)
   - 別ファイル化を検討 (`tests/e2e/test_dashboard_offline.py`)、または既存ファイル内で `@pytest.mark.parametrize("offline", [False, True])` 形式
7. **`docs/dev/reviews/2026-04-18-comprehensive-review.md` の M-1 / L-6 を resolved マーク** (review L-4)
   - 形式: `✅ Sprint 007 PR I で resolved（CDN link 完全削除 + CSP 'self' のみ + form-action 'self' に厳格化、tests/test_dashboard_csp.py）`
   - L-6 は `H-4 で escape 対策済 + PR I で CSP 'self' により script 注入経路完全封鎖` の 2 段で resolved
8. **`docs/dev/security-notes.md`** (review L-3、必須化): 「CDN 依存ゼロ達成 + CSP 厳格化」エントリ追加
9. **`docs/plans/sprint-007-pr-i.md`** (本ファイル)

### Non-goals

- dark theme 対応 (Sprint 007 後 follow-up)
- a11y polish (tabindex 動的更新 / dispatchEvent / id slugify、Sprint 008 follow-up)
- README screenshots 更新 (#32、user 環境依存)

---

## 重要な確認: PR H 段階で動作可能か

PR H で **inline `<script>` / `<style>` / `style=` / `onclick=` / `hx-headers` / `data-target` を全削除済**。残るのは **CDN link** のみ。CDN を削除しても自前 CSS/JS で全機能が動くはず (PR H で E2E 7/7 PASS 確認済)。

PR I の merge 後、CSP が初めて `'unsafe-inline'` 無しで効くため、**inline asset が 1 つでも残っていたらブラウザでブロックされる**。Plan H の BS4 test (test_dashboard_inline_assets.py 8 件) で全 partial を assert 済なので **静的に保証** されている。

---

## Risk register

| リスク | 軽減策 |
|---|---|
| **CDN 削除後にブラウザで動かない** (CSS/JS の依存漏れ) | E2E P1 7 ケース + オフライン test (CDN block) で動作保証 |
| **CSP `'self'` で inline asset が CSP violation エラー** | Plan H BS4 test で全 partial の inline 不在を保証済、静的に守られる |
| **GitHub Actions の paths-ignore で CSP test が走らない** | tests/test_dashboard_csp.py は `tests/` 直下に置く、ci.yml の `paths-ignore` 対象外 |
| **包括レビューの M-1 / L-6 resolved マーク漏れ** | docs/dev/reviews/2026-04-18-comprehensive-review.md に明示 |
| **古い CDN cache** | PR I merge 後にユーザーがハード reload 必要、リリースノートに明記 |
| **Playwright での route block** | `page.route("https://cdn.jsdelivr.net/**", lambda r: r.abort())` パターンで全 CDN リクエストを拒否、E2E 全 PASS |
| **CSP の `default-src 'self'` で WebSocket がブロック** | dashboard は WebSocket 未使用、影響無し |
| **CSP の `style-src 'self'` で CSS の `style.cssText` 動的設定がブロック** | DOM API 経由は CSP `style-src-attr` の対象外 (CSP3 仕様、ADR 0004 Known Limitations 明記) |
| **`FLASK_DEBUG=1` 起動時の Werkzeug interactive debugger が CSP `'unsafe-inline'` 違反で動かない** (review M-4) | 想定通り (Sprint 005 PR B で `FLASK_DEBUG=1` は dev override のみ)。Risk として認識、本番 gunicorn では問題なし |
| **`response.headers.setdefault` のままだと他 layer の弱い CSP が先に立つ可能性** (review H-1) | `response.headers["Content-Security-Policy"] = ...` で **強制上書き** に変更、test で証明 |

---

## 受入基準 (Rev.2)

- [ ] `bundle/dashboard/templates/index.html` から `cdn.jsdelivr.net` / `unpkg.com` 文字列が消える (grep で 0 件)
- [ ] `bundle/dashboard/app.py` の CSP に `'unsafe-inline'` / `cdn.jsdelivr.net` / `unpkg.com` が含まれない
- [ ] CSP に **`form-action 'self'`** が含まれる (default-src fallback 対象外、明示必要)
- [ ] CSP 設定が **`response.headers["Content-Security-Policy"] = ...`** (強制上書き) に変更
- [ ] **`Permissions-Policy: camera=(), microphone=(), geolocation=(), payment=()`** 追加
- [ ] `tests/test_dashboard_csp.py` 新規 5+ 件 PASS (CSP parse + form-action + Permissions-Policy + 強制上書き証明)
- [ ] `tests/test_dashboard_inline_assets.py` 拡張 (CDN URL / `<base>` / dns-prefetch・preconnect 不在)
- [ ] `tests/test_dashboard_security_headers.py` に厳格化 assert 追加 (review H-2)
- [ ] 既存 396 unit + E2E P1 7 件 全 PASS
- [ ] **オフライン test** (Playwright route で CDN block) で E2E P1 全 PASS
- [ ] 包括レビュー M-1 / L-6 resolved マーク (`✅ Sprint 007 PR I で resolved` 形式)
- [ ] **`docs/dev/security-notes.md`** に「CDN 依存ゼロ達成 + CSP 厳格化」記録 (必須化)

---

## Rev.2 反映マッピング

| # | Sev | 指摘 | 反映 |
|---|---|---|---|
| H-1 | High | `setdefault` だと他 layer の弱い CSP が勝つ可能性 | `=` 強制上書きに変更、test で証明 |
| H-2 | High | 既存 test_dashboard_security_headers.py に厳格化 assert 追加漏れ | 既存 test に `'unsafe-inline' not in csp` 等を追加 |
| M-1 | Medium | Playwright route の URL pattern 不正確 | regex で `https?://(cdn\\.jsdelivr\\.net|unpkg\\.com)/.*` パターン化 |
| M-2 | Medium | `form-action` が default-src fallback 対象外 | CSP に追加 |
| M-3 | Medium | `<base>` 要素が後で追加される regression | BS4 test で不在 assert |
| M-4 | Medium | FLASK_DEBUG 競合の Risk note | Risk register に追加 |
| Gemini Medium | | Permissions-Policy 追加 | header 追加 + test |
| L-1 | Low | CSP violation 検出 E2E test | Sprint 008 follow-up 明記 |
| L-3 | Low | security-notes.md 更新を必須化 | 受入基準で必須化 |
| L-4 | Low | resolved マーク文字列を明示 | deliverable 7 で文字列形式明記 |
| L-5 (Gemini) | Low | dns-prefetch / preconnect 不在 assert | BS4 test で追加 |

---

## Rev.3 self-review (実装) 反映

### Claude self-review (Phase 1)
- 全観点 Pass、修正必要な指摘なし
- `<base>` 不在 + dns-prefetch 不在 + counter[0] closure + Permissions-Policy syntax 等を網羅 OK

### Gemini 再レビュー (Phase 3)
- 全観点 Pass、merge OK 判定
- Sprint 008 candidates (low priority):
  - COOP `same-origin` / CORP `same-origin` 追加 (defense-in-depth、現状 over-engineering)
  - X-Frame-Options 等の hardening を `setdefault` から `=` 強制上書きに統一 (整合性)
  - Playwright counter の `asyncio.Lock` 化 (race 厳密化、現状 GIL で許容範囲)

### 結論

- High / Medium 指摘なし
- Sprint 007 PR I は merge 可能、**M-1 / L-6 を完全 resolved**
- Beta release candidate 到達

---

## 参照

- ADR 0004: `docs/dev/adr/0004-dashboard-external-deps-removal.md`
- 包括レビュー M-1 / L-6: `docs/dev/reviews/2026-04-18-comprehensive-review.md`
- CSP3 仕様: <https://www.w3.org/TR/CSP3/>
- Permissions Policy 仕様: <https://www.w3.org/TR/permissions-policy/>
