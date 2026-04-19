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

## beta / pre-release tag 運用 (issue #68)

release workflow は PEP 440 **native** pre-release suffix (`a` / `b` / `rc`) 付き tag を
TestPyPI 限定経路で自動処理する。`v0.1.0b1` を push → TestPyPI のみ発火、本番 PyPI と
GitHub Release は skip される。

### ルーティング表

| tag 形式 | 例 | TestPyPI | 本番 PyPI | GitHub Release |
|---|---|---|---|---|
| stable | `v0.1.0` | ❌ | ✅ | ✅ |
| pre-release | `v0.1.0a1` / `v0.1.0b1` / `v0.1.0rc1` | ✅ | ❌ | ❌ |
| `workflow_dispatch` target=testpypi | (tag 非依存) | ✅ | ❌ | ❌ |

### beta release フロー (stable 前の疎通確認)

**推奨**: `make release <VERSION>` で一括実行 (後述 "make release コマンド" セクション)。
以下は素の git 手順:

```bash
# 1. pyproject.toml の version を pre-release に bump (`0.1.0b1`)
vim pyproject.toml                            # version = "0.1.0b1"

# 2. 同じ version で tag を切って push
git commit -am ":bookmark: release: v0.1.0b1"
git tag v0.1.0b1
git push origin v0.1.0b1

# 3. TestPyPI に自動 publish される。wheel install で疎通確認
pip install --index-url https://test.pypi.org/simple/ --pre agent-zoo==0.1.0b1
# or 本手順冒頭の「手順」セクションの wheel install 検証を TestPyPI 経由で実施

# 4. 問題があれば TestPyPI 上で yank (後述)。version を bump (`0.1.0b2`) して再試行
# 5. OK なら stable version に bump して tag
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
- **同一 version の再 upload 不可** — TestPyPI / PyPI は同一 version の 2 回目 upload を
  reject。beta 毎に `b1 → b2 → ...` で bump する。
- **dynamic version (`dynamic = ["version"]`) は未対応**。Verify step が明示 error で
  fail する。hatch-vcs 等への移行が必要になった時点で workflow を拡張する。

### TestPyPI の yank / rollback

broken な beta を上げてしまった場合:

1. https://test.pypi.org/manage/project/agent-zoo/ にログイン
2. 対象 version の "Manage" → "Yank" (install 時に `--pre` + 明示 version 指定されない限り skip される)
3. 修正を commit し `b2` に bump して再 tag (同一 version の再 upload は不可)

完全削除 (release file の delete) も同画面で可能だが、既存の install を破壊するので yank を優先する。

### PyPI / TestPyPI の Trusted Publisher 設定

OIDC trusted publishing を使う場合、PyPI 側の project 設定で以下を確認:

- **Workflow filename**: `release.yml`
- **Environment**: `pypi` / `testpypi` (本 workflow で使い分け)
- **Tag pattern**: PyPI 側で tag filter を絞っている場合、pre-release suffix を含む tag
  (`v*.*.*b*` 等) も許可範囲に入れる。通常 `v*.*.*` のような broad glob で問題ない。

設定が pre-release 未許可のまま `v0.1.0b1` を push すると、`pypa/gh-action-pypi-publish`
step が認証エラーで fail する (ただし build 自体は通っているので artifact は残る)。

### 想定外 tag が push された時の挙動

- **非 PEP 440 native (`v0.1.0-beta-1`, `v0.1.0.post1`, `vv0.1.0` 等)**: build job の
  Classify step が exit 1 で止める。TestPyPI / 本番 PyPI / GitHub Release いずれにも
  発火しない。failing red build は意図的 (silent > loud)。
- **`v*.*.*` glob に偶然マッチする tag (例 `v2026.04.19`)**: 同上、Classify で明示
  reject される。workflow を通したい場合は `on.push.tags` pattern を見直す。

### `make release` コマンド (自動化)

手動 git 手順の代替として、リポジトリ root の Makefile が `release` target を提供する:

```bash
# 副作用なしの事前検証 (format / working tree / tag 未存在 / pyproject 整合)
make release-dry-run 0.1.0b1

# 本実行: pyproject.toml を bump + :bookmark: commit + v0.1.0b1 tag を local に作る
make release 0.1.0b1

# 出力に従って push (コマンドは echo される)
git push origin main --follow-tags
```

**内部処理** (`scripts/release-prepare.sh`):

1. VERSION format check — PEP 440 native public version (release.yml classify と同一 regex)
2. working tree clean 確認
3. branch 確認 — `main` 以外なら TTY prompt で confirm、非 TTY / `CI=*` 環境は abort
4. tag `v<VERSION>` 未存在確認
5. `pyproject.toml` の `[project].version` を Python で section-aware に書き換え (sed より安全)
6. `tomllib` で read-back verify (一致しなければ rollback + exit)
7. `:bookmark: release: v<VERSION>` で commit + `v<VERSION>` tag 作成 (失敗 / SIGINT で rollback)
8. 次手順 (push) と undo コマンドを echo

**commit prefix `:bookmark:`** は [gitmoji](https://gitmoji.dev/) の release 慣例で、本 repo の release commit 専用 prefix。他の gitmoji (`:sparkles:` / `:memo:` / `:arrow_up:` 等) と意味が衝突しないため release workflow の自動化で区別しやすい。

**push は意図的に自動化していない** — tag を公開する destructive action は maintainer の明示確認に委ねる (script の echo 通りのコマンドを手で実行)。

### 想定外 tag が push された時の挙動

- `pyproject.toml` の hatchling 設定 (`force-include` / sdist include)
- `src/zoo/api.py::_asset_source()` の installed/source 分岐
- リリースワークフロー: `.github/workflows/release.yml` (tag push で TestPyPI / PyPI に自動 publish)
- `tests/test_release_workflow.py` (workflow yaml assertion + inline python の subprocess test)
