# Sprint 006 PR E 実装計画: サプライチェーン hardening (Rev. 2)

| 項目 | 値 |
|---|---|
| 対象 | 包括レビュー M-3 (Docker image SHA pin) / M-4 (GitHub Actions SHA pin) + Dependabot 設定 + pip-audit |
| 親計画 | [docs/plans/2026-04-18-consolidated-work-breakdown.md](2026-04-18-consolidated-work-breakdown.md) Sprint 006 PR E |
| ブランチ | `sprint-006/supply-chain-hardening` |
| 想定期間 | 半日 |
| Rev. 履歴 | Rev.1 → Rev.2 (Claude subagent + Gemini 3 flash 並行レビュー反映、High 5 + Medium 多数) |

---

## レビュー指摘反映サマリ (Rev.2)

| 指摘 | Severity | Rev.2 反映 |
|---|---|---|
| Claude H1 / Gemini #1 — `package-ecosystem: docker-compose` は実在しない | High | `docker-compose.yml` 用は `package-ecosystem: docker` + `directory: /bundle` で扱う (公式 docker ecosystem は Dockerfile と docker-compose.yml の `image:` 行両方をパース) |
| Claude H2 — docker-compose の `tag@sha256:` 書式の検証 | High | CI に `docker compose config --resolve-image-digests > /dev/null` step 追加で PR 段階で fail-fast |
| Claude H3 / Gemini #4 — pypa/gh-action-pypi-publish は branch SHA でなく tag SHA を pin | High | 検証結果: `v1.14.0` tag = `cef22109...` (= 現 release/v1 branch HEAD)。**SHA は同じ、コメントだけ `# v1.14.0` に変更** で Dependabot が tag 追跡可能に |
| Claude H4 — multi-arch manifest list 検証 | High | 検証結果: 全 4 image が `application/vnd.oci.image.index.v1+json` または `manifest.list.v2+json` で multi-arch (amd64 + arm64 等) 含む。**Apple Silicon dogfood 互換 OK**。検証コマンドを計画書 SHA セクションに記録 |
| Claude H5 — `pip-audit --strict` のセマンティクス誤解 | High | `--strict` は metadata fail を昇格するもので「warning を fail」ではない。CVE 検出は `--strict` 無しでも exit != 0。説明を修正、`--strict` は付けない方向で simplify |
| Gemini #2 — pip-audit が `bundle/dashboard/requirements.txt` (gunicorn) を見ない | Medium | `pip-audit -r bundle/dashboard/requirements.txt` を独立 step で追加 |
| Gemini #3 — npm install -g のバージョン固定漏れ | Medium | 本 PR スコープ外 (M-3 は FROM image SHA pin)。`docs/dev/security-notes.md` に「npm CLI 版固定は別 PR 候補」追記 + ROADMAP/BACKLOG 化 |
| Claude M1 — uses 行カウント不整合 | Medium | 計画書記述を「ci.yml 11 行 + release.yml 8 行 = 19 行 (6 種類のユニーク action)」に修正 |
| Claude M3 — gitmoji prefix | Medium | `:arrow_up:` で既存 commit 規約に整合、追加考察を計画書に明記 |
| Claude M4 / Gemini #6 — pip-audit version 上限明示 / uv.lock 活用 | Medium | `pip-audit>=2.7,<3` で上限明示。uv.lock activation は ROADMAP |
| Claude M5 — dependabot.yml schema validation + 回帰テスト | Medium | `tests/test_dependabot_config.py` で schema validation + Dockerfile coverage 回帰テスト 5 件 |
| Claude M7 — `tool.uv.exclude-newer` と pip-audit の鮮度衝突 | Medium | `uv tool install pip-audit` 経由で別 venv 化、本体 `dev` extras から外す |
| Claude M8 — Gemini model 指定明記 | Medium | 受入基準に `gemini-3-flash-preview` 明記 |
| Gemini #5 — Dependabot PR 重複 | Low | `groups: dependencies: patterns: ["*"]` で個別 ecosystem ごとに 1 PR にまとめる |
| Gemini #6 / Claude L2 — uv.lock + pip --require-hashes | Low | ROADMAP に追記、本 sprint scope 外 |

