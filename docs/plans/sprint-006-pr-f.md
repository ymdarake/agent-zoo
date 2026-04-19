# Sprint 006 PR F 実装計画: policy_lock cross-container 共通化 (M-8) (Rev. 2)

| 項目 | 値 |
|---|---|
| 対象 | 包括レビュー M-8 (policy.toml TOCTOU 競合)、PR D で defer されたもの |
| 親計画 | [docs/plans/2026-04-18-consolidated-work-breakdown.md](2026-04-18-consolidated-work-breakdown.md) Sprint 006 PR F |
| ブランチ | `sprint-006/policy-lock-shared` |
| 想定期間 | 半日〜1 日 |
| Rev. 履歴 | Rev.1 → Rev.2 (Claude subagent + Gemini 3 flash 並行レビュー反映、High 3 + Medium 6) |

---

## Rev.2 反映サマリ

| 指摘 | Severity | Rev.2 反映 |
|---|---|---|
| Claude H1 / Gemini #2 — silent passthrough は ADR 0005 と矛盾 | High | reader = `warn` (passthrough)、writer = `raise` の API 分離 (`policy_lock_shared` warn / `policy_lock_exclusive` raise) |
| Claude H2 / Gemini #3 — `zoo init` で `.zoo/locks/` 生成欠落 + `bundle/locks/.gitkeep` 不在で配布物動作不能 | High | `src/zoo/api.py::init` に `"locks"` 追加 + `bundle/locks/.gitkeep` 配置 + `.gitignore` を `bundle/locks/*` + `!bundle/locks/.gitkeep` パターンに |
| Claude H3 — CI E2E P2 で `bundle/locks/` 不在で proxy 起動失敗 | High | `tests/e2e/test_proxy_block.py::proxy_up` + `.github/workflows/ci.yml::e2e-proxy` に locks dir mkdir 追加 |
| Claude M1 / Gemini #4 — base policy.toml への LOCK_SH 不要 | Medium | runtime のみ lock。base は writer 不在のため LOCK_SH 削除 (overhead カット) |
| Claude M2 — `bundle/locks/.gitkeep` track 戦略 | Medium | `bundle/certs/` 前例に従い `bundle/locks/.gitkeep` track + `.gitignore` 例外パターン |
| Claude M3 — tempdir fallback の symlink 攻撃面 | Medium | `os.open(lock_path, O_RDWR \| O_CREAT \| O_NOFOLLOW, 0o600)` で symlink 抑止 |
| Claude M4 — `policy_edit.policy_lock` 1 line alias 化 | Medium | `from _policy_lock import policy_lock_exclusive as policy_lock` の 1 行委譲確定 |
| Claude M5 / Gemini #5 — lock failure 時 reader/writer test 分離 + flaky 防止 | Medium | `test_shared_lock_failure_warns_and_passes` / `test_exclusive_lock_failure_raises` の 2 件に分離。subprocess は `multiprocessing.Event` で同期 |
| Claude M6 — `_load` コード片精度 | Medium | M1 反映で runtime のみ wrap、既存 try/except を保ったまま |
| Gemini #1 — macOS Docker Desktop の VirtioFS で flock cross-VM 効かない可能性 | High | host-mode は scope 外。container-mode (proxy + dashboard 同 VM) では同一 kernel で flock 効く前提を `docs/dev/security-notes.md` に明記 |
| Claude L1〜L5 / Gemini Low — env docs / strict.yml / cleanup 等 | Low | docs commit にまとめて反映 |

---

## 背景: PR D で defer された理由

PR D Rev.2 plan review で発覚した破綻点:
1. proxy container は `bundle/docker-compose.yml` で `./policy.runtime.toml:/config/policy.runtime.toml:ro` で **ro mount**
2. 既存 `policy_edit.py::policy_lock` は `lock_path = f"{os.path.abspath(policy_path)}.lock"` → 同じ ro path に lock file を書こうとする
3. proxy 側で `open("/config/policy.runtime.toml.lock", "w")` が EROFS / EACCES → fail-closed (旧 policy 保持) に流れ、reload 機能が silent に死ぬ

