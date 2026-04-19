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

## 関連

- `pyproject.toml` の hatchling 設定 (`force-include` / sdist include)
- `src/zoo/api.py::_asset_source()` の installed/source 分岐
- リリースワークフロー: `.github/workflows/release.yml` (tag push で TestPyPI / PyPI に自動 publish)
