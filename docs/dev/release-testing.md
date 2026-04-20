# リリーステスト (wheel install での本番互換性検証)

PyPI publish 前に **editable install (`pip install -e`) ではなく wheel install** で動作確認する手順。`pyproject.toml` の `force-include` 設定漏れや、`_asset_source()` の installed branch (`zoo/_assets/.zoo/`) が正しく見えるかを実機で検証する。

## 手順

```bash
# 1. wheel ビルド
cd <agent-zoo source repo>
uv build --wheel
ls dist/                                      # agent_zoo-<version>-py3-none-any.whl

# 2. 隔離 venv で wheel install
mkdir -p /tmp/zoo-wheel-test && cd /tmp/zoo-wheel-test
python -m venv .venv
source .venv/bin/activate
pip install <agent-zoo source repo>/dist/agent_zoo-*.whl

# 3. zoo CLI が動くか
which zoo                                     # /tmp/zoo-wheel-test/.venv/bin/zoo
zoo --help

# 4. workspace を作って harness 一式が wheel から取れるか
zoo init
ls .zoo/                                      # docker-compose.yml / policy.toml / addons / dashboard / container 等
ls .zoo/dashboard/static/                     # app.css / app.js が居る (Sprint 007 PR G で追加)
ls .zoo/certs/extra/                          # .gitkeep が居る (PR #57 で追加)

# 5. build + dashboard 起動
zoo build --agent claude
zoo up --dashboard-only
curl -fsS http://127.0.0.1:8080/static/app.css | head -5
curl -fsS http://127.0.0.1:8080/ | grep -E "(meta name=\"csrf-token\"|/static/app.css|/static/app.js)"

# 6. cleanup
zoo down
deactivate
cd / && rm -rf /tmp/zoo-wheel-test
```

## 検証ポイント

| 項目 | 期待 |
|---|---|
| `_asset_source()` の installed branch | wheel 内 `zoo/_assets/.zoo/` を参照、source repo の `bundle/` には依存しない |
| `bundle/dashboard/static/{app.css,app.js}` | `pyproject.toml` の `force-include` で wheel に含まれる → `.zoo/dashboard/static/` にコピーされる |
| `bundle/certs/extra/` | wheel に含まれない (force-include 対象外) が、`zoo init` の runtime mkdir で `.zoo/certs/extra/.gitkeep` を生成 |
| `bundle/locks/` | 同様に runtime mkdir で生成 |
| Flask `app.config["ASSET_VERSION"]` + `@app.context_processor` | template の `?v=...` が gunicorn 経由でも展開される (Sprint 007 PR H 修正) |
| dashboard CSP | `Content-Security-Policy` に `'unsafe-inline'` / CDN ドメインが含まれない (Sprint 007 PR I) |
| editable と wheel の挙動差分 | 無い (両方とも `_asset_source()` の installed branch を辿るのが理想、source fallback は dev のみ) |

## よくある問題

