# Sprint 004: Docs / CI Cleanup

| 項目 | 値 |
|---|---|
| 期間 | 2026-04-19（半日） |
| テーマ | Sprint 003 完了後に残った当日作業の不整合 (H1〜H4 + M1〜M8) を 1 PR で一括修正 |
| 親計画 | [2026-04-18 統合作業ブレークダウン](../../plans/2026-04-18-consolidated-work-breakdown.md) Sprint 004 |
| Brunch | `chore/sprint-004-docs-ci-cleanup` |
| 完了 commit | (PR merge 時追記) |

---

## Sprint Goal

包括レビュー ([2026-04-18](../reviews/2026-04-18-comprehensive-review.md)) の Phase 2 指摘を、小さな修正としてまとめて片付ける。リスク低、影響小、Sprint 005 (Critical Security) 着手の地ならし。

---

## 実施項目（12 点、P004-1〜P004-11 + archive 反映）

| # | 指摘 | 内容 | 対象 |
|---|---|---|---|
| P004-1 | H1 | 削除済 `zoo.test_smoke()` API 記述除去 | `docs/dev/python-api.md` |
| P004-2 | H2 | 構造図から削除済 `Makefile` / `data/` 除去、`bundle/data` 言及も `.zoo/data` に修正 | `CLAUDE.md` |
| P004-3 | H3 | CI `e2e-proxy` で `touch bundle/policy.runtime.toml` 追加（`IsADirectoryError` 防止） | `.github/workflows/ci.yml` |
| P004-4 | H4 旧 M1 | `paths-ignore: '**.md'` → root .md 明示列挙、`HARNESS_RULES.md` を CI 対象に戻す | `.github/workflows/ci.yml` |
| P004-5 | M2 | `proxy_up` healthcheck 失敗時に `pytest.fail` + logs 添付、`up -d` 失敗時も teardown 走るよう try/finally で保護 | `tests/e2e/test_proxy_block.py` |
| P004-6 | M3 | `__import__("os")` → 通常 `import os` に整理 | `tests/e2e/test_proxy_block.py` |
| P004-7 | M4 | PR template 「CI 自動実行」と作者 manual のすれ違い解消、`bundle/dashboard/` 変更時のみ `make e2e` を promt | `.github/pull_request_template.md` |
| P004-8 | M5 | Sprint 003 archive の `<next>` placeholder を `9f78e5a` + 実 commit title に置換 | `docs/dev/sprints/003-...md` |
| P004-9 | M6 (Gemini G-1) | `ci.yml` に `workflow_dispatch: {}` 追加（手動実行可能に） | `.github/workflows/ci.yml` |
| P004-10 | M7 (Gemini G-2) | uv cache を `actions/cache@v4` 明示 key 化、Python matrix 毎に独立 | `.github/workflows/ci.yml` |
| P004-11 | M8 (Gemini G-3 / G3-A2) | root `Makefile` コメントで「`ci.yml` のエイリアス / dev / maintainer only / 配布物には含めない」を明記 | `Makefile` |
| — | Self-review H-1 / M-1 / M-3 / M-4 / L-1 / L-2 / L-3 | サブエージェント指摘の反映（CLAUDE.md 残存 `bundle/data` / e2e 2 jobs も明示 cache に統一 / fixture try block 拡張 / archive 実 title / paths-ignore コメント / restore-keys / PR template 具体条件） | 上記ファイル群 |

---

## Commit Log（4 commit）

```
b23023e :memo: docs 整合性修復: 削除済 API / 構造図 / Sprint log placeholder (P004-1, P004-2, P004-8)
ec151d7 :wrench: ci.yml: paths-ignore 明示化 + workflow_dispatch + Python 別 uv cache (P004-3, P004-4, P004-9, P004-10)
57a0c4e :white_check_mark: test_proxy_block: healthcheck 失敗時 pytest.fail + __import__ 整理 (P004-5, P004-6)
1786bd2 :art: PR template + root Makefile の責務明記 (P004-7, P004-11)
```

（self-review 反映分は merge 時の fixup commit として記録）

---

## Self-Review / Gemini Review

- Phase 1: Claude subagent review → 指摘 11 件（H-1 / M 5 / L 4 + 良かった点 7 / 修正提案 10）
  - すべて反映済（M-2 Makefile「e2e 除く」コメントは `pyproject.toml` の `norecursedirs = ["tests/e2e"]` で pytest が自動除外するため **false positive** と判定、修正なし）
- Phase 2: Gemini review → 指摘 (PR merge 前に実行予定)

---

## 検証

| 項目 | 結果 |
|---|---|
| `make unit` | 234 PASS |
| `make e2e` | 7 PASS / 4.26s |
| `make help` | 7 targets 正しく列挙 |
| `ci.yml` YAML 構文 | validated (`pyyaml`) |

---

## 学び

### paths-ignore の glob は安全寄りに

`**.md` は compact だが `bundle/templates/HARNESS_RULES.md` のような **code-adjacent .md** を skip してしまう。root 直下の .md を whitelist 列挙する方が安全。

### pytest `for...else` の正しい使い方

`for ... else` は **break しなかった場合** に else が実行される Python 独自のセマンティクス。healthcheck loop で `if healthy: break` → `else: pytest.fail` の構造が timeout 検出として自然。

### Self-review の相補性

サブエージェントが「Makefile の e2e 除く コメントが嘘」と指摘したが、pytest の `norecursedirs` 設定を知らなかったための false positive。**実装側のコンテキスト知識** と **静的な code review** の両方があると補完される例。

---

## 今後の注意点（将来作業者へ）

- **`paths-ignore` と branch protection rule の相互作用**:
  `ci.yml` は `push` to main trigger にも `paths-ignore` を設定しているため、docs-only の merge では main commit に CI status が付かない。将来 branch protection で「required status checks」を設定する場合、`paths-ignore` と衝突する可能性があるため、そのタイミングで `push` 側の `paths-ignore` を見直すか、dummy always-green job を追加する等の対応が必要。（Gemini review 指摘）
- **root 直下に新規 `.md` を追加する時**:
  `SECURITY.md` / `CONTRIBUTING.md` 等を追加した場合、`ci.yml` の `paths-ignore` に追記しない限り CI が走る。これは safe default (CI 優先)。意図的に skip したければ明示追加。
- **`pyproject.toml::norecursedirs` への依存**:
  `make unit` が e2e を除外するのは `norecursedirs = ["tests/e2e"]` 設定に依存。この設定を外すと Docker 依存の P2 test が `make unit` で走って skip される挙動になる。`make unit` / `make e2e` の責務分離を維持するには本設定を保持。

---

## 参照

- [2026-04-18 包括レビュー](../reviews/2026-04-18-comprehensive-review.md) Phase 2
- [統合作業ブレークダウン](../../plans/2026-04-18-consolidated-work-breakdown.md) Sprint 004 節
- PR: (merge 時追記)