---

## 取得済 SHA (2026-04-19、検証済)

### Docker images (Docker Hub registry API、multi-arch manifest list 確認済)

| image | tag | digest | 確認済 manifest type | 含む arch |
|---|---|---|---|---|
| `node:20-slim` | `20-slim` | `sha256:f93745c153377ee2fbbdd6e24efcd03cd2e86d6ab1d8aa9916a3790c40313a55` | `application/vnd.oci.image.index.v1+json` | amd64, arm64 (v8), arm (v7) |
| `python:3.12-slim` | `3.12-slim` | `sha256:804ddf3251a60bbf9c92e73b7566c40428d54d0e79d3428194edf40da6521286` | `application/vnd.oci.image.index.v1+json` | amd64, arm64 (v8), arm (v5/v7) |
| `mitmproxy/mitmproxy:10` | `10` | `sha256:8ee7377e1dc2dd1b2a0083d9d07d6c3f1e48c69b53b39f8dd000581e72d74498` | `application/vnd.oci.image.index.v1+json` | amd64, arm64 |
| `coredns/coredns:1.11.4` | `1.11.4` | `sha256:4190b960ea90e017631e3e1a38eea28e98e057ab60d57d47b3db6e5cf77436f7` | `application/vnd.docker.distribution.manifest.list.v2+json` | amd64, arm64, arm v7, ppc64le, riscv64, s390x |

検証コマンド (再現用):
```bash
TOKEN=$(curl -s "https://auth.docker.io/token?service=registry.docker.io&scope=repository:library/node:pull" \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['token'])")
curl -sH "Authorization: Bearer $TOKEN" \
  -H "Accept: application/vnd.docker.distribution.manifest.list.v2+json" \
  -H "Accept: application/vnd.oci.image.index.v1+json" \
  "https://registry-1.docker.io/v2/library/node/manifests/20-slim" \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['mediaType']); [print(' ', m.get('platform')) for m in d['manifests']]"
```

### GitHub Actions (gh api で git ref → commit SHA に解決)

| action | tag | commit SHA | コメント |
|---|---|---|---|
| `actions/checkout` | `v5` | `93cb6efe18208431cddfb8368fd83d5badbf9bfd` | `# v5` |
| `astral-sh/setup-uv` | `v7` | `37802adc94f370d6bfd71619e3f0bf239e1f3b78` | `# v7` |
| `actions/cache` | `v4` | `0057852bfaa89a56745cba8c7296529d2fc39830` | `# v4` |
| `actions/upload-artifact` | `v6` | `b7c566a772e6b6bfb58ed0dc250532a479d7789f` | `# v6` |
| `actions/download-artifact` | `v7` | `37930b1c2abaa49bbe596cd826c3c89aef350131` | `# v7` |
| `pypa/gh-action-pypi-publish` | **`v1.14.0`** (←Rev.1 で `release/v1` branch ref として記載していたものと同 SHA だが tag を採用) | `cef221092ed1bacb1cc03d23a2d87d1d172e277b` | `# v1.14.0` |

**tag 採用の根拠**: `pypa/gh-action-pypi-publish` の `release/v1` branch HEAD は現状 `v1.14.0` tag と同じ commit。tag コメントにすることで Dependabot が `v1.14.1` 等の新 tag を検出して自動更新 PR を出せる (branch ref のままだと SemVer 追跡不可)。

---

## 設計判断 (Rev.2 確定)

### M-3: Docker image SHA pin

