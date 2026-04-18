# Sprint 005: Critical Security Fix

| 項目 | 値 |
|---|---|
| 期間 | 2026-04-18〜2026-04-19（2 日） |
| テーマ | [2026-04-18 包括レビュー](../reviews/2026-04-18-comprehensive-review.md) の Critical + High を一括解消、Alpha publish 可能な状態へ |
| 親計画 | [2026-04-18 統合作業ブレークダウン](../../plans/2026-04-18-consolidated-work-breakdown.md) Sprint 005 |
| 完了 PR | #37 (A), #38 (B), #39 (C) |
| 完了 ADR | [ADR 0005 Fail-closed Addons](../adr/0005-fail-closed-addons.md) |

---

## Sprint Goal

包括レビューで発見された **リリース blocker**（Critical C-1 / C-2、High H-1〜H-4、Gemini G-2 / G3-B2）を 3 PR に分割して解消する:

- **PR A**: mitmproxy addon の fail-closed 化 (C-2)
- **PR B**: dashboard セキュリティ包括対応 (C-1 / H-1 / H-2 / H-4 / G-2 / G3-B2)
- **PR C**: container hardening (H-3)

Sprint 完了時点で Alpha release 可能な状態を目指す（Phase 1 完全完了）。

---

## Decisions

### PR A: mitmproxy addon fail-closed（ADR 0005）

| # | 決定 | 結果 |
|---|---|---|
| A1 | hook 種別ごとの decorator を用意（`fail_closed_block` / `_ws_message` / `_lifecycle`） | ✅ `bundle/addons/_fail_closed.py` |
| A2 | `policy_enforcer.py` の全 5 event hook に適用 | ✅ request / response / websocket_message / websocket_end / done |
| A3 | mitmproxy 制御例外 (`AddonHalt` / `OptionsError`) は透過 | ✅ `_MITMPROXY_CONTROL_EXCEPTIONS` 動的収集 |
| A4 | WebSocket drop 失敗時の最終防衛線として `flow.kill()` | ✅ Gemini review 反映 |
| A5 | ctx.log 失敗時 stderr fallback の 2 段防御 | ✅ |
| A6 | 14 テスト (正常 / 例外 / 既存 response 保護 / drop 失敗 / ctx 不在 / 既存 response 上書き / 制御例外透過) | ✅ |

### PR B: dashboard セキュリティ包括

| # | 決定 | 結果 |
|---|---|---|
| B1 | `FLASK_DEBUG=1` 撤去、`gunicorn` 復元 (C-1) | ✅ `docker-compose.yml` |
| B2 | Flask-WTF CSRFProtect 導入 (H-1) | ✅ `<body hx-headers>` で HTMX 自動送出 + `meta` tag で fetch() 送出 |
| B3 | record_id strict regex + `path.resolve().is_relative_to` 2 段防御 (H-2) | ✅ policy_inbox / dashboard 両層で検証 |
| B4 | `hx-vals` を `|tojson|forceescape` で JSON-safe 化 + stem filter (H-4) | ✅ |
| B5 | CSP + X-CTO + X-Frame-Options + Referrer-Policy (G-2) | ✅ `@app.after_request` |
| B6 | Strict Host middleware (G3-B2) | ✅ IPv6 / case / trailing dot / 不正 port 全対応 |
| B7 | 38 テスト追加 (CSRF / path traversal / security headers) | ✅ |

### PR C: container hardening (H-3)

| # | 決定 | 結果 |
|---|---|---|
| C1 | proxy: `user: 1000 + cap_drop [ALL] + no-new-privileges + entrypoint bypass` | ✅ mitmdump を非 root + 無 cap で直接 exec |
| C2 | dashboard: `user: HOST_UID + cap_drop [ALL] + no-new-privileges` | ✅ gunicorn が host UID で run |
| C3 | dns: `cap_drop [ALL] + cap_add [NET_BIND_SERVICE] + no-new-privileges` | ✅ CoreDNS の port 53 bind を許容 |
| C4 | 実機 `docker compose up -d` で proxy PID 1 = UID 1000 + CapBnd=0、dashboard PID 1 = UID 502 + CapBnd=0 確認 | ✅ |

---

## Commit Log