PR F はこれを解決する独立 PR。

---

## 設計

### `bundle/addons/_policy_lock.py` 新設

mitmproxy / Flask 非依存の pure module。proxy / dashboard 両方から import。

**API (Rev.2)**:
```python
def lock_path_for(policy_path: str) -> str:
    """policy file 用の lock file path を共有 lock dir 配下にマップ。
    POLICY_LOCK_DIR env (default: /locks) を base に basename + ".lock"。
    Fallback 順: env dir → <policy_path>.lock → tempdir。
    """

@contextmanager
def policy_lock_shared(policy_path: str):
    """LOCK_SH (read 用 shared lock) を取得。reader (PolicyEnforcer._load) 用。

    Rev.2 (self-review H1): lock 取得失敗時は logger.warning で観測可能化した上で
    passthrough。reader は ADR 0005 fail-closed 原則と両立する best-effort 動作。
    """

@contextmanager
def policy_lock_exclusive(policy_path: str):
    """LOCK_EX (write 用 exclusive lock) を取得。writer (policy_edit.py) 用。

    Rev.2 (self-review H1): lock 取得失敗時は OSError を raise (fail-closed)。
    writer の失敗は「ユーザー操作 (whitelist accept) が無音で失敗」を意味するため、
    UI 側で 503 を返して retry できるようにする。inbox bulk-accept の partial
    書き込みも防ぐ。
    """
```

**実装方針**:
- lock dir 解決 (3 段 fallback):
  1. `POLICY_LOCK_DIR` env を読む (default `/locks`)
  2. dir が exist & writable なら `<dir>/<basename(policy_path)>.lock`
  3. dir が無い or 書き込めない → `<policy_path>.lock` (既存挙動互換、host-mode fallback)
  4. 全部失敗したら `tempfile.gettempdir()` 配下に `agent_zoo_<basename>.lock`
- lock file open は `os.open(lock_path, O_RDWR | O_CREAT | O_NOFOLLOW, 0o600)` で **symlink follow 抑止 + 600 強制** (Rev.2 self-review M3)
- reader (`policy_lock_shared`): lock acquire 失敗時 `logger.warning` + passthrough
- writer (`policy_lock_exclusive`): lock acquire 失敗時 `OSError` raise

