# ADR 0002: `.zoo/` Workspace Layout

## Status
Proposed (2026-04-18) — 実装は別 sprint

## Context

現状 `zoo init` は **workspace ルート直下** に bundled assets（`docker-compose.yml`, `policy.toml`, `Makefile`, `addons/`, `container/`, `dashboard/`, `templates/`, `host/`, `dns/`, `scripts/` 等）を展開する。これにより以下の問題:

1. **user の workspace が散らかる** — user 本来のコード（`src/`, `tests/` など）と zoo の管理ファイルが root で混在
2. **`.gitignore` が複雑化** — `data/`, `policy.runtime.toml`, `certs/`, `.zoo/inbox/` 等を個別に書く必要
3. **他ツールの設定ファイルと衝突する可能性** — 例: user の `Makefile` や `docker-compose.yml` が既に存在する場合
4. **agent-zoo 固有のファイルが目立ちすぎる** — workspace の主役が user のコードであるべき

A-3 で導入された `${WORKSPACE}/.zoo/inbox/` ディレクトリの存在で、**「すべて `.zoo/` 配下に集約する」** ほうが一貫性のある設計と判明した。

## Decision

### D1. すべての zoo 管理ファイルを `${WORKSPACE}/.zoo/` 配下に集約

```
${WORKSPACE}/
  .zoo/
    docker-compose.yml
    docker-compose.strict.yml
    policy.toml
    policy.runtime.toml
    Makefile               # zoo 開発時のみ使用、通常は zoo CLI 経由
    addons/
    container/
    dashboard/
    templates/
    host/
    dns/
    scripts/
    inbox/                 # ADR 0001
    data/                  # harness.db
    certs/                 # mitmproxy CA
  src/                     # user の本来のコード
  README.md
  .gitignore               # `.zoo/` 1 行で全 runtime artifact を除外
```

### D2. zoo CLI が CWD と `--project-directory` を吸収

user は `.zoo/` ディレクトリを意識せず、workspace root から `zoo` コマンドを叩く:

```bash
cd ${WORKSPACE}
zoo run                    # 内部で .zoo/ を --project-directory に
zoo bash                   # 同上
zoo proxy claude -p "..."  # host モード、.zoo/ 関係なし
```

### D3. docker-compose.yml の bind mount path

`.zoo/docker-compose.yml` から見た相対 path:

```yaml
services:
  claude:
    volumes:
      - ../:/workspace               # workspace root を mount
      - ./certs:/certs:ro            # .zoo/certs/
      - ./inbox:/harness/inbox       # .zoo/inbox/
      - ./policy.toml:/harness/policy.toml:ro
      - ./policy.runtime.toml:/config/policy.runtime.toml
```

`${WORKSPACE}` env 変数は不要（全て `.zoo/` 内 + `..` で完結）。

### D4. `runner.repo_root()` の意味再定義

- 現状: `docker-compose.yml` と `policy.toml` がある dir
- 新規: **`.zoo/` ディレクトリがある dir** = workspace root

CWD から walk-up して `.zoo/docker-compose.yml` を見つけたら、その親を workspace root とする。

### D5. `Makefile` の扱い

- agent-zoo **source repo の Makefile** は維持（開発者用）
- user workspace への **配布は廃止**（zoo CLI で代替）
- `Makefile` を `_BUNDLED_FILES` から削除

### D6. `templates/.gitignore` を新規追加

`zoo init` で workspace ルートに配置（既存があれば skip）:

```gitignore
# Agent Zoo runtime artifacts
.zoo/
```

たった 1 行。

### D7. source repo `bundle/` と配布先 `.zoo/` の命名分離

ユーザー判断: agent-zoo source repo 内に `.zoo/` を作ると意味が混乱するため、
**source = `bundle/`**、**配布先 = `.zoo/`** で命名を分ける。

| | source repo (clone 元) | 配布物 (zoo init 後) |
|---|---|---|
| ディレクトリ名 | `bundle/` | `.zoo/` |
| 意味 | 配布資材の置き場（maintainer が編集）| user workspace 内の harness 一式 |
| `docker-compose.yml` | `bundle/docker-compose.yml` | `.zoo/docker-compose.yml` |
| `Makefile` | **削除済** (zoo CLI 一本化、後日方針変更) | **配布しない** |
| `tests/`, `src/`, `pyproject.toml` | repo root 直下 | （配布対象外） |

#### 検出ロジック

`runner.workspace_root()`: cwd から walk-up で **`.zoo/docker-compose.yml`** を検出 → その親を返す。
`runner.zoo_dir()`: `workspace_root() / ".zoo"` を返す。