```
# PR A (#37) — 2026-04-18 merged
78f21d2 :white_check_mark: addons/_fail_closed: mitmproxy addon 用 fail-closed decorator + test
77e5a11 :lock: policy_enforcer: 全 mitmproxy event hook に fail-closed decorator を適用
a81c565 :memo: ADR 0005 fail-closed addons + architecture / CHANGELOG / review 更新
ddbadf9 :memo: Sprint 005 PR A self-review 反映: 制御例外透過 / 追加テスト / stderr 2 段 / ADR 拡充
9b7f542 :lock: Gemini review 反映: WebSocket drop 失敗時の flow.kill() 最終防衛線

# PR B (#38) — 2026-04-18 merged
142c880 :lock: docker-compose.yml: dashboard の FLASK_DEBUG=1 撤去 (C-1)
1a55ebf :lock: dashboard: CSRF 対策 (Flask-WTF CSRFProtect) 導入 (H-1)
54d5863 :lock: inbox: record_id の path traversal 対策 (H-2)
2af3b62 :lock: dashboard: HTMX 属性 injection / XSS / CSP / DNS rebinding 対策 (H-4 / G-2 / G3-B2)
1f42044 :memo: CHANGELOG + 包括レビューに Sprint 005 PR B の resolved マーク + uv.lock 更新
4184824 :recycle: Sprint 005 PR B self-review 反映: Host 正規化 / IPv6 対応 / SECRET_KEY 強化 / test 拡張
6016dc6 :lock: Gemini review 反映: Host 正規化強化 (port / trailing dot / case)

# PR C (#39)
82b6461 :lock: docker-compose: proxy / dashboard / dns に container hardening (H-3)
# （本 archive + 残 docs commit が続く）
```

---

## 検証

| 項目 | 結果 |
|---|---|
| `make unit` (全テスト) | **287 PASS** (Sprint 005 で +53 tests) |
| `make e2e` (P1 dashboard) | **7 PASS** |
| CI `e2e-proxy` (post-merge) | PR A / B の main push で自動実行済 |
| 実機 `docker compose up -d` (PR C) | proxy UID 1000 / dashboard UID 502、両 CapBnd=0 |
| 包括レビュー Critical / High の resolved マーク | C-1 / C-2 / H-1 / H-2 / H-3 / H-4 すべて ✅ |

---

## 学び / 次に活かす

### Fail-closed 設計は「契約」

addon が例外で死ぬと mitmproxy は flow を pass-through する (fail-open) という仕様を知ったのは Gemini レビュー経由。「セキュリティ製品が壊れたら **必ず deny**」は明文化されていない暗黙契約だったが、今回 ADR 0005 として明示した。将来 hook 追加時も decorator 漏れをレビューで catch できる。

### 「localhost bind = 安全」は幻想

dashboard は `127.0.0.1:8080` bind だが、ブラウザ経由 CSRF + DNS rebinding で外部 origin から操作可能 (G3-B2)。HTTP API を公開している限り Origin / Host / CSRF の防御は必須。Flask-WTF CSRFProtect + Strict Host middleware で localhost 前提の甘えを解消。

### Docker image entrypoint の CHOWN 要件

mitmproxy/mitmproxy:10 image は `docker-entrypoint.sh` で `usermod` を呼ぶため、`cap_drop: [ALL]` だけでは container 起動が失敗する。`entrypoint: [""]` で bypass し、`user: 1000` で直接 mitmdump を起動することで cap 完全剥奪と両立。この種の「image 側の root 前提 init」対応は他の container でも今後必要になる。

### 2 段防御 (defense-in-depth) の具体例

`record_id` の path traversal 対策で、以下 2 層を両方実装:
1. **regex whitelist** (`^[A-Za-z0-9T:_-]+$`) - 表層、入力 validation
2. **`path.resolve().is_relative_to(inbox_resolved)`** - 深層、symlink / encoding bypass を物理的に阻止

どちらか 1 つでも強固だが、両方実装することで「regex を誰かが後で緩めても symlink bypass が効かない」「symlink 実装がバグっても regex で弾ける」相互保険が効く。テストも両層で独立検証。

### Self-review + Gemini の相互補完

- **Claude subagent** (一次 / 静的解析): コード整合性、テスト漏れ、false positive 候補
- **Gemini 2.5 Pro** (セカンドオピニオン / 設計面): アーキテクチャ盲点、既知仕様 (mitmproxy fail-open, DNS rebinding)
- **Gemini 3 Flash Preview** (サードオピニオン / 裏取り): Claude/Gemini 2.5 が見逃した仕様確認 (drop() → flow.kill()、Host 正規化)

3 層レビュー体制で Critical 1 + High 1 + Medium 複数の追加検出があり、Claude 単体では気付けなかった。

---

## 参照

- ADR 0005 [Fail-closed Addons](../adr/0005-fail-closed-addons.md)
- 包括レビュー [2026-04-18](../reviews/2026-04-18-comprehensive-review.md)
- 統合作業計画 [Sprint 005 節](../../plans/2026-04-18-consolidated-work-breakdown.md#sprint-005-critical-security-fix2〜3-日3-pr)
- PR: #37 (A), #38 (B), #39 (C)