**macOS Docker Desktop 制約 (Gemini #1)**: VirtioFS / gRPC FUSE 経由で host ↔ Linux VM 間の flock は協調しない可能性がある。本実装は **container-mode (proxy + dashboard が同一 Docker VM 内)** を前提とし、cross-VM (host-mode) lock 協調は scope 外。詳細は `docs/dev/security-notes.md` に明記。

### docker-compose.yml に locks bind mount

```yaml
services:
  proxy:
    volumes:
      - ./locks:/locks  # M-8 PR F: cross-container policy lock 共有
      ...

  dashboard:
    volumes:
      - ./locks:/locks  # M-8 PR F
      ...
```

`./locks/` は host 側に作成 (空 dir)。`.gitignore` 追記。

### 既存 policy_edit.py の移行 (Rev.2 確定: 1 line alias)

```python
# bundle/addons/policy_edit.py の旧定義 (`policy_lock`) を削除し、import で alias
from _policy_lock import policy_lock_exclusive as policy_lock
```

6 callsite (`add_to_allow_list` 等) はそのまま動く (writer = LOCK_EX、Rev.1 と同じセマンティクス)。`tests/test_policy_edit.py::TestFileLock` の既存 3 ケースが alias の互換性を担保。

**注意**: 既存 `test_lock_file_created` が `os.path.abspath(rt_path) + ".lock"` の存在を assert している (`tests/test_policy_edit.py:305-312`)。新 helper では lock file が `/locks` (env 設定時) や tempdir に移るため、テストの assertion を `lock_path_for(rt_path)` の return path 検証に書き換える (commit 2 内で対応)。

### policy.py::PolicyEngine._load に LOCK_SH (Rev.2 確定: runtime のみ)

base policy への LOCK_SH は不要 (writer 不在、Rev.2 M1 反映)。runtime のみ wrap:

```python
from _policy_lock import policy_lock_shared

def _load(self):
    # base policy.toml は writer 不在 (dashboard は runtime のみ書く) のため lock 不要
    with open(self.policy_path, "rb") as f:
        policy = tomllib.load(f)
    self._mtime = self.policy_path.stat().st_mtime

    runtime_path = Path(str(self.policy_path).replace(".toml", ".runtime.toml"))
    runtime = {}
    if runtime_path.exists():
        try:
            # cross-container shared lock (M-8 PR F)。失敗時は warn+passthrough
            # (reader は best-effort、ADR 0005 fail-closed と両立)
            with policy_lock_shared(str(runtime_path)):
                with open(runtime_path, "rb") as f:
                    runtime = tomllib.load(f)
            self._runtime_mtime = runtime_path.stat().st_mtime
        except Exception as e:
            logger.warning(f"Failed to load runtime policy: {e}")
    ...
```

`policy_lock_shared` 自身が失敗時 raise しない (warn + passthrough) ので、`with` 文の中で正常に open() されることが保証される。except 経路は file open / TOML parse 失敗のみ受ける。

---

## TDD 計画

### 新規 test: `tests/test_policy_lock.py`

| ケース | 内容 |
|---|---|
| `test_lock_path_for_writable_dir` | `POLICY_LOCK_DIR=/tmp/test-locks` に dir 作成 → `lock_path_for("/etc/policy.toml")` が `/tmp/test-locks/policy.toml.lock` |
| `test_lock_path_for_missing_dir_fallback` | `POLICY_LOCK_DIR=/nonexistent` → fallback で `<policy_path>.lock` |
| `test_lock_path_for_unwritable_dir_fallback` | dir はあるが書けない (mock) → tempdir fallback |
| `test_shared_lock_acquired` | `policy_lock_shared` が context manager として動く、lock file が生成される |
| `test_exclusive_lock_acquired` | `policy_lock_exclusive` が同様 |
| `test_concurrent_shared_locks` | shared lock は複数同時取得可能 |
| `test_exclusive_blocks_shared` | exclusive lock 中は shared lock が待つ (subprocess で動作確認) |
| `test_lock_failure_silent_passthrough` | lock 取得不能環境 (mock OSError) でも with 文は通る (silent) |

### 既存 test の影響

`tests/test_policy_edit.py` が `policy_lock` を使っているか確認 → 動作を保つ。

`tests/test_policy.py` の PolicyEngine 系 test は `_policy_lock` import path に依存しないので影響なし。

---

## Commit 分割

| # | 内容 | ファイル |
|---|---|---|
| 1 | :sparkles: `_policy_lock` module 新設 + test | `bundle/addons/_policy_lock.py` (新), `tests/test_policy_lock.py` (新) |
| 2 | :recycle: `policy_edit.policy_lock` を `_policy_lock` 経由に移行 | `policy_edit.py` |
| 3 | :lock: `PolicyEngine._load` に LOCK_SH 追加 | `policy.py` |
| 4 | :wrench: docker-compose.yml に `./locks:/locks` mount + .gitignore | `docker-compose.yml`, `.gitignore` |
| 5 | :memo: CHANGELOG + 包括レビュー M-8 resolved + Sprint 006 archive | docs |

---

## 影響範囲

| ファイル | 変更種別 |
|---|---|
| `bundle/addons/_policy_lock.py` | 新設 (~100 LOC) |
| `bundle/addons/policy_edit.py` | `policy_lock` を `from _policy_lock import policy_lock_exclusive as policy_lock` に置換 |
| `bundle/addons/policy.py` | `_load` の runtime 読込のみ LOCK_SH wrap |
| `bundle/docker-compose.yml` | proxy / dashboard に `./locks:/locks` 追加 (dns は不要) |
| `bundle/docker-compose.strict.yml` | 既存 override 確認、必要なら locks mount 追加 |
| `bundle/locks/.gitkeep` | 新設 (空 dir を git track、`bundle/certs/.gitkeep` 前例) |
| `.gitignore` | `bundle/locks/*` + `!bundle/locks/.gitkeep` パターン |
| `src/zoo/api.py` | `init()` の runtime dirs リストに `"locks"` 追加 |
| `tests/test_policy_lock.py` | 新設 (~10 件) |
| `tests/test_policy_edit.py` | `test_lock_file_created` の assertion 修正 (lock_path_for 経由) |
| `tests/test_zoo_init.py` | `.zoo/locks/` が `init()` で生成されることの test 追加 |
| `tests/e2e/test_proxy_block.py` | `proxy_up` fixture で `bundle/locks/` mkdir 追加 |
| `.github/workflows/ci.yml` | `e2e-proxy` job の `Prepare runtime policy` step に `mkdir -p bundle/locks` |
| `CHANGELOG.md` | `### Security` (M-8) |
| `docs/dev/reviews/2026-04-18-comprehensive-review.md` | M-8 ✅ resolved |
| `docs/dev/security-notes.md` | "policy_lock の cross-container 協調" 節を「実装済」に更新 + macOS Docker Desktop の cross-VM flock 制約注記 |
| `docs/user/policy-reference.md` | `POLICY_LOCK_DIR` env の説明追加 |
| `BACKLOG.md` | Sprint 006 PR F ✅ → Sprint 006 完了 |

---

## 受入基準

- [ ] `_policy_lock` 新設、`policy_edit.policy_lock` が thin wrapper 化
- [ ] `PolicyEngine._load` で LOCK_SH 取得
- [ ] docker-compose.yml で proxy / dashboard に `./locks:/locks` mount
- [ ] 新規 test 8 件 PASS
- [ ] 既存 371 unit + 7 e2e-dashboard 全 PASS
- [ ] post-merge `e2e-proxy` (P2) で proxy が `/locks` mount 経由で正常起動
- [ ] self-review (Claude subagent + Gemini gemini-3-flash-preview) Medium 以上解消
- [ ] CHANGELOG `### Security`、包括レビュー M-8 ✅ resolved
- [ ] Sprint 006 全 3 PR (D / E / F) 完了 → Sprint 006 archive 作成

---

## リスク / 要検証事項

1. **`/locks` dir が host 側に存在しないと bind mount で proxy 起動失敗** — `zoo init` で `.zoo/locks/` を作る、または `.gitkeep` 配置で対応
2. **silent fallback で lock がほぼ機能しないケース** — `/locks` dir 存在検証を起動時に行い info log で報告
3. **既存 `policy_lock` の callsite 6 箇所が thin wrapper で transparent に動くか** — wrapper 経由で sleep/timeout 等の挙動変更が無いことを `tests/test_policy_edit.py` 既存 test 全 PASS で担保
4. **base policy.toml への LOCK_SH の overhead** — base は通常変更されないので lock contention は皆無、無視可
5. **CI E2E P2 で proxy が `/locks` mount 不在で起動する可能性** — `tests/e2e/test_proxy_block.py::proxy_up` fixture で `bundle/locks/` を事前 touch する必要があるか確認

---

## 参照

- 包括レビュー: M-8 (`docs/dev/reviews/2026-04-18-comprehensive-review.md`)
- PR D 計画書 H1 deferred 理由: `docs/plans/sprint-006-pr-d.md`
- 親計画 PR F: `docs/plans/2026-04-18-consolidated-work-breakdown.md`
