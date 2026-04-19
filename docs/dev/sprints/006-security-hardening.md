# Sprint 006: Security Hardening (Medium + Supply Chain + TOCTOU)

| 項目 | 値 |
|---|---|
| 期間 | 2026-04-19（1 日） |
| テーマ | [2026-04-18 包括レビュー](../reviews/2026-04-18-comprehensive-review.md) の Medium 全件 (M-2〜M-8) + サプライチェーン hardening (Dependabot / pip-audit) + G3-B1 (DB 権限) を 3 PR で解消 |
| 親計画 | [2026-04-18 統合作業ブレークダウン](../../plans/2026-04-18-consolidated-work-breakdown.md) Sprint 006 |
| 完了 PR | #40 (D), #41 (E), #46 (F) |
| 関連 plan docs | [PR D plan](../../plans/sprint-006-pr-d.md) (Rev.2), [PR E plan](../../plans/sprint-006-pr-e.md) (Rev.2), [PR F plan](../../plans/sprint-006-pr-f.md) (Rev.2) |

---

## Sprint Goal

Sprint 005 で Critical / High が片付いた状態に対し、**Medium 全件 + サプライチェーン hardening + 監査ログ 600 + TOCTOU** を 3 PR に分割して解消し、リリース後の Beta phase を前倒しで安全に進められる土台を作る。

- **PR D**: ポリシー adjacent セキュリティ（M-2 / M-5 / M-6 / M-7 / G3-B1）
- **PR E**: サプライチェーン hardening（M-3 / M-4 / Dependabot / pip-audit）
- **PR F**: policy_lock cross-container 共通化（M-8、PR D で defer された問題）

---

## Decisions

### PR D: ポリシー adjacent セキュリティ（#40）

| # | 決定 | 結果 |
|---|---|---|
| D1 | URL scrub (userinfo / query / fragment / 制御文字) + host lowercase 正規化 (M-2) | ✅ `bundle/addons/_url_scrub.py` 新設、`scrub_url` で 4 要素 redact + log injection 防御 |
| D2 | `secret_patterns` を URL にも適用、`URL_SECRET_BLOCKED` で 403 (M-2) | ✅ `PolicyEngine.check_url_secrets`、block_patterns は URL 文脈で FP 多いので適用なし |
| D3 | Content-Length > 1MB を addon 側で 413 fail-closed (M-6) | ✅ `_parse_content_length` (RFC 7230 strict) + 2 段防御 (mitmproxy `--set body_size_limit=1m` も併用) |
| D4 | dashboard `_DOMAIN_RE` を RFC 1035 準拠 strict 化 (M-5) | ✅ `_LABEL_RE = (?!-)[A-Za-z0-9-]{1,63}(?<!-)` + 2 ラベル以上強制、UI 経由 / inbox accept 経由両方塞ぐ |
| D5 | `block_args` 限界の docs 整理 (M-7) | ✅ user-docs に抽象 warning、bypass 例は dev-only `docs/dev/security-notes.md` に分離（agent self-jailbreak 対策） |
| D6 | `harness.db` + WAL + SHM を chmod 600 (G3-B1) | ✅ `_db_secure.py` 新設、symlink follow 抑止 + EPERM fail-safe |
| D7 | self-review fix (Claude H 4 + M 6 / Gemini M 2) | ✅ BLOCK_STATUSES 中央集権 / CR-LF 防御 / host normalize / Content-Length isdigit / inbox _validate_domain / wiring 統合 test 4 件 |

### PR E: サプライチェーン hardening（#41）

| # | 決定 | 結果 |
|---|---|---|
| E1 | Docker image SHA pin (4 image) (M-3) | ✅ node / python / mitmproxy / coredns を **multi-arch manifest list digest** で pin。Apple Silicon arm64 + CI amd64 両対応確認済 |
| E2 | GitHub Actions SHA pin (19 uses 行) (M-4) | ✅ checkout / setup-uv / cache / upload-artifact / download-artifact / pypa-publish 全部 commit SHA pin、`# <tag>` コメント併記 |
| E3 | `pypa/gh-action-pypi-publish` を branch ref → tag SHA に切替 | ✅ `release/v1` (mutable branch) → `v1.14.0` (= 同 commit SHA) で Dependabot tag-based 追跡可能化 |
| E4 | Dependabot 設定 (`.github/dependabot.yml`) | ✅ github-actions / docker x3 / pip x2 を週次更新、`groups` で 1 ecosystem 1 PR 集約、agent-zoo-base internal image は `ignore` |
| E5 | pip-audit を CI に独立 job として統合 | ✅ project + dashboard requirements.txt を OSV.dev 併用で audit、unit matrix とは独立で重複実行を排除 |
| E6 | `docker compose config --resolve-image-digests` 検証 step | ✅ `compose-config` job で SHA pin 構文を PR 段階 fail-fast |
| E7 | self-review fix (Claude H 3 + M 2 / Gemini M 1) | ✅ SHA pin regression test (10 件) / agent-zoo-base ignore / tag rewrite 検出 guide / security-update grouping コメント |