agent-zoo source repo 自身は `.zoo/` を持たない → **source repo で zoo CLI は動かない**（D7 の方針）。
maintainer は **別 dir で zoo init** する — `pip install -e .` → 別 dir で `zoo init && zoo build` → dogfood。
（当初は `cd bundle && make build` ルートも併用していたが、後日 bundle/Makefile も撤去して zoo CLI 一本化。Follow-up note 参照）

#### `pyproject.toml` の hatch force-include

source repo の `bundle/` ディレクトリを配布時には `zoo/_assets/.zoo/` 配下へ map:

```toml
[tool.hatch.build.targets.wheel.force-include]
"bundle/docker-compose.yml" = "zoo/_assets/.zoo/docker-compose.yml"
"bundle/docker-compose.strict.yml" = "zoo/_assets/.zoo/docker-compose.strict.yml"
"bundle/policy.toml" = "zoo/_assets/.zoo/policy.toml"
"bundle/container" = "zoo/_assets/.zoo/container"
"bundle/addons" = "zoo/_assets/.zoo/addons"
"bundle/dashboard" = "zoo/_assets/.zoo/dashboard"
"bundle/templates" = "zoo/_assets/.zoo/templates"
"bundle/host" = "zoo/_assets/.zoo/host"
"bundle/dns" = "zoo/_assets/.zoo/dns"
```

`api._asset_source()`:
- installed: `zoo/_assets/.zoo/` を返す
- source repo (開発時): `bundle/` を返す（= 配布物と同一構造）

`api.init()` は source から target/`.zoo/` へコピー。

### D8. policy_candidate.toml は廃止

ADR 0001 で inbox 移行済み。リリース前なので互換維持不要。
- ファイル削除
- docker-compose mount 削除
- Makefile / runner.py / api.py の touch 削除
- harness テンプレートの互換言及削除
- `scripts/migrate_candidates_to_inbox.py` も削除（リリース前なので migration 不要）
- `scripts/show_candidates.py` は inbox 用に置換または削除
- `zoo logs candidates` API も削除または `zoo logs inbox` に置換

## Consequences

### Positive
- workspace 直下が clean（`.zoo/` 1 つのみ）
- `.gitignore` 1 行で全除外
- user コードと zoo 管理ファイルの分離が明確
- 他ツールとの衝突リスク減
- A-3 の inbox path（`.zoo/inbox`）と統一感
- `.zoo/` 削除で workspace の zoo 状態を一括リセット可能

### Negative / Trade-offs
- 既存 `zoo init` 済 workspace は **新形式に migration 必要** → migration script 提供 or 「リリース前なので無視」
- bind mount path に `..` が含まれる → 起動 cwd の整合に注意（zoo CLI で吸収）
- agent-zoo source repo での開発手順が変わる（source 直下から `zoo init` した別 dir へ）

## Migration

リリース前なので **既存環境への migration は提供しない**（Sprint 002 で全面切替）。

- 新規 user: `zoo init` で `.zoo/` 構造になる
- 既存開発者: agent-zoo source repo を pull → 旧 layout のままで `make` も `zoo` CLI も動作（D7 の fallback 検出による）

## Open / Future

- `zoo init --legacy`（旧 layout）の提供有無 — リリース前は **No**
- `.zoo/` 内の runtime artifact のさらなる細分化（`.zoo/cache/` 等）は将来検討
- agent-zoo source repo を user workspace として併用する場合の symlink 戦略

## Follow-up (2026-04-18)

D5 当初は「Makefile を配布物から除外、`bundle/Makefile` は maintainer 用に維持」としていたが、
**後日 `bundle/Makefile` も完全撤去** し、Docker compose 操作は `zoo` CLI (`zoo build` / `zoo run` /
`zoo reload` / `zoo logs *` 等) に一本化した。

- `bundle/Makefile` 削除
- `api.test_smoke()` / `cli.test_smoke` は Makefile 依存のため併せて削除（同等の疎通確認は E2E P2 `tests/e2e/test_proxy_block.py` でカバー済み、再実装なし）
- maintainer の dogfood ルートは「別 dir で `zoo init` → `zoo build` → `zoo run`」の 1 通りに統一
- repo root の空 `data/` ディレクトリも同時撤去（`.zoo/data/` に集約済）

## References

- ADR 0001 [Policy Inbox](0001-policy-inbox.md) — `.zoo/inbox/` 導入の起点
- BACKLOG #28 — docs cleanup（本 ADR 実装後に docs を全面刷新する）
- 関連 issue: `.zoo/` 集約 refactor（新規起票予定）
