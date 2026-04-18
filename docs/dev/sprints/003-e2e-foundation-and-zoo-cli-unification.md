# Sprint 003: E2E Test Foundation + zoo CLI 一本化

| 項目 | 値 |
|---|---|
| 期間 | 2026-04-18（1 day） |
| テーマ | E2E テスト基盤 (P1 dashboard / P2 proxy) + 配布物の Makefile 全撤去 / zoo CLI 一本化 |
| 親 issue | #33（E2E P1/P2 実装）＋ ADR 0002 Follow-up（Makefile 撤去） |
| 完了タスク | ADR 0003 D1〜D7 + Self-Review + Gemini レビュー反映 + bundle/Makefile 撤去 |
| 残課題 | #31 user smoke（Sprint 002 から継続）、#34 E2E P3、#35 inbox helper script |

---

## Sprint Goal

Sprint 002 で `.zoo/` layout refactor を完了させた直後の後続として:

1. **E2E テスト基盤を整備**（[ADR 0003](../adr/0003-e2e-test-strategy.md)）
   - P1 dashboard UI (Docker 不要、Playwright + Flask 直起動)
   - P2 proxy ドメイン制御疎通 (Docker compose）
2. **Playwright Chromium を `.venv/` に閉じ込める** — system / user cache を汚さない
3. **`bundle/Makefile` を撤去し Docker compose 操作を `zoo` CLI に一本化**（ADR 0002 Follow-up）
4. **ローカル dev フロー改善** — repo root `Makefile` で `PLAYWRIGHT_BROWSERS_PATH` を強制 export

---

## Decisions

### ADR 0003 E2E Test Strategy（[adr/0003](../adr/0003-e2e-test-strategy.md)）

| # | 決定 | 実装結果 |
|---|---|---|
| D1 | P1 dashboard UI: Playwright + Flask 直起動、agent はモック（fixture で `inbox/*.toml` 直接配置） | ✅ `tests/e2e/test_dashboard.py` 7 件、4.3 秒 |
| D2 | P2 proxy 疎通: docker compose で proxy + claude 起動、コンテナ内 curl | ✅ `tests/e2e/test_proxy_block.py` 3 件、Docker 無い環境は自動 skip |
| D3 | P3 real agent: token + opt-in CI（#34、本 sprint では deferred） | ⏳ #34 として次フェーズ |
| D4 | Playwright browsers を `.venv/playwright-browsers/` に隔離 | ✅ `conftest.py` + repo root `Makefile` で `PLAYWRIGHT_BROWSERS_PATH` を設定 |
| D5 | agent モック戦略（P1）: 実 agent (claude/codex/gemini) を起動せず fixture で `inbox/*.toml` 再現 | ✅ `write_inbox_pending` fixture |
| D6 | ポート: OS 割当 (`_free_port`) + `_wait_port` ヘルス待ち | ✅ Flask 起動成功まで 15 秒待機、失敗時は log 吐き出し |
| D7 | DB schema 手動初期化 — `policy_enforcer.py` import できない環境でも動くよう sqlite3 で直接 CREATE | ✅ `conftest._init_db_schema` |
| D8 | CI 統合: `unit` / `e2e-dashboard` を毎 PR + main push、`e2e-proxy` を main push 時のみ | ✅ `.github/workflows/ci.yml` 新設、PR テンプレも追加 |

### ADR 0002 Follow-up（bundle/Makefile 撤去）

| # | 決定 | 実装結果 |
|---|---|---|
| F1 | `bundle/Makefile` 完全撤去、Docker compose 操作は `zoo` CLI に一本化 | ✅ `zoo build` / `zoo run` / `zoo reload` 等で代替可能 |
| F2 | `api.test_smoke()` / `zoo test smoke` も Makefile 依存のため削除 | ✅ 同等疎通は E2E P2 でカバー済、再実装なし |
| F3 | repo root の空 `data/` ディレクトリ削除（`.zoo/data/` に集約済） | ✅ `data/.gitkeep` 削除 |
| F4 | repo root `Makefile` を dev 用として新規導入（`PLAYWRIGHT_BROWSERS_PATH` を強制 export） | ✅ `setup` / `e2e-install` / `unit` / `e2e` / `e2e-all` / `test` / `help` targets |

---

## 主な変更

### E2E テスト基盤（新規）

- `tests/e2e/test_dashboard.py`: P1 dashboard UI テスト 7 件
  - root loads / empty inbox / lists pending / accept writes runtime / reject marks status / path accept / bulk accept
  - button selector を `form[hx-post*="accept"] button:has-text("許可")` に絞り bulk button と区別
- `tests/e2e/test_proxy_block.py`: P2 proxy テスト 3 件
  - Docker daemon が無い環境では自動 skip
- `tests/e2e/conftest.py`:
  - `workspace` fixture: `.zoo/` layout を tmp に生成
  - `dashboard` fixture: bundle/dashboard を Flask 直起動（`subprocess.Popen`）→ URL 返却
  - `write_inbox_pending` fixture: agent が submit した `inbox/*.toml` を再現
  - `PLAYWRIGHT_BROWSERS_PATH` を `.venv/playwright-browsers/` へ `setdefault`
- `tests/e2e/README.md`: Setup / 実行 / デバッグ手順
- `pyproject.toml`: `[e2e]` extras (`playwright>=1.40`, `pytest-playwright>=0.4`)、`norecursedirs = ["tests/e2e"]`

### repo root `Makefile`（新規）

- `PLAYWRIGHT_BROWSERS_PATH := $(CURDIR)/.venv/playwright-browsers` を export
- targets: `setup` / `e2e-install` / `unit` / `e2e` / `e2e-all` / `test` / `help`
- dev 用途に限定（配布物には含めない）

### bundle/Makefile 撤去 + zoo CLI 一本化

- `bundle/Makefile` 削除（216 行）
- `src/zoo/api.py`: `test_smoke()` 削除、`_BUNDLED_FILES` コメントから Makefile 言及除去
- `src/zoo/cli.py`: `zoo test smoke` サブコマンド削除
- `src/zoo/__init__.py`: `test_smoke` export 削除
- `tests/test_zoo_api.py`: `test_smoke` export assertion を削除
- `tests/test_zoo_init.py`: `test_makefile_is_not_distributed` docstring 更新
- `bundle/container/Dockerfile{,.base,.codex,.gemini,.unified}`: comment の `make build` → `zoo build`
- `data/.gitkeep` 削除

### ドキュメント刷新

- `README.md` / `README.en.md`: maintainer dogfood ルートを `pip install -e . && zoo init && zoo build` に統一
- `CLAUDE.md`: 開発コマンドを zoo CLI 化、「テスト・dev タスク」セクションを root Makefile 前提に
- `docs/user/install-from-package.md`: maintainer 節を zoo CLI 一本化
- `docs/user/policy-reference.md` / `.en.md`: `zoo reload` のみを記載（旧 `cd bundle && make reload` 削除）
- `docs/dev/architecture.md` / `.en.md`: Makefile 行を「無し」に
- `docs/dev/adr/0002-dot-zoo-workspace-layout.md`: Follow-up (2026-04-18) セクション追加、D5/D7 表を更新
- `docs/dev/adr/0003-e2e-test-strategy.md`: smoke test 参照を Makefile 撤去に合わせて調整
- `CHANGELOG.md`: Removed/Changed に今回の撤去を明記
- `BACKLOG.md`:
  - #28 CLOSED を反映（行削除）
  - #29 残タスクを「#31 user smoke のみ」に更新
  - #33 status を Makefile systematization 反映
  - #35 新規（inbox helper script）追加

---

## Commit Log

```
7d3101a :sparkles: E2E テスト P1+P2 実装 (ADR 0003) + Gemini レビュー反映
74d793f :bug: E2E P1 動作確認: button selector を form 単位に絞る + Chromium を .venv に閉じ込め
c36d9cb :wrench: repo root に Makefile を導入し PLAYWRIGHT_BROWSERS_PATH を強制 export
c2eb258 :fire: bundle/Makefile と repo root data/ を撤去し zoo CLI に一本化
a92c8b0 :memo: zoo test smoke 再実装を正式にやらないことを明記
b659791 :memo: Sprint 003 アーカイブ作成（本ファイル）
<next>  :sparkles: GitHub Actions ci.yml + PR テンプレ追加（#33 完了条件の最後の 1 項目）
```

---

## Self-Review / Gemini Review

- **E2E 実装フェーズ (7d3101a)**: Self-Review (Claude subagent) + Gemini Review 反映済
  - Gemini 指摘事項: `_free_port` race の注記、`policy_enforcer.py` import 可能性検証、fixture yield の cleanup 順
  - 将来追加候補を `tests/e2e/README.md` に列挙（Whitelist タブ E2E / 破損 TOML 共存 / Dedup UI 等）
- **Button selector 修正 (74d793f)**: 実機 Playwright 動作確認で bulk button との衝突が判明、form 単位 selector で解消
- **bundle/Makefile 撤去 (c2eb258)**: 型チェック 2 件 (`typing.Any` unused、`stdin.close()` 型 narrow) も合わせて修正

---

## 検証

| 項目 | 結果 |
|---|---|
| `make unit` (ユニットテスト) | **234 PASS** / 1 warning（policy_inbox 想定内） |
| `make e2e` (P1 dashboard) | **7 PASS** / 4.3 秒 |
| `make e2e-all` (P1+P2) | ⏳ P2 は Docker daemon 必要、user 実機で `#31` と同時確認 |
| `zoo test --help` (smoke 削除後) | ✅ `unit` のみ表示 |
| `.venv/playwright-browsers/` 独立 | ✅ Chromium 520 MB を system 外に格納 |

---

## 学び / 次に活かす

### Agent モック戦略の価値

ADR 0003 D5 の「P1 では実 agent を起動せず fixture で `inbox/*.toml` を直接配置」が効いた:

- **Docker 不要** → dev マシンで 4 秒で P1 完走、CI でも 1 分未満
- **確率的応答リスク無し** → flaky test ゼロ
- **Flask 直起動 (subprocess.Popen)** で dashboard の routing / HTMX / policy_inbox 書込を end-to-end に検証可能

実 agent を介さないと UI ↔ policy_inbox ↔ policy.runtime.toml の結線しか確認できないが、この結線こそが最も壊れやすい箇所だった。

### Selector の粒度

`button:has-text("許可")` のような text ベース selector は、他要素（bulk 一括許可ボタン）と衝突しやすい。`form[hx-post*="accept"] button:has-text("許可")` のように **form 単位に絞る** 形が安定する。HTMX の属性 (`hx-post="..../accept"`) を selector のアンカーに使うのが良い。

### Makefile 撤去の判断基準

当初 ADR 0002 D5 では「Makefile を配布物から除外、maintainer 用に bundle/Makefile は残す」としていたが、Sprint 003 で評価し直して **完全撤去に踏み切った** 理由:

- zoo CLI がすでに全 compose 操作をカバーしていた（`zoo build` / `zoo run` / `zoo reload` / `zoo logs *`）
- maintainer も結局「dogfood workspace で `zoo init` → `zoo build`」ルートのほうを使っていた
- `api.test_smoke()` が Makefile 依存だったが、E2E P2 が同等カバレッジを提供するため不要

**判断基準**: 「同等機能を担う上位ルートが既に動いている」+「下位ルートの利用者が事実上 0」+「削除で理解コスト低下」の 3 条件が揃った時点で遠慮なく撤去する。

### Playwright browsers containment

`PLAYWRIGHT_BROWSERS_PATH` を `.venv/playwright-browsers/` に固定する手段を 2 箇所に張る設計にした:

1. `conftest.py`: `os.environ.setdefault(...)` — pytest 実行時の fallback
2. repo root `Makefile`: `export PLAYWRIGHT_BROWSERS_PATH := $(CURDIR)/.venv/...` — `make e2e-install` / `make e2e` 経由の強制

これで「素の `playwright install chromium` を叩く」以外の全ルートで system cache を汚染しない。520 MB の binary を `.venv/` にまとめる = `rm -rf .venv` で完全クリーンアップ可能、という単純な衛生性が得られた。

---

## 参照

- ADR 0003 [E2E Test Strategy](../adr/0003-e2e-test-strategy.md)
- ADR 0002 [.zoo/ Workspace Layout](../adr/0002-dot-zoo-workspace-layout.md) — Follow-up (2026-04-18)
- Sprint 002 [dot-zoo-workspace-layout](002-dot-zoo-workspace-layout.md) — 前提となる layout refactor
- 元 issue #33 E2E P1/P2、#34 E2E P3（deferred）、#35 inbox helper script（新規）
