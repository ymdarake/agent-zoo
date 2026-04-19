# Sprint 006 PR D 実装計画: ポリシー adjacent セキュリティ (Rev. 2)

| 項目 | 値 |
|---|---|
| 対象 | 包括レビュー M-2 / M-5 / M-6 / M-7 + G3-B1 (M-8 は別 PR へ defer) |
| 親計画 | [docs/plans/2026-04-18-consolidated-work-breakdown.md](2026-04-18-consolidated-work-breakdown.md) Sprint 006 PR D |
| ブランチ | `sprint-006/policy-adjacent-security` |
| 想定期間 | 1 日 |
| Rev. 履歴 | Rev.1 (initial) → Rev.2 (Claude subagent + Gemini 3 flash 並行レビュー反映) |

---

## レビュー指摘反映サマリ（Rev.2 で追加変更）

| 指摘 | Severity | 反映内容 |
|---|---|---|
| Claude H1 / Gemini H1 — M-8 lock path ro-mount 衝突 | High | **M-8 を PR D から defer**。現状の atomic rename + addon 単一プロセス読みで TOCTOU は実害小、cross-container lock dir 設計は別 ADR 案件 |
| Claude H2 / Gemini H2 — M-6 body_size_limit fail-open | High | body_size_limit は OOM 保護用に維持、**同時に request() hook で Content-Length > 1MB を 413 で遮断**する fail-closed 前段を追加 |
| Claude M1 / L7 — M-2 config 追加方針が親計画と不整合 | Medium | 常時 ON に統一。親計画書 (`consolidated-work-breakdown.md`) P006D-1 の「`apply_to = ["body", "url"]` 追加」を削除 |
| Claude M2 / M3 — M-5 既存 entry sweep / allow-deny matrix 不足 | Medium | 既存 `policy.toml` 12 entries を unit test で通す明示 + 拒否 7 ケース / 許可 6 ケースの full matrix を test 仕様に追加。revoke / dismiss / restore 系は strict 適用（緩い validation 分岐は入れない → 理由: 古い緩い entry は base `policy.toml` に残っても UI 経由追加は拒否すべき） |
| Claude M4 / Gemini M-2 — scrub_url の IPv6 / userinfo / fragment | Medium | scrub_url 仕様を拡張: query + fragment + userinfo 3 要素を redact。parse 失敗時は `[invalid-url]` 固定 |
| Claude M5 — G3-B1 で WAL / SHM 漏れ | Medium | `_secure_db_file` を db / db-wal / db-shm の 3 ファイルに適用 |
| Claude M6 / Gemini M-7 — agent self-jailbreak リスク | Medium | `bundle/policy.toml` のコメントは中立表現のみ。具体的 bypass 例は **`docs/dev/security-notes.md`** (新設、dev-only、agent 非参照 path) に記載 |
| Claude M7 — commit 分割方針なし | Medium | 6 commit の順序明記 (M-7 → M-5 → M-6 → M-2 → G3-B1 → docs/CHANGELOG) |
| Gemini Low — IDN / busy_timeout | Low | IDN は Punycode 前提を CHANGELOG に明記、busy_timeout は現状 WAL + 低書き込み頻度で問題化していないので defer |
| Claude L2〜L8 — 記述ミス / checklist 欠落 | Low | 影響範囲表修正 / commit 単位 checklist 追加 / test ケース数明細 (M-7 除き新規 25 件) / base lock 取得削除 |

### H1 の deferred 理由（重要、再発防止のため記録）

**当初案**: `policy_enforcer.py::PolicyEngine._load` に `fcntl.LOCK_SH` を追加、`policy_edit.py::policy_lock` の `LOCK_EX` と協調。

**破綻点**:
1. `bundle/docker-compose.yml:146` で proxy は `./policy.runtime.toml:/config/policy.runtime.toml:ro` で ro mount
2. `lock_path = f"{os.path.abspath(policy_path)}.lock"` だと proxy 側で `/config/policy.runtime.toml.lock` の open("w") が EROFS / EACCES
3. 結果として `maybe_reload` が常時 except 経路 (旧ポリシー保持) へ → reload 機能が silently 停止

**正しい設計に必要な追加工事**:
- proxy / dashboard 両方に rw mount できる lock dir (例: `./locks:/locks`) を新設
- lock path mapping helper (`_policy_lock_path(policy_path) -> str`) を共通モジュール化
- `POLICY_LOCK_DIR` env 対応 + defaults + host-mode fallback
- 既存 `policy_edit.py::policy_lock` 全 callsite (6 箇所) を新 helper に移行