**変更**:
- `bundle/container/Dockerfile.base:13` `FROM node:20-slim` → `FROM node:20-slim@sha256:f93745c1...`
- `bundle/dashboard/Dockerfile:1` `FROM python:3.12-slim` → `FROM python:3.12-slim@sha256:804ddf32...`
- `bundle/docker-compose.yml:107` proxy `image: mitmproxy/mitmproxy:10` → `image: mitmproxy/mitmproxy:10@sha256:8ee7377e...`
- `bundle/docker-compose.yml:179` dns `image: coredns/coredns:1.11.4` → `image: coredns/coredns:1.11.4@sha256:4190b960...`

各箇所に `# Dependabot が SHA を週次更新` コメント。**Dockerfile.codex / Dockerfile.gemini / Dockerfile.unified は `FROM agent-zoo-base:latest` のみで外部 image 引かないため変更不要**。

### M-4: GitHub Actions SHA pin

**変更対象 (Rev.2 訂正後の正確なカウント)**:
- `ci.yml`: 11 `uses:` 行 (checkout x3, setup-uv x3, cache x5)
- `release.yml`: 8 `uses:` 行 (checkout x2, setup-uv x1, upload-artifact x1, download-artifact x3, pypa-publish x2)
- 合計: **19 uses 行 / 6 ユニーク action**

**形式**:
```yaml
- uses: actions/checkout@93cb6efe18208431cddfb8368fd83d5badbf9bfd  # v5
```

### Dependabot 設定 (Rev.2 改訂)

**`.github/dependabot.yml`**:
```yaml
version: 2
updates:
  # GitHub Actions: ci.yml + release.yml の uses: 19 行
  - package-ecosystem: "github-actions"
    directory: "/"
    schedule:
      interval: "weekly"
    commit-message:
      prefix: ":arrow_up:"
    labels: ["dependencies", "github-actions"]
    groups:
      gh-actions:
        patterns: ["*"]

  # Docker (Dockerfile + docker-compose.yml の `image:` 行両方を docker ecosystem
  # でカバー、Rev.2 H1 反映)
  - package-ecosystem: "docker"
    directory: "/bundle/container"  # Dockerfile.base / Dockerfile.codex / .gemini / .unified
    schedule:
      interval: "weekly"
    commit-message:
      prefix: ":arrow_up:"
    labels: ["dependencies", "docker"]
    groups:
      docker:
        patterns: ["*"]

  - package-ecosystem: "docker"
    directory: "/bundle/dashboard"  # dashboard Dockerfile
    schedule:
      interval: "weekly"
    commit-message:
      prefix: ":arrow_up:"

  - package-ecosystem: "docker"
    directory: "/bundle"  # docker-compose.yml の `image:` 行 (proxy / dns)
    schedule:
      interval: "weekly"
    commit-message:
      prefix: ":arrow_up:"

  # Python (pyproject.toml の dev / e2e extras + requirements.txt)
  - package-ecosystem: "pip"
    directory: "/"
    schedule:
      interval: "weekly"
    commit-message:
      prefix: ":arrow_up:"
    labels: ["dependencies", "python"]

  - package-ecosystem: "pip"
    directory: "/bundle/dashboard"  # gunicorn 等の requirements.txt
    schedule:
      interval: "weekly"
    commit-message:
      prefix: ":arrow_up:"
```

### pip-audit を CI に統合 (Rev.2 改訂)

**`ci.yml` の `unit` job 末尾に 2 step**:
```yaml
- name: Audit project Python dependencies (uv tool で pip-audit を分離 install)
  run: uv tool run pip-audit --vulnerability-service osv

- name: Audit dashboard requirements.txt (gunicorn 等を独立 audit)
  run: uv tool run pip-audit -r bundle/dashboard/requirements.txt --vulnerability-service osv
```