| 症状 | 原因 / 対策 |
|---|---|
| `zoo init` で `.zoo/dashboard/static/app.{css,js}` が無い | `pyproject.toml` の `force-include` に `bundle/dashboard` が含まれているか確認 (現状含まれている) |
| `zoo build` で `COPY certs/extra/` が "not found" で fail | `zoo init` の runtime mkdir に `certs/extra/.gitkeep` 追加 (PR #57 で対応済) |
| `zoo run` で `proxy: PermissionError /certs/mitmproxy-ca.pem` | bundle/certs/ owner 不一致 (Sprint 005 PR C hardening 後)。CI / E2E P2 でのみ顕在化、wheel install では `zoo init` が dir を runtime user 所有で作るので問題なし |
| dashboard で `?v=` query が出ない | `@app.context_processor` で `asset_version` 注入されているか確認 (Sprint 007 PR H 修正) |

## 自動化

`./scripts/dogfood-dashboard.sh` は **editable install (`pip install -e`)** ベースなので、wheel install テストは現状手動。将来必要なら以下のような変種スクリプトを追加可:

- `scripts/dogfood-dashboard-wheel.sh`: dist/*.whl を install + 同じ自動検証 18 項目を実行

## beta / pre-release tag 運用 (issue #68 + 本番 PyPI 統一)

release workflow は PEP 440 **native** pre-release suffix (`a` / `b` / `rc`) 付き tag を
**本番 PyPI に publish する** (PEP 440 流儀)。stable と pre-release のルーティング差は
GitHub Release の自動作成のみ。`environment: pypi` の **required reviewers**
(public repo 前提、issue #73) が共通の人間 gate。

### ルーティング表

| tag 形式 | 例 | 本番 PyPI | GitHub Release | reviewer approval |
|---|---|---|---|---|
| stable | `v0.1.0` | ✅ | ✅ | ✅ |
| pre-release | `v0.1.0a1` / `v0.1.0b1` / `v0.1.0rc1` | ✅ | ❌ (CHANGELOG / PyPI description のみ) | ✅ |
| `workflow_dispatch` target=testpypi | (tag 非依存) | ❌ | ❌ | ❌ (TestPyPI は debug 用、approval なし) |

install 側の違い:

| version | install コマンド |
|---|---|
| stable | `pip install agent-zoo` / `uv tool install agent-zoo` |
| pre-release | `pip install --pre agent-zoo==X.Y.ZbN` / `uv tool install --prerelease=allow agent-zoo==X.Y.ZbN` |

### beta release フロー (stable 前の疎通確認)

**推奨**: `make release-commit <VERSION>` + PR + `make release-tag <VERSION>` の 2-phase
(後述 "make release-* コマンド" セクション)。以下は素の git 手順 (dogfood / 緊急時向け):

```bash
# 1. release branch で pyproject bump + commit
git checkout -b release/v0.1.0b1
vim pyproject.toml                            # version = "0.1.0b1"
git commit -am ":bookmark: release: v0.1.0b1"
git push -u origin release/v0.1.0b1
gh pr create --title ":bookmark: release: v0.1.0b1" --template release.md
# ... PR を squash merge ...

# 2. main に pull → annotated tag push
git checkout main && git pull
git tag -a v0.1.0b1 -m "Release v0.1.0b1"
git push origin v0.1.0b1

# 3. Actions 画面で `environment: pypi` の approval を与える
#    (reviewer = maintainer、prevent_self_review=false で self-approve 可)。
#    30 日以内に approve しないと run が自動 fail する点に注意。

# 4. 本番 PyPI に publish される。`--pre` 経由で疎通確認
pip install --pre agent-zoo==0.1.0b1
# or: uv tool install --prerelease=allow agent-zoo==0.1.0b1

# 5. 問題があれば PyPI 上で yank (後述)。version を bump (`0.1.0b2`) して再試行
# 6. OK なら stable version に bump して tag
vim pyproject.toml                            # version = "0.1.0"
git commit -am "bump version: 0.1.0"
git tag v0.1.0
git push origin v0.1.0                        # 本番 PyPI + GitHub Release
```

**注意事項**:

- **`pyproject.toml` と tag は常に bit-for-bit 一致** させる。build job の Verify step が
  `removeprefix("v") == project.version` で厳密比較し、不一致なら fail。正規化は意図的に
  行わない (`v0.1.0-beta-1` のような非 PEP 440 native 形は silent に `0.1.0b1` へ
  正規化されると事故になるため)。
- **leading zero 禁止** — `v0.1.0b01` は classify regex で reject。PyPI 側で `0.1.0b1` に
  正規化され、後続の `v0.1.0b1` push と衝突する事故を未然に防ぐ。
- **同一 version の再 upload 不可** — PyPI は同一 version の 2 回目 upload を reject。
  beta 毎に `b1 → b2 → ...` で bump する。yank しても同じ filename は再利用不可。
- **dynamic version (`dynamic = ["version"]`) は未対応**。Verify step が明示 error で
  fail する。hatch-vcs 等への移行が必要になった時点で workflow を拡張する。
- **pre-release は GitHub Release を自動作成しない**。release notes は CHANGELOG.md /
  PyPI project description で公開される。beta でも GitHub Release を作りたい場合は
  手動で `gh release create v<V> --prerelease --notes ...` を叩く。

### PyPI の yank / rollback

broken な release (stable / pre-release 両方) を publish してしまった場合:

1. https://pypi.org/manage/project/agent-zoo/ にログイン
2. 対象 version の "Options" → "Yank" (install 時に `pip install foo` から skip されるが、
   `==X.Y.Z` や `--pre` で明示指定すると install は可能)
3. 修正を commit し次 version に bump して再 tag (同一 version の再 upload は不可)

完全削除 (release file の delete) も同画面で可能だが、公式ドキュメントでは
"last resort to address legal issues or harmful releases" 扱い。既存 install を破壊
するので yank を優先する。

### PyPI / TestPyPI の Trusted Publisher 設定

OIDC trusted publishing は以下 4 つの claim 一致で gate する (PyPI 側に tag ref
filter は存在しない)。PyPI project 設定の "Publishing" ページで登録する:

| 項目 | 値 |
|---|---|
| Owner | `ymdarake` |
| Repository name | `agent-zoo` |
| Workflow filename | `release.yml` |
| Environment name | `pypi` (本番) / `testpypi` (debug) |

project 未作成時は **Pending publisher** として予約し、初回 publish 成功で
project 自動生成 + active publisher 昇格。tag は release.yml 側の
`on.push.tags` + build job の Classify step (PEP 440 native regex) が
gate するので、PyPI 側に別途 tag filter は不要。

**Tag レベルで追加の gate が欲しい場合**は GitHub 側の Environment protection
rule の "Deployment branches and tags" で設定可能 (本 project は未使用、
required reviewers で十分)。

### 想定外 tag が push された時の挙動

- **非 PEP 440 native (`v0.1.0-beta-1`, `v0.1.0.post1`, `vv0.1.0` 等)**: build job の
  Classify step が exit 1 で止める。本番 PyPI / GitHub Release いずれにも発火しない。
  pre-release の safety net (TestPyPI のみに逃がす) を廃止したため、**Classify の
  exit 1 が本番 PyPI 誤公開を防ぐ唯一の防衛線**。failing red build は意図的 (silent > loud)。
- **`v*.*.*` glob に偶然マッチする tag (例 `v2026.04.19`)**: 同上、Classify で明示
  reject される。workflow を通したい場合は `on.push.tags` pattern を見直す。

### TestPyPI (publish workflow デバッグ専用 annex)

TestPyPI は **publish workflow 自体の smoke test 用**に残してある
(Trusted Publisher OIDC / artifact upload 配線の動作確認)。tag push では発火せず、
`workflow_dispatch` (target=testpypi) でのみ手動発火する:

```bash
# Actions タブ → "Release to PyPI" → "Run workflow" → target=testpypi を選択
# or gh CLI:
gh workflow run release.yml -f target=testpypi

# 疎通確認 (index-url が必要):
pip install --index-url https://test.pypi.org/simple/ \
            --extra-index-url https://pypi.org/simple/ \
            --pre agent-zoo==X.Y.ZbN
```

TestPyPI は user 配布先ではない。一般 install 検証は本番 PyPI (pre-release は `--pre`) で行う。

### `make release-*` コマンド (自動化)

手動 git 手順の代替として、リポジトリ root の Makefile が 2 種類の release target を提供する:

- **branch-protected main (推奨)**: `release-commit` + `release-tag` の 2-phase (PR 経由)
- **legacy (protection 無し)**: `release` 全部入り (bump + commit + tag を一気に)

#### Phase flow (branch-protected main、PR 必須環境)

```bash
# phase 1: release branch で bump commit を作る (tag は打たない)
git checkout -b release/v0.1.1b1
make release-commit-dry-run 0.1.1b1       # 副作用なしで事前検証
make release-commit 0.1.1b1               # pyproject bump + :bookmark: commit
git push -u origin release/v0.1.1b1
gh pr create --title ":bookmark: release: v0.1.1b1" --template release.md
# ↑ .github/PULL_REQUEST_TEMPLATE/release.md に CHANGELOG / pyproject /
#   TestPyPI / PyPI / Trusted Publisher / yank 手順 checklist が入っている
# ... PR 上で checklist を確認 → squash merge ...

# phase 2: merge 後の main で HEAD に annotated tag を打って push
git checkout main && git pull
make release-tag-dry-run 0.1.1b1          # 事前検証
make release-tag 0.1.1b1                  # HEAD に annotated tag
git push origin v0.1.1b1                  # tag push → release workflow 発火
```

**`release-tag` の precondition** (script が自動 check):
- `pyproject.toml` project.version == VERSION (phase 1 の bump が merge 済であること)
- HEAD commit subject に `release: v<VERSION>` が含まれる (誤 commit に tag する事故を防止)
- HEAD == `origin/main` (orphan tag が workflow 発火 → 本番 PyPI 暴発を防止)
- local / remote に `v<VERSION>` tag が既存でない

いずれか失敗すれば fail-fast。

#### 内部処理 (`scripts/release-prepare.sh`)

1. `--no-tag` / `--tag-only` のいずれか必須 (flag 無しは usage error)
2. VERSION format check — PEP 440 native public version (release.yml classify と同一 regex)
3. working tree clean 確認
4. branch 確認 — `--tag-only` は main 必須 (non-TTY / CI env で main 以外は abort)、`--no-tag` は release branch 前提で main 以外も warn 無しで通す
5. tag `v<VERSION>` が local / remote origin で未存在であること
6. `--tag-only`: pyproject.version == VERSION + HEAD subject `release: v<VERSION>` + HEAD == origin/main の 3 precondition check → annotated tag 作成
7. `--no-tag`: `pyproject.toml` の `[project].version` を section-aware に書き換え (Python re.sub、他の `version = "..."` は誤爆しない) → tomllib read-back verify → `:bookmark: release: v<VERSION>` commit (tag は打たない)
8. 失敗 / SIGINT で `git checkout HEAD -- ./pyproject.toml` rollback
9. 次手順 (push コマンド) と undo 手順を echo

**commit prefix `:bookmark:`** は [gitmoji](https://gitmoji.dev/) の release 慣例で、本 repo の release commit 専用 prefix。`release-tag` の HEAD subject check も `release:\s*v?<VERSION>` pattern でこれを前提としている。

**push は意図的に自動化していない** — tag を公開する destructive action は maintainer の明示確認に委ねる (script の echo 通りのコマンドを手で実行)。

## 関連

- `pyproject.toml` の hatchling 設定 (`force-include` / sdist include)
- `src/zoo/api.py::_asset_source()` の installed/source 分岐
- リリースワークフロー: `.github/workflows/release.yml` (tag push で本番 PyPI に自動 publish、TestPyPI は workflow_dispatch 経由のデバッグ)
- `tests/test_release_workflow.py` (workflow yaml assertion + inline python の subprocess test)