これは **6 commit 越えの独立 PR スコープ**。PR D の他 5 項目と mix すると review 粒度が破綻するため、Sprint 006 PR F (新設) として独立対応とする。

**M-8 当面の扱い**:
- 現行 atomic rename で partial read は防げている（direct overwrite fallback は稀なケースのみ）
- マルチプロセス競合は dashboard 単一プロセス書き + proxy 単一プロセス読みで実質衝突ほぼ無し
- 包括レビューの resolved マークは付けず、「PR F で対応予定」と注記
- BACKLOG に PR F を追記

---

## 対象指摘（Rev.2 確定分）

| ID | 概要 | ファイル |
|---|---|---|
| **M-2** | URL query strip + secret_patterns を URL 適用 + Content-Length 前チェック | `bundle/addons/policy_enforcer.py`, `policy.py` |
| **M-5** | `_validate_domain` 正規表現を RFC 1035 準拠 strict 化 | `bundle/dashboard/app.py` |
| **M-6** | mitmproxy `body_size_limit=1m` (OOM 保護) + Content-Length 413 fail-closed | `bundle/docker-compose.yml`, `policy_enforcer.py` |
| **M-7** | `block_args` の限界を user docs に抽象 warning + dev-docs に bypass 例列挙 | `docs/user/policy-reference.{md,en.md}`, `docs/dev/security-notes.md` (新設) |
| **G3-B1** | `harness.db` + WAL + SHM を chmod 600 | `bundle/addons/policy_enforcer.py` |

**defer**: M-8 → Sprint 006 PR F (新設、`policy_lock` 共通化)

---

## 設計判断（Rev.2 確定版）

### M-2: URL scrub + secret_patterns on URL + Content-Length 前チェック

**仕様 (scrub_url)**:
```
scrub_url(url: str) -> str:
  - parse 失敗時 → "[invalid-url]" 固定
  - userinfo (user:pass@) → "[redacted]@" 置換
  - query (? 以降) → "?[redacted]" (空 query は省略)
  - fragment (# 以降) → 削除
  - scheme / host / port / path はそのまま
```

**設計**:
1. `bundle/addons/policy_enforcer.py` に module-level `scrub_url(url) -> str`
2. `PolicyEngine.check_url_secrets(url) -> tuple[bool, str]` を追加（secret_patterns のみ）
3. `request()` hook で:
   - 冒頭: `url_safe = scrub_url(flow.request.url)` 計算
   - **Content-Length 前チェック（M-6 fail-closed と融合）**:
     ```python
     content_length = _parse_content_length(flow.request.headers.get("content-length"))
     if content_length is not None and content_length > _MAX_BODY_BYTES:
         self._log_request(host, method, url_safe, "BODY_TOO_LARGE", content_length, "exceeds body_size_limit")
         flow.response = http.Response.make(413, b"Payload too large", ...)
         return
     ```
   - `is_allowed` → `check_rate_limit` → **`check_url_secrets(flow.request.url)`** (NEW) → `check_payload(body)` の順
   - URL secret 検出時は `URL_SECRET_BLOCKED` status で 403
   - 全 `_log_request` 呼出で `url_safe` を渡す (raw url は DB に書かない)
4. `_MAX_BODY_BYTES = 1024 * 1024` 定数 (1 MB)。mitmproxy `--set body_size_limit=1m` と一致させる

**代案比較**:
- (a) `?[redacted]` placeholder 保持 ← 採用。query 存在の可観測性確保
- (b) query 完全削除 → デバッグ性 ↓
- (c) key 名だけ保持 (`?api_key=[redacted]&q=[redacted]`) → 実装複雑度見合わない

**policy.toml 設定追加**: しない（常時 ON）。opt-out が必要になった場合は別 sprint で config 追加。

### M-5: Strict `_DOMAIN_RE`

**設計**:
```python
_LABEL_RE = r"(?!-)[A-Za-z0-9-]{1,63}(?<!-)"
_DOMAIN_RE = re.compile(rf"^(\*\.)?({_LABEL_RE}\.)+{_LABEL_RE}$")
```

