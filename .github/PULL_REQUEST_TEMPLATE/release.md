## Release PR: v__VERSION__

<!-- タイトルは必ず ":bookmark: release: vX.Y.Z[abrc]N" にしてください
     (phase 2 の `release-prepare.sh --tag-only` が HEAD subject の
     `release: v<VERSION>` を fail-fast で verify するため) -->

## 種別

- [ ] stable release (`vX.Y.Z`) → 本番 PyPI + GitHub Release
- [ ] pre-release (`vX.Y.Z(a|b|rc)N`) → TestPyPI のみ

## Phase 1: この PR で必ず確認

- [ ] `pyproject.toml` の `[project].version` が tag と **bit-for-bit 一致** (例: tag `v0.1.1b1` → `version = "0.1.1b1"`)
- [ ] `CHANGELOG.md` の `[Unreleased]` section に今回の変更が反映されている (stable release なら `[X.Y.Z] - YYYY-MM-DD` に section を切り分け)
- [ ] PR タイトル / commit subject が `:bookmark: release: v<VERSION>` 形式
- [ ] CI all green (unit / E2E P1 / audit / docker digest pins)

## Phase 2: merge 後の main で実施 (忘れず!)

```bash
git checkout main && git pull
make release-tag <VERSION>         # HEAD に annotated tag、3 precondition を verify
git push origin v<VERSION>         # tag push → release workflow 発火
```

`make release-tag` は以下を fail-fast で check:
- `pyproject.version == VERSION`
- HEAD commit subject に `release: v<VERSION>` が含まれる
- HEAD == `origin/main` (orphan tag による本番 PyPI 暴発防止)

## 公開先別の確認事項

### pre-release (TestPyPI のみ)

- [ ] tag 形式は PEP 440 native (`v0.1.1b1` / `v0.1.1a1` / `v0.1.1rc1`。dash 形 `-beta-` や leading zero `b01` は reject される)
- [ ] TestPyPI は **同一 version の 2 回 upload 禁止**。broken な beta は **yank して version bump** (`b1` → `b2` → ...)
- [ ] wheel install 疎通: `pip install --index-url https://test.pypi.org/simple/ --pre agent-zoo==<VERSION>`
- [ ] docs/dev/release-testing.md の手順で本番互換性を検証 (`_asset_source()` / force-include / dashboard static 等)

### stable (本番 PyPI + GitHub Release)

- [ ] 対応する beta (`v<X>.<Y>.<Z>b*` 等) で TestPyPI 疎通確認済
- [ ] `pip install agent-zoo==<VERSION>` が publish 後に通ることを確認
- [ ] GitHub Release の auto-generated notes で release note として妥当な内容か確認

## Trusted Publisher 設定 (初回 / 新 maintainer のみ)

- [ ] PyPI / TestPyPI の "Trusted publisher" で以下が許可されているか
  - Repository: `ymdarake/agent-zoo`
  - Workflow: `release.yml`
  - Environment: `pypi` / `testpypi`
  - Tag filter: 未設定 or `v*.*.*` broad match (pre-release suffix も許可する pattern)
- [ ] 詳細: [docs/dev/release-testing.md](../../docs/dev/release-testing.md) の "PyPI / TestPyPI の Trusted Publisher 設定" section

## Rollback

TestPyPI / 本番 PyPI で問題があった場合:

- TestPyPI: https://test.pypi.org/manage/project/agent-zoo/ → 対象 version を "Yank"
- PyPI: https://pypi.org/manage/project/agent-zoo/ → 同上 (stable は慎重に)
- local の tag 削除: `git tag -d v<VERSION>`
- remote の tag 削除 (push 済の場合): `git push origin :refs/tags/v<VERSION>`

## 関連

<!-- #NN, ADR リンク、beta 版 issue 等 -->