**設計判断**:
- `--strict` は付けない (Claude H5 反映、`--strict` は metadata fail を昇格するだけで CVE 検知には不要)
- `uv tool run` で pip-audit を別 venv に install し、`tool.uv.exclude-newer` の影響を回避
- `--vulnerability-service osv` で OSV.dev 併用 (Gemini #2 反映、PyPI advisory + OSV カバレッジ強化)
- `--ignore-vuln <ID>` は false positive 発生時に追加運用、`docs/dev/security-notes.md` に手順追記

### CI 検証 step (H2 対応)

**`ci.yml` の `e2e-dashboard` job または独立 job**:
```yaml
- name: Verify Docker image digests resolve
  working-directory: bundle
  run: docker compose config --resolve-image-digests > /dev/null
```

`docker compose config` は Docker daemon 不要 (parse + resolve のみ)。SHA pin が syntactically 正しいか PR 段階で fail-fast する。

---

## TDD 計画 (Rev.2)

### Test 構成

| ファイル | 対象 | 件数 |
|---|---|---|
| `tests/test_dependabot_config.py` (新規) | YAML parse / version=2 / docker ecosystem 全 Dockerfile dir 網羅 / groups 設定 / pip ecosystem requirements.txt 網羅 | 5 |

### 設計

`tests/test_dependabot_config.py`:
```python
import yaml
import pathlib

def _config():
    return yaml.safe_load(pathlib.Path(".github/dependabot.yml").read_text())

def test_version_is_2():
    assert _config()["version"] == 2

def test_all_dockerfiles_covered():
    """Dockerfile を持つ directory が全部 docker ecosystem に登録されていること
    (FROM agent-zoo-base:latest のみの内部参照は除外)"""
    config = _config()
    docker_dirs = {u["directory"].lstrip("/") for u in config["updates"]
                   if u["package-ecosystem"] == "docker"}
    # 既知の external image を引く Dockerfile dir 一覧 (将来追加されたら更新)
    expected = {"bundle/container", "bundle/dashboard", "bundle"}  # bundle = docker-compose.yml
    assert expected <= docker_dirs

def test_all_python_requirements_covered():
    config = _config()
    pip_dirs = {u["directory"].lstrip("/") for u in config["updates"]
                if u["package-ecosystem"] == "pip"}
    assert {"", "bundle/dashboard"} <= pip_dirs

def test_groups_present_for_pr_consolidation():
    config = _config()
    grouped_ecosystems = [u for u in config["updates"] if "groups" in u]
    assert len(grouped_ecosystems) >= 2  # github-actions + docker は groups で重複防止

def test_commit_message_uses_gitmoji_prefix():
    config = _config()
    for u in config["updates"]:
        prefix = u.get("commit-message", {}).get("prefix")
        if prefix is not None:
            assert prefix == ":arrow_up:"
```

---

## Commit 分割 (Rev.2)

| # | 内容 | ファイル |
|---|---|---|
| 1 | :lock: M-3 Docker image SHA pin (4 image) | `Dockerfile.base`, `dashboard/Dockerfile`, `docker-compose.yml` |
| 2 | :lock: M-4 GitHub Actions SHA pin (19 uses 行) | `.github/workflows/{ci,release}.yml` |
| 3 | :wrench: Dependabot 設定追加 + 検証 test | `.github/dependabot.yml` (新), `tests/test_dependabot_config.py` (新) |
| 4 | :wrench: CI に pip-audit + Docker compose digest 検証 step | `ci.yml` |
| 5 | :memo: docs/dev/security-notes.md に Rev.2 知見追記 (npm pin defer / pip-audit 運用) | `docs/dev/security-notes.md` |
| 6 | :memo: CHANGELOG + 包括レビュー M-3 / M-4 resolved + plan archive | `CHANGELOG.md`, review .md, `BACKLOG.md` |

各 commit 単独で revert 可能（依存なし）。

---

## 影響範囲 (Rev.2)

| ファイル | 変更種別 |
|---|---|
| `bundle/container/Dockerfile.base` | `FROM node:20-slim@sha256:...` |
| `bundle/dashboard/Dockerfile` | `FROM python:3.12-slim@sha256:...` |
| `bundle/docker-compose.yml` | proxy / dns image に `@sha256:...` |
| `.github/workflows/ci.yml` | 11 uses SHA pin + pip-audit step x2 + docker compose config 検証 step |
| `.github/workflows/release.yml` | 8 uses SHA pin |
| `.github/dependabot.yml` | 新設 |
| `tests/test_dependabot_config.py` | 新設 (5 件) |
| `docs/dev/security-notes.md` | npm CLI 版固定 / uv.lock activation / pip-audit 運用ガイド 追記 |
| `CHANGELOG.md` | `### Security` (M-3 / M-4 / Dependabot / pip-audit) |
| `docs/dev/reviews/2026-04-18-comprehensive-review.md` | M-3 / M-4 ✅ resolved |
| `BACKLOG.md` | Sprint 006 PR E 完了反映、ROADMAP に npm pin / uv.lock activation 追記 |
| `pyproject.toml` | **変更なし** (pip-audit は uv tool run で走るため `[dev]` extras に追加不要) |

---

## 受入基準 (Rev.2)

- [ ] M-3 / M-4 の SHA pin 完了 (4 image + 19 uses 行)
- [ ] `.github/dependabot.yml` が GitHub Dependabot に accept される (merge 後 GitHub UI 目視確認)
- [ ] `ci.yml` で `pip-audit` が走り、project + dashboard requirements.txt 両方を audit
- [ ] `ci.yml` で `docker compose config --resolve-image-digests` が green (SHA pin 構文正常)
- [ ] `make unit` (5 新規 test 含む) + `make e2e` ローカル green
- [ ] CI `unit` (3.11/3.12/3.13 matrix) + `e2e-dashboard` green
- [ ] post-merge `e2e-proxy` (P2) が SHA pin した images で green
- [ ] self-review: Claude subagent + Gemini (`gemini-3-flash-preview`) の両方で Medium 以上解消
- [ ] CHANGELOG `### Security` に M-3 / M-4 / Dependabot / pip-audit 4 項目
- [ ] 包括レビュー M-3 / M-4 ✅ resolved
- [ ] BACKLOG ROADMAP に npm CLI 版固定 / uv.lock activation 追記

---

## リスク / 要検証事項 (Rev.2)

1. **`pip-audit` が既存依存で fail する** — local で先行実行して既知 CVE があれば事前対応 / `--ignore-vuln` 検討
2. **`uv tool run pip-audit` が CI runner で初回 install (network 通信)** — cache 効かないため毎回 ~10 秒程度。許容範囲
3. **Dependabot の `groups` で個別 PR が出ない可能性** — group 内 patch level 更新が滞ると個別 update が遅れる。実運用で auto-merge ポリシー検討 (Sprint 008+)
4. **Dependabot PR が大量発生** — 初回 setup 直後は accumulated update PR 多数が立つ可能性。groups で 1 PR にまとまるはず
5. **PR F (M-8 LOCK_SH) との merge 順** — PR E → PR F の順を厳守。docker-compose.yml への変更がコンフリクトしうる
6. **manifest list 構成の変化** — Dependabot が新 SHA を提案したとき、その SHA も multi-arch であることを reviewer が目視確認する運用ガイドを security-notes.md に追記

---

## 参照

- 包括レビュー: [docs/dev/reviews/2026-04-18-comprehensive-review.md](../dev/reviews/2026-04-18-comprehensive-review.md) M-3 / M-4
- 親計画: [docs/plans/2026-04-18-consolidated-work-breakdown.md](2026-04-18-consolidated-work-breakdown.md) PR E
- Dependabot v2 公式: https://docs.github.com/en/code-security/dependabot/dependabot-version-updates/configuration-options-for-the-dependabot.yml-file
- Dependabot で docker-compose は `package-ecosystem: docker` でカバーされる: https://docs.github.com/en/code-security/dependabot/ecosystems-supported-by-dependabot/supported-ecosystems-and-repositories
- pip-audit `--strict` 仕様: https://pypi.org/project/pip-audit/
