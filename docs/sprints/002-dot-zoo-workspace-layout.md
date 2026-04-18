# Sprint 002: `.zoo/` Workspace Layout Refactor (#29)

| 項目 | 値 |
|---|---|
| 期間 | 2026-04-18（1 day） |
| テーマ | ADR 0002 `.zoo/` Workspace Layout の実装 + candidate 経路の完全削除 |
| 親 issue | #29 |
| 完了タスク | D1〜D8 全完了 + Self-Review 2 段階反映 |
| 残課題 | #31（user 実機 smoke）/ #28（docs 刷新） |

---

## Sprint Goal

ADR 0002 [docs/adr/0002-dot-zoo-workspace-layout.md](../adr/0002-dot-zoo-workspace-layout.md) に基づく:

1. **source repo の bundled assets を `bundle/` に集約**（root 直下散乱を解消）
2. **配布先 (zoo init された user workspace) は `.zoo/` で命名分離**
3. **後方互換削除**（リリース前のため legacy fallback 不要）
4. **`policy_candidate.toml` 経路の完全削除**（D8 先行）
5. **agent への mental model を inbox 1 経路に統一**

---

## Decisions（ADR 0002 D1〜D8）

| # | 決定 | 実装結果 |
|---|---|---|
| D1 | bundled assets を `${WORKSPACE}/.zoo/` 配下に集約 | ✅ `init()` が `target/.zoo/` に展開 |
| D2 | zoo CLI が cwd / `--project-directory` を吸収 | ✅ `compose_up` で workspace 指定時 `<ws>/.zoo/` を cwd に |
| D3 | docker-compose の bind mount は `.zoo/` 内 + `..:/workspace` で完結 | ✅ `${WORKSPACE}` env 撤去、`./inbox`, `./certs`, `../:/workspace` に統一 |
| D4 | `runner.repo_root()` を `workspace_root()` + `zoo_dir()` に分離 | ✅ `.zoo/docker-compose.yml` 検出ベース、`repo_root()` 削除 |
| D5 | Makefile を user 配布から削除 | ✅ `_BUNDLED_FILES` から削除、maintainer 用に `bundle/Makefile` のみ残す |
| D6 | `templates/.gitignore` 新規（workspace 直下用） | ✅ `src/zoo/_init_assets/workspace.gitignore` 配置（`.zoo/` 1 行で全 runtime artifact 除外）|
| D7 | source = `bundle/`、配布 = `.zoo/` の命名分離 | ✅ source repo 内に `.zoo/` を作らない、`bundle/` に集約。source 内 zoo CLI は意図的に動かない（dogfood は別 dir で `zoo init` or `cd bundle && make`） |
| D8 | `policy_candidate.toml` 廃止 | ✅ commit 2e0f49d で先行削除（リリース前のため互換不要） |

---

## 主な変更

### コア
- `src/zoo/runner.py`: `workspace_root()` / `zoo_dir()` を `lru_cache` 付き関数として分離。`repo_root()` 削除。`run()` / `run_interactive()` の cwd デフォルトを `zoo_dir()` に。`build_base()` の context も `zoo_dir()`。
- `src/zoo/api.py`:
  - `_BUNDLED_FILES` から `Makefile` 削除、`scripts` も削除
  - `init()` が `target/.zoo/` 配下に bundled をコピー、`target/.gitignore` を配置（`workspace.gitignore` template から）
  - `_asset_source()`: installed = `_assets/.zoo/`, source = `bundle/`（walk-up 検出）
  - `_init_assets_dir()`: package data + source fallback で `.gitignore` テンプレを取得
  - `logs_clear()` / `logs_analyze()` / `_pipe_to_claude()` / `reload_policy()` / `down()` / `test_smoke()` の path を `zoo_dir()` ベースに統一
- `src/zoo/__init__.py`: `logs_candidates` export 削除
- `src/zoo/cli.py`: `logs candidates` コマンド削除

### Source Repo Migration
- `git mv` で repo root → `bundle/` に集約:
  - `docker-compose.yml`, `docker-compose.strict.yml`, `policy.toml`, `Makefile`
  - `addons/`, `container/`, `dashboard/`, `templates/`, `host/`, `dns/`, `certs/`
- `bundle/docker-compose.yml`:
  - 4 agent service の bind mount を `../:/workspace` + `./inbox:/harness/inbox` + `./certs:/certs:ro` に統一
  - `${WORKSPACE}` env 依存を撤去
- `bundle/Makefile`:
  - `${WORKSPACE:-./workspace}/.zoo/inbox` → `./inbox`（cwd = bundle/ 前提）
  - `make unit` の path を `pytest ../tests/` に
  - `make candidates` ターゲット削除
- `bundle/host/setup.sh`: `srt-settings.json` → `settings.json` 誤記修正

### Packaging
- `pyproject.toml`:
  - `[tool.hatch.build.targets.wheel.force-include]` を `bundle/...` source → `zoo/_assets/.zoo/...` install へ map（Makefile 除外）
  - `[tool.hatch.build.targets.sdist].include` を `bundle/` 1 行に集約
  - `[tool.pytest.ini_options].pythonpath = ["bundle"]` 追加（test から `addons` / `dashboard` を top-level import 可能に）

