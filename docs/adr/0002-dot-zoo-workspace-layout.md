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

### D7. agent-zoo source repo の特別扱いはしない

agent-zoo 自体を dogfood する場合、user は普通の workspace と同じ手順:
1. agent-zoo を clone（= source repo）
2. `pyproject.toml` のある dir で `pip install -e .` などで開発
3. **別ディレクトリに `zoo init` で workspace を作成**して動作確認
4. agent-zoo source repo 内に `.zoo/` を作って dogfood する場合も同手順（cwd を変える）

source repo 内に直接 `.zoo/` を作ると重複 (`addons/` が source 直下と `.zoo/addons/` の 2 か所) するが、開発時は **source 直下を編集 → `.zoo/` には反映しない**運用にする（または symlink）。詳細は実装時に詰める。

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
- 既存開発者: agent-zoo source repo を pull → `pip install -e .` → 別 dir で `zoo init`

## Open / Future

- `zoo init --legacy`（旧 layout）の提供有無 — リリース前は **No**
- `.zoo/` 内の runtime artifact のさらなる細分化（`.zoo/cache/` 等）は将来検討
- agent-zoo source repo を user workspace として併用する場合の symlink 戦略

## References

- ADR 0001 [Policy Inbox](0001-policy-inbox.md) — `.zoo/inbox/` 導入の起点
- BACKLOG #28 — docs cleanup（本 ADR 実装後に docs を全面刷新する）
- 関連 issue: `.zoo/` 集約 refactor（新規起票予定）
