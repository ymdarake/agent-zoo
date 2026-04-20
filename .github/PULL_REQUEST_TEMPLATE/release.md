## Release PR: v__VERSION__

<!-- PR 作成時に `__VERSION__` を実際のバージョンに置換してください。
     例: gh pr create --title ":bookmark: release: v0.1.1b2" \
              --body-file <(sed 's/__VERSION__/0.1.1b2/g' .github/PULL_REQUEST_TEMPLATE/release.md)

     タイトルは必ず ":bookmark: release: vX.Y.Z[abrc]N" にしてください
     (phase 2 の `release-prepare.sh --tag-only` が HEAD subject の
     `release: v<VERSION>` を fail-fast で verify するため) -->

## 種別

- [ ] stable release (`vX.Y.Z`) → 本番 PyPI + GitHub Release
- [ ] pre-release (`vX.Y.Z(a|b|rc)N`) → 本番 PyPI (`--pre` opt-in)。GitHub Release は自動作成されない

どちらも `environment: pypi` の required reviewer approval を経由する (public repo 前提)。

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

### pre-release (本番 PyPI、`--pre` で公開)

- [ ] tag 形式は PEP 440 native (`v0.1.1b1` / `v0.1.1a1` / `v0.1.1rc1`。dash 形 `-beta-` や leading zero `b01` は reject される)
- [ ] PyPI は **同一 version の 2 回 upload 禁止**。broken な beta は **yank して version bump** (`b1` → `b2` → ...)
- [ ] wheel install 疎通: `pip install --pre agent-zoo==<VERSION>` / `uv tool install --prerelease=allow agent-zoo==<VERSION>`
- [ ] docs/dev/release-testing.md の手順で本番互換性を検証 (`_asset_source()` / force-include / dashboard static 等)
- [ ] pre-release は GitHub Release を自動作成しない。release notes を残したければ `gh release create v<V> --prerelease --notes-file ...` を手動実行

### stable (本番 PyPI + GitHub Release)

- [ ] 対応する beta (`v<X>.<Y>.<Z>b*` 等) で `--pre` install 疎通確認済
- [ ] `pip install agent-zoo==<VERSION>` が publish 後に通ることを確認 (stable は `--pre` 不要)
- [ ] GitHub Release の auto-generated notes で release note として妥当な内容か確認

## Trusted Publisher 設定 (初回 / tag pattern 変更時)

- [ ] PyPI の "Trusted publisher" で以下が許可されているか (**重要**: pre-release
      tag を発火させるので tag pattern が狭いと OIDC reject される)
  - Repository: `ymdarake/agent-zoo`
  - Workflow: `release.yml`
  - Environment: `pypi`
  - Tag filter: **`v*` or `v*.*.*` broad match** (pre-release suffix `b*` / `a*` / `rc*` を含む tag を許可)
- [ ] TestPyPI (debug 専用) の Trusted Publisher も同様に登録 (Environment: `testpypi`)
- [ ] `environment: pypi` の required reviewers が restored (public repo 前提) — issue #73
- [ ] 詳細: [docs/dev/release-testing.md](../../docs/dev/release-testing.md) の "PyPI / TestPyPI の Trusted Publisher 設定" section

## Rollback

本番 PyPI で問題があった場合:

- PyPI: https://pypi.org/manage/project/agent-zoo/ → 対象 version を "Yank"
- local の tag 削除: `git tag -d v<VERSION>`
- remote の tag 削除 (push 済の場合): `git push origin :refs/tags/v<VERSION>`
- TestPyPI (workflow_dispatch 経由で上げた場合のみ): https://test.pypi.org/manage/project/agent-zoo/

## 関連

<!-- #NN, ADR リンク、beta 版 issue 等 -->