### Tests
- `tests/test_zoo_init.py`: fixture を `_asset_source` の monkeypatch + workspace_root 検出用 `.zoo/` 作成に再構成
- `tests/test_zoo_api.py`: fixture を `.zoo/` 配下構造に統一、TestRepoRootDiscovery 削除、TestWorkspaceRoot 追加（new layout / walk-up / errors 3 ケース）、TestComposeUpInbox に workspace 指定時 cwd assert を 2 件追加
- `tests/test_dashboard.py` / `tests/test_policy_inbox.py`: `sys.path` を `bundle/{addons,dashboard}` に更新
- `tests/test_show_candidates.py` / `test_migrate_candidates_to_inbox.py`: 削除（D8）

### Cleanup
- `policy_candidate.toml`, `scripts/show_candidates.py`, `scripts/migrate_candidates_to_inbox.py` を削除
- `data/harness.db` 等の誤 tracked 化を rebase で修正（commit 7ce7bfa）
- `.gitignore` を `bundle/data/`, `bundle/certs/` ベースに更新（root data/, certs/ も safety net）

### Docs
- `docs/adr/0002-dot-zoo-workspace-layout.md` 新規（D1〜D8 + Migration + Open）
- ADR D7 を「source = bundle/」「配布 = `.zoo/`」「source 内 zoo CLI は動かない方針」で詳細化

---

## Self-Review

### Phase 1: Claude subagent レビュー → 検出
- **High** 5 件: `runner.run()` 等で `repo_root()` 残骸（CLI 全壊状態）、`api.logs_analyze()` / `_pipe_to_claude()` / `reload_policy()` / `down()` の path、`bundle/docker-compose.yml` unified の `${WORKSPACE}/.zoo/inbox` 残骸
- **Medium** 5 件: `bundle/Makefile` の `${WORKSPACE}` 旧形式、`compose_env(workspace)` の遺物、`api.proxy()` の cwd、docs/python-api.md `repo_root` 言及、cli.py WORKSPACE デフォルト
- **Low** 5 件: fixture 名 rename 推奨、monkeypatch 隔離 OK、`.gitignore` 互換コメント、pythonpath コメント

### Phase 2: 修正反映（commit 7ac1cbd）
- High 5 件全部、Medium 2 件（M1 Makefile, M4 docs）、Low 1 件（L4 .gitignore）

### Phase 3: Gemini レビュー → 検出
- **High** 1 件: `test_smoke` が Makefile 依存（配布物で動かない）
- **Medium** 2 件: `run --workspace <path>` 指定時 cwd 不追従、`bundle/Makefile unit` の `pytest tests/` path
- **Low** 2 件: `setup.sh` の `srt-settings.json` 誤記、`_pipe_to_claude` の sqlite3 quote（誤指摘）

### Phase 4: 修正反映（commit 249a252）
- High 1（test_smoke は docstring + ROADMAP 化）、Medium 2 全て、Low 1 件
- 誤指摘 1 件 skip

---

## Verification

| 項目 | 結果 |
|---|---|
| Unit tests | **234 PASS**（228 → 234、TestWorkspaceRoot + TestComposeUpInbox 追加分）|
| Self-Review 2 段階 | Claude + Gemini 反映済 |
| Docker smoke (`make test`) | ⏳ user 環境で要確認（#31 項目 8）|
| docs 刷新 | ⏳ #28 として次 sprint |

---

## Resolved Decisions（Sprint 002 で確定）

| 決定 | 詳細 |
|---|---|
| 後方互換不要 | リリース前のため legacy fallback 全削除（user 判断） |
| 命名分離 | source = `bundle/`、配布 = `.zoo/`（user 判断、source repo 内に `.zoo/` を作る案を撤回） |
| `policy_candidate.toml` 完全削除 | inbox 移行を完了、互換層も不要（user 判断） |
| source repo で zoo CLI は動かない | dogfood は (a) `cd bundle && make build` (b) 別 dir で `zoo init` |
| `.zoo/.gitignore` は持たない | workspace 直下の `.gitignore` で `.zoo/` 全体 ignore するため冗長（追加レビューで判明） |

---

## Commit Log（Sprint 002、9 commit）

```
249a252 :bug: #29 Phase 4 Gemini fix: workspace cwd / Makefile path / setup.sh / docstring
7ac1cbd :bug: #29 Phase 2 self-review fix: H1-H5 + M1/M4/L4
7ce7bfa :recycle: #29 Phase 3-5: source repo を bundle/ へ集約 + 配布先 .zoo/ と命名分離（rebase 済）
3eebfa0 :recycle: #29 案A: legacy fallback 削除 + .gitignore template を package data へ
45332ad :sparkles: #29 Phase 2: zoo init() を target/.zoo/ 配下展開に変更
a455668 :sparkles: #29 Phase 0+1: workspace_root/zoo_dir 分離 + .gitignore テンプレ
2e0f49d :fire: candidate 経路を完全削除（ADR 0002 D8 先行）
30b3e40 :memo: ADR 0002 .zoo/ Workspace Layout 起票 + #29 / Sprint 002 計画
```

---

## 次 sprint へ繰り越し

| # | タスク | 状態 |
|---|---|---|
| #28 | docs cleanup（zoo init 中心の設計に基づき README / docs/* を全面刷新） | ⏳ Sprint 003 候補 |
| #31 | user 実機 smoke チェックリスト（11 項目）| ⏳ user 環境で実施 |
| #3  | OpenAI exec_command 引数検知（E-2） | ⏸ 仕様確定待ち |