**許可マトリクス**:
| 入力 | 判定 | 根拠 |
|---|---|---|
| `example.com` | ✅ | 2 label |
| `*.example.com` | ✅ | wildcard + 2 label |
| `foo.bar.baz.com` | ✅ | 4 label |
| `a-b.example.com` | ✅ | label 内 hyphen OK |
| `1.2.3.4` | ✅ | digit-only label は RFC 1035 準拠 |
| `xn--foo.example.com` | ✅ | Punycode OK |
| `localhost` | ❌ | single label |
| `*.com` | ❌ | TLD-only wildcard |
| `a..com` | ❌ | 連続 dot |
| `a-.com` | ❌ | trailing hyphen |
| `-a.com` | ❌ | leading hyphen |
| `*.*.example.com` | ❌ | 多段 wildcard |
| `example.com.` | ❌ | trailing dot (DNS absolute; Host ヘッダ側でのみ受理する既存仕様を踏襲) |

**互換性影響**: UI 追加系 (`api_whitelist_allow`, `api_whitelist_allow_path`, `api_whitelist_dismiss`, `api_whitelist_restore`, `api_whitelist_revoke_domain`, `api_whitelist_revoke_path`) 6 endpoint で適用。base `policy.toml` の現行 entry 12 件 (`api.anthropic.com` 等) はすべて新 regex を通る (unit test で明示検証)。

**user 向け migration note**: 緩い形式 (localhost 等) を使いたい場合は base `policy.toml` を手編集する旨 `docs/user/policy-reference.md` に追記。

**CHANGELOG**: `### Changed` 節にも「dashboard domain validation を strict 化。localhost / single-label host は UI から追加不可」と明記（behavior change）。

### M-6: body_size_limit=1m + Content-Length 413 fail-closed

**2 段防御**:
1. **mitmproxy level**: `--set body_size_limit=1m` → 1MB 超は stream pass-through で OOM 保護
2. **addon level (fail-closed)**: `request()` hook で Content-Length header > 1MB を 413 で事前遮断（M-2 と同じ判定を共有）

**効果**: 正常 API (body < 1MB) は現行通り全検査、巨大 body は (a) OOM 回避 (b) secret_patterns bypass 封じ を両立。

**実装場所**: M-2 の request() hook 改修と一体化。`_MAX_BODY_BYTES` 定数を共有。

**検証**: `zoo build && zoo up` で proxy 正常起動 + 通常 request 疎通 + 1MB+1B request で 413 を手動確認（E2E 自動化は Sprint 006 PR E 以降）。

### M-7: block_args 限界の user-docs 警告 + dev-docs 詳細

**agent self-jailbreak 対策**（レビュー M6 / Gemini M-7）:

**`docs/user/policy-reference.md`（agent 可読な可能性あり）**:
> ⚠ **重要な制約**: `block_args` は **文字列パターンマッチの性質上、本質的に bypass 可能性があります**。LLM が生成するコマンドの完全な危険パターン検知は困難です。**最終的な防御はネットワーク隔離**（外部 API 経由でしか破壊操作できない状態を保つこと）であり、`block_args` は補助的な早期検知として位置づけてください。

(具体的 bypass コマンド例は記載しない)

**`docs/dev/security-notes.md`（新設、dev-only、agent からは参照 path 外）**:
- block_args bypass の具体例（`rm  -rf /` 空白 2 つ / `/bin/rm -rf /` / `R="rm -rf"; eval "$R /"` 等）を列挙
- 「なぜこれらが通るか」の regex 実装詳細
- 将来的な防御強化案の議論記録

**`bundle/policy.toml` の `block_args` 上部コメント**: 中立表現のみ。
```toml
# 引数にこの文字列が含まれたらブロック（実行コマンド・パスのパターン）
# 注: これはワード境界マッチで、完全な検知は困難です。最終的な防御は
#     domains.allow の厳格化によるネットワーク隔離です。カスタマイズは
#     あなたの threat model に合わせて。詳細: docs/user/policy-reference.md
block_args = [
    ...
]
```

### G3-B1: harness.db + WAL + SHM chmod 600

**仕様**:
```python
def _secure_db_file(db_path: str) -> None:
    """DB 本体 + WAL + SHM を chmod 600 に強制。
    bind mount で chmod 不可 (EPERM) な場合は log.error で続行 (fail-safe)。
    """
    for suffix in ("", "-wal", "-shm"):
        target = db_path + suffix
        if not os.path.exists(target):
            continue
        try:
            os.chmod(target, 0o600)
        except OSError as e:
            ctx.log.error(f"chmod {target} failed: {e}")
```