### PR F: policy_lock cross-container 共通化（#46）

| # | 決定 | 結果 |
|---|---|---|
| F1 | `_policy_lock.py` 新設で proxy / dashboard 両方から writable な共有 lock dir 経由で fcntl.flock (M-8) | ✅ `lock_path_for` 3 段 fallback (env / 同階層 / tempdir)、`/locks` を default |
| F2 | reader = warn + passthrough、writer = raise の API 分離 | ✅ `policy_lock_shared` (best-effort、ADR 0005 と両立) / `policy_lock_exclusive` (fail-closed) |
| F3 | `O_NOFOLLOW + 0o600` で symlink 攻撃 / world-readable 抑止 | ✅ `_open_lock_file` helper |
| F4 | `policy_edit.policy_lock` を thin alias 化 | ✅ `from _policy_lock import policy_lock_exclusive as policy_lock`、6 callsite 透過動作 |
| F5 | `PolicyEngine._load` runtime 読込に LOCK_SH (base は不要) | ✅ runtime のみ wrap、mtime stat() も lock 内で取得 (Gemini #2 反映) |
| F6 | docker-compose に proxy / dashboard `./locks:/locks` mount | ✅ dns は不要 (policy 触らない) |
| F7 | `zoo init` で `.zoo/locks/` 自動生成 | ✅ `src/zoo/api.py::init` の runtime dirs に "locks" 追加 |
| F8 | CI E2E P2 で `bundle/locks/` mkdir | ✅ `tests/e2e/test_proxy_block.py::proxy_up` + `.github/workflows/ci.yml::e2e-proxy` 両方 |
| F9 | self-review fix (Claude H 1 + M 2 + L 1 / Gemini M 1 + L 2) | ✅ policy_edit import fallback / `_runtime_mtime` を lock 内 / fallback warn / module-level subprocess target / docs |

---

## Commit Log

```
# PR D (#40) — 2026-04-19 merged
299b1f9 :memo: Sprint 006 PR D commit 1: M-7 block_args 限界の docs 整理
9f876a8 :lock: Sprint 006 PR D commit 2: M-5 _DOMAIN_RE を RFC 1035 準拠 strict 化
f030cda :wrench: Sprint 006 PR D commit 3: M-6 mitmproxy body_size_limit=1m
676c462 :lock: Sprint 006 PR D commit 4: M-2 URL scrub + secret 検査 + M-6 Content-Length fail-closed
0091881 :lock: Sprint 006 PR D commit 5: G3-B1 harness.db + WAL + SHM を chmod 600
008e0bc :lock: Sprint 006 PR D commit 6: self-review (Claude + Gemini) 反映
51fb4f3 :memo: Sprint 006 PR D commit 7: CHANGELOG + 包括レビュー resolved + BACKLOG 更新

# PR E (#41) — 2026-04-19 merged
493ce4f :lock: Sprint 006 PR E commit 1: M-3 Docker image SHA pin
81159c0 :lock: Sprint 006 PR E commit 2: M-4 GitHub Actions SHA pin (19 uses)
62205ea :wrench: Sprint 006 PR E commit 3: Dependabot 設定 + 検証 test
6ad3e16 :wrench: Sprint 006 PR E commit 4: pip-audit + docker compose digest 検証 を CI に統合
a85ad9d :memo: Sprint 006 PR E commit 5: docs 更新 + 包括レビュー M-3 / M-4 resolved + BACKLOG
22e0f43 :lock: Sprint 006 PR E commit 6: self-review (Claude + Gemini) 反映

# PR F (#46) — 2026-04-19 merged
d929853 :sparkles: Sprint 006 PR F commit 1: _policy_lock module 新設
307694c :recycle: Sprint 006 PR F commit 2: policy_edit.policy_lock を _policy_lock 経由に移行
c1ca97c :lock: Sprint 006 PR F commit 3: PolicyEngine._load の runtime 読込に LOCK_SH
7b81908 :wrench: Sprint 006 PR F commit 4: docker-compose に ./locks mount + CI 対応
760dd2c :wrench: Sprint 006 PR F commit 5: zoo init で .zoo/locks/ を生成
3ba70b0 :memo: Sprint 006 PR F commit 6: docs / CHANGELOG / 包括レビュー M-8 resolved
7c2436f :lock: Sprint 006 PR F commit 7: self-review (Claude + Gemini) 反映
```

---

## 検証

| 項目 | 結果 |
|---|---|
| `make unit` (全テスト) | **381 PASS** (Sprint 006 で +94 件、PR D +41 / PR E +13 / PR F +10、self-review fix で +30 件) |
| `make e2e` (P1 dashboard) | **7 PASS** |
| CI `unit` (3.11 / 3.12 / 3.13 matrix) | 全 PR で green |
| CI `pip-audit` | green、No known vulnerabilities found |
| CI `compose-config` | green、SHA pin 構文 OK |
| CI `e2e-dashboard` | green |
| 包括レビュー Medium / G3-B1 の resolved マーク | M-2 / M-3 / M-4 / M-5 / M-6 / M-7 / M-8 / G3-B1 すべて ✅ |

---

## 学び / 次に活かす

### Plan review が High blocker を 2 連続で発見

PR D Plan Rev.1 → Rev.2 で:
- **H1**: M-8 LOCK_SH の lockfile path が ro mount と衝突 → PR F に defer 判断
- **H2**: M-6 `body_size_limit=1m` 単独だと fail-open → addon 側 Content-Length 413 と 2 段防御化

PR E Plan Rev.1 → Rev.2 で:
- **H1**: `package-ecosystem: docker-compose` は実在しない → docker ecosystem で兼用
- **H3**: `pypa/gh-action-pypi-publish` の branch SHA は Dependabot 追跡不可 → tag SHA に切替

**plan review (Claude subagent + Gemini 並行) を都度回す価値が極めて高い**。実装してから気付くと scope や手戻りが大きくなる。Sprint 005 と同様に「Plan → 並行レビュー → Rev.2 → 実装」を全 PR で踏襲できた。

### Self-review でも High が出る

Plan review を通しても、実装段階で **High 級の見落とし** が複数発覚:
- PR D self-review H-1: 新 status `URL_SECRET_BLOCKED` / `BODY_TOO_LARGE` を `blocks` テーブル / dashboard 集計に追加し忘れ
- PR D self-review H-2: `scrub_url` が CR/LF を silent に削除して log injection 余地
- PR E self-review H-1: SHA pin 形式自体の regression 防止 test が無く、後続 PR で SHA pin が消されても検出不能
- PR F self-review H-1: `policy_edit.py` の `_policy_lock` import が `from addons.policy_edit` 経由で fail（フル test run では他テストの sys.path 副作用で偽陽性 PASS）

これらは **コード書いた後の self-review でしか出ない種類の見落とし**。Plan review + Self-review の 2 段構成は冗長ではなく、実質的に異なる種類のバグを catch する補完関係にある。

### 「中央集権定数」が H-1 系の解決に効く

PR D self-review H-1 (新 status の集計漏れ) のような **「複数箇所に同じ列挙を散らした結果、追加忘れ」** バグは `BLOCK_STATUSES` のような中央定数で構造的に回避できる。dashboard 側の SQL `IN (?, ?, ...)` も placeholder + parameterized query に切替えたことで副次的に SQL injection 余地も縮小。**列挙が散らばっている箇所には中央定数化のリファクタ機会**。

### `_url_scrub` / `_db_secure` / `_policy_lock` のような pure helper module 切り出し

mitmproxy 依存の `policy_enforcer.py` から pure 関数だけを切り出すことで、test での import が劇的に楽になる（`addons = [PolicyEnforcer()]` の module-level 副作用を回避）。Sprint 005 で `_fail_closed.py` を切り出した先例があり、PR D / F でも同パターンが効いた。**「policy_enforcer.py の中で完結させたくなる pure 関数は別 module に切る」を習慣化**。

### サプライチェーン hardening の verification cost

SHA pin した digest が本当に multi-arch manifest list か / branch ref が tag rewrite されてないか / Dependabot が agent-zoo-base 等の internal image で warning 出さないか — verification cost が無視できない。`docs/dev/security-notes.md` に運用 guide を残し、Dependabot PR レビューが盲目的にならないようにした。

### macOS Docker Desktop の cross-VM flock 制約

PR F Plan review で Gemini が指摘。VirtioFS / gRPC FUSE 経由で host process と Linux VM 内 container process は flock を共有しない。**「cross-container は OK、host-mode 併用は scope 外」と明示** することで誤った安全感を防いだ。host-mode の限界は `docs/dev/security-notes.md` に明記。

---

## 参照

- ADR: 本 sprint で新規 ADR は無し（PR F の `_policy_lock` 切り出しは PR D の `_url_scrub.py` / `_db_secure.py` 系の compositional refactor として扱える）
- 包括レビュー [2026-04-18](../reviews/2026-04-18-comprehensive-review.md): M-2〜M-8 / G3-B1 すべて ✅
- 統合作業計画 [Sprint 006 節](../../plans/2026-04-18-consolidated-work-breakdown.md#sprint-006-security-hardening2-日2-pr): PR F 追加で 3 PR 構成、すべて完了
- 個別 plan: [PR D](../../plans/sprint-006-pr-d.md), [PR E](../../plans/sprint-006-pr-e.md), [PR F](../../plans/sprint-006-pr-f.md)
- PR: #40 (D), #41 (E), #46 (F)
