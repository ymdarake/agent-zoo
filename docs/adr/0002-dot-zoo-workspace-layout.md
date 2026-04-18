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

### D7. agent-zoo source repo の特別扱い（legacy layout 互換）

**配布物（zoo init された user workspace）は新 layout（`.zoo/` 配下）**だが、
**agent-zoo source repo は legacy layout（root 直下）を維持**する:

| | source repo (clone 元) | 配布物 (zoo init 後) |
|---|---|---|
| `docker-compose.yml` | root 直下 | `.zoo/` 配下 |
| `policy.toml` | root 直下 | `.zoo/` 配下 |
| `addons/`, `container/` 等 | root 直下 | `.zoo/` 配下 |
| `Makefile` | root 直下（maintainer 用に維持）| **配布しない** |
| `tests/`, `src/`, `pyproject.toml` | root 直下 | （配布対象外） |

#### 検出ロジック

`runner.workspace_root()`: cwd から walk-up で fallback 検出
1. **新 layout**: `.zoo/docker-compose.yml` 検出 → その親 dir を返す
2. **旧 layout（source repo）**: `docker-compose.yml + policy.toml` 検出 → その dir を返す

`runner.zoo_dir()`: zoo の管理ファイルがあるディレクトリ
- 新 layout: `workspace_root() / ".zoo"`
- 旧 layout: `workspace_root()` (= source repo root)

内部実装は `zoo_dir()` 経由で path 解決:
- `zoo_dir() / "certs"`, `zoo_dir() / "addons"`, `zoo_dir() / "policy.toml"` 等
- これにより、source repo / 配布物どちらでも同じコードが動作

#### `pyproject.toml` の hatch force-include

source repo の root 直下にあるファイルを、配布時には `zoo/_assets/.zoo/` 配下へ map:

```toml
[tool.hatch.build.targets.wheel.force-include]
"docker-compose.yml" = "zoo/_assets/.zoo/docker-compose.yml"
"docker-compose.strict.yml" = "zoo/_assets/.zoo/docker-compose.strict.yml"
"policy.toml" = "zoo/_assets/.zoo/policy.toml"
"container" = "zoo/_assets/.zoo/container"
"addons" = "zoo/_assets/.zoo/addons"
"dashboard" = "zoo/_assets/.zoo/dashboard"
"templates" = "zoo/_assets/.zoo/templates"
"host" = "zoo/_assets/.zoo/host"
"dns" = "zoo/_assets/.zoo/dns"
# Makefile は配布しない（maintainer 開発用）
```

`api.init()` は `_asset_source() / ".zoo"` (= `zoo/_assets/.zoo/`) 配下を読み、`target/.zoo/` 配下にコピー。

#### dogfood 開発手順

agent-zoo を clone した maintainer は **2 通り**で開発できる:
1. **source repo で直接**: `make build`, `make test`, `make run` 等の Makefile を使う（旧 layout のまま、`runner.zoo_dir() = source repo root`）
2. **別 dir で zoo init**: `pip install -e .` → 別 dir で `zoo init` → そこで新 layout を smoke 確認

両方とも `runner.workspace_root()` の fallback で動作する。symlink 等の特殊作業は不要。

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

## References

- ADR 0001 [Policy Inbox](0001-policy-inbox.md) — `.zoo/inbox/` 導入の起点
- BACKLOG #28 — docs cleanup（本 ADR 実装後に docs を全面刷新する）
- 関連 issue: `.zoo/` 集約 refactor（新規起票予定）