**呼出**:
- `_init_db` の schema 作成後（DB file + WAL + SHM が出揃う PRAGMA journal_mode=WAL 直後の INSERT 前後）
- ~~`done()` 直前にも 1 回 (念のため) 呼ぶ~~ → 実装上は `done()` で `db.close()` のため WAL/SHM が消える。close 後の chmod は無意味なので **実装は `_init_db` の 1 回呼出のみ** とした (self-review M-6 対応)。WAL truncate / rotation で chmod 600 が剥がれる既知制約は `docs/dev/security-notes.md` に明記

**代案比較 (umask 方式)**:
- proxy container entrypoint で `umask 0077` 設定すれば新規 file が自動で 600
- 採用しない理由: (a) 既存 entrypoint 改変が他機能に波及リスク (b) chmod は明示的で audit log で追跡しやすい (c) WAL 生成タイミングは SQLite 内部で不可視、umask 効かないケース理論的にあり

**テスト**: tempfile で空 DB 作成 → `_secure_db_file` 呼出 → `stat().st_mode & 0o777 == 0o600` を 3 ファイル分検証。EPERM 時に log error で落ちないことも mock で検証。

---

## TDD 計画 (Rev.2)

### Test 構成と想定件数

| ファイル | 対象 | 件数 |
|---|---|---|
| `tests/test_url_scrub.py`（新規） | `scrub_url` 8 ケース (query / fragment / userinfo / IPv6 / path-only / 空 / 日本語 / parse 失敗) | 8 |
| `tests/test_dashboard_domain_validation.py`（新規） | `_validate_domain` 許可 6 + 拒否 7 + 既存 `policy.toml` 12 entries sweep | 14 |
| `tests/test_payload_rules.py`（拡張） | `check_url_secrets` 3 ケース + body/URL 両方 1 + block_patterns が URL 非適用 1 | 5 |
| `tests/test_db_permissions.py`（新規） | `_secure_db_file` 3 (db/wal/shm) + EPERM mock 1 | 4 |
| `tests/test_content_length_gate.py`（新規） | Content-Length 413 fail-closed 3 + header 欠落時は通過 1 | 4 |

**合計: 新規 35 件**（親計画 P006D-1〜-6 見積 5 件から増加。review で carve-out が深化した結果）

### Red → Green → Refactor

1. `scrub_url` (最も単純、先行) → Green → Refactor
2. `_secure_db_file` (db+wal+shm、独立) → Green → Refactor
3. `_validate_domain` strict regex (独立、dashboard) → Green → Refactor
4. `check_url_secrets` + `check_payload` 既存互換 → Green → Refactor
5. Content-Length 413 (M-2/M-6 統合) → Green → Refactor

### Commit 分割（PR D 内）

| # | 内容 | 主対象 | 新規テスト |
|---|---|---|---|
| 1 | :memo: M-7 docs + security-notes.md 新設 | 3 docs | 0 |
| 2 | :lock: M-5 `_DOMAIN_RE` strict 化 + test | dashboard | 14 |
| 3 | :wrench: M-6 docker-compose `body_size_limit=1m` | compose | 0 |
| 4 | :lock: M-2 URL scrub + check_url_secrets + Content-Length gate | addons | 8 + 5 + 4 = 17 |
| 5 | :lock: G3-B1 `_secure_db_file` (db/wal/shm) | addons | 4 |
| 6 | :memo: CHANGELOG + review resolved マーク + Sprint 006 archive stub | docs | 0 |

commit ごとに `make unit` + 既存 287 PASS を維持。

---

## 影響範囲 (Rev.2 修正)

| ファイル | 変更種別 |
|---|---|
| `bundle/addons/policy_enforcer.py` | `scrub_url` / `_secure_db_file` / `_parse_content_length` 追加、`request()` hook 改修、`_init_db` / `done()` で chmod 呼出 |
| `bundle/addons/policy.py` | `check_url_secrets(url) -> tuple[bool, str]` 追加 |
| `bundle/dashboard/app.py` | `_DOMAIN_RE` strict 化 |
| `bundle/docker-compose.yml` | proxy command に `--set body_size_limit=1m` 追加 |
| `bundle/policy.toml` | `block_args` 上部コメント中立表現化 |
| `docs/user/policy-reference.md` / `.en.md` | `[tool_use_rules]` に抽象 warning 追加 |
| `docs/dev/security-notes.md` (**新設**) | block_args bypass 詳細、M-2 URL scrub の設計根拠、G3-B1 DB file 運用 |
| `CHANGELOG.md` | `[Unreleased] ### Security` (5 項目) + `### Changed` (M-5 behavior change) |
| `docs/dev/reviews/2026-04-18-comprehensive-review.md` | M-2 / M-5 / M-6 / M-7 / G3-B1 に ✅ resolved、M-8 に 「defer to PR F」注記 |
| `BACKLOG.md` | Sprint 006 に PR F (policy_lock 共通化) 追加 |

変更なし:
- `bundle/addons/policy_edit.py` (M-8 defer により `policy_lock` は現状維持)
- `bundle/addons/policy.py::PolicyEngine._load` (M-8 defer により LOCK_SH 追加なし)

---

## 受入基準 (Rev.2)

- [ ] M-2 / M-5 / M-6 / M-7 / G3-B1 の 5 項目すべて反映（M-8 は defer、注記明記）
- [ ] 新規テスト 35 件 PASS、既存 287 unit + 7 E2E P1 全 PASS
- [ ] 既存 `bundle/policy.toml` 12 domain entries が strict `_DOMAIN_RE` を全部通ることを unit test で確認
- [ ] `make unit` + `make e2e` ローカル green
- [ ] maintainer 環境で `zoo build && zoo up` 起動 + 1MB+1B request が 413 で reject されることを手動確認
- [ ] self-review (Claude subagent) 指摘 Medium 以上解消
- [ ] Gemini (3 flash preview) レビュー指摘 Medium 以上解消
- [ ] CHANGELOG `### Security` + `### Changed` + `### Added`（security-notes.md）更新
- [ ] 包括レビューの 5 項目 resolved マーク、M-8 の PR F defer 注記
- [ ] PR description に 5 項目 + M-8 defer 理由明記
- [ ] CI `unit` (3.11/3.12/3.13 matrix) + `e2e-dashboard` green
- [ ] `docs/user/policy-reference.md` と `.en.md` の内容整合性を目視レビュー
- [ ] `docs/dev/security-notes.md` が agent container mount path (`/workspace/docs/dev/`) から参照可能でも許容（dev 向け分類のため）

---

## リスク / 要検証事項 (Rev.2)

1. **Content-Length header 欠落 request** (chunked transfer encoding 等) → header が無い場合 `_parse_content_length` が None を返し、body 検査に委ねる。test で明示
2. **mitmproxy `--set body_size_limit=1m` の実挙動** — v10.x では「body を load しない (stream pass-through)」が default という認識だが、実機で 413 を返すか pass-through かは実測で確認。どちらでも addon pre-check で fail-closed できるため、設計上の堅牢性は確保
3. **IDN (Unicode domain)** — 現 regex は ASCII のみ。Punycode (`xn--`) は通るが生の Unicode は通らない。CHANGELOG に明記、将来的には `idna` ライブラリ経由で正規化する ROADMAP 項目を追加
4. **`docs/dev/security-notes.md` が agent container 内 `/workspace/docs/dev/` に見える** — agent が深いディレクトリまで読むケースは稀だが、security by obscurity に頼る設計ではない前提。本質対策は「block_args に依存せずネットワーク隔離で防御」
5. **M-8 defer による TOCTOU 残置** — 現行 atomic rename で partial read はほぼ起きない。direct overwrite fallback 経路 (bind mount で rename 失敗時) は実機で発生頻度確認済で稀。PR F で完全解決する前提で、PR D マージは許容

---

## Rollback 指針

各 commit は独立に revert 可能な構造（docs-only commit を先に、addon の security 変更を後半に配置）。
- commit 2 (M-5 strict regex) revert → dashboard UI の validation が元に戻る、他影響なし
- commit 3 (body_size_limit compose) revert → OOM 保護のみ失効、addon-side 413 は残る
- commit 4 (M-2 core) revert → URL scrub / check_url_secrets / 413 gate が全消え、M-6 の fail-closed 担保も消える（セット revert 要）
- commit 5 (G3-B1) revert → chmod が消える、独立

上記を受けて PR description の「revert 時は commit 3 と 4 はセットで」を明記。

---

## 参照

- Rev.1 → Rev.2 差分の決定根拠
  - Claude subagent review (2026-04-19、High 2 + Medium 7 + Low 8)
  - Gemini 3 flash preview review (2026-04-19、High 2 + Medium 2 + Low 2)
- 親計画: [docs/plans/2026-04-18-consolidated-work-breakdown.md](2026-04-18-consolidated-work-breakdown.md)
- 包括レビュー: [docs/dev/reviews/2026-04-18-comprehensive-review.md](../dev/reviews/2026-04-18-comprehensive-review.md)
