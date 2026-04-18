# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Policy Inbox** ([ADR 0001](docs/dev/adr/0001-policy-inbox.md)) — agent が必要な許可 request を `<workspace>/.zoo/inbox/<id>.toml` に submit、dashboard で accept すると `policy.runtime.toml` に自動反映 (Sprint 001)
- **`bundle/` source / `.zoo/` 配布の命名分離** ([ADR 0002](docs/dev/adr/0002-dot-zoo-workspace-layout.md)) — user workspace が clean に保たれる (Sprint 002)
- `zoo bash` — コンテナ内に対話 shell
- `zoo proxy <agent>` — host CLI に proxy 環境を注入して exec
- `zoo` CLI (typer ベース) — 全機能をサブコマンド化
- Python API (`zoo.run`, `zoo.task`, `zoo.up`, `zoo.down`, ...)
- `zoo init [DIR]` — `<DIR>/.zoo/` 配下に harness 一式を展開 + `<DIR>/.gitignore` 生成
- Gemini CLI 対応（`AGENT=gemini` / `bundle/container/Dockerfile.gemini`）
- **Unified イメージ**（`Dockerfile.unified`、cross-agent 呼び出し用、#27）
- 共通 base イメージ `agent-zoo-base:latest` と base+agent の二段ビルド
- GitHub Actions CI — pytest (Python 3.11/3.12) と CLI smoke を自動実行
- PyPI 公開用のメタデータ（classifiers, urls, license など）
- Release workflow に TestPyPI デプロイ対応 — `workflow_dispatch` の `target` 入力で `none` / `testpypi` を選択可能。本番 PyPI へのリリースは `v*.*.*` タグ push 専用とし、手動実行からの本番公開経路は塞いでいる

### Changed
- **Workspace layout を `.zoo/` 集約に移行** — `zoo init` は `<workspace>/.zoo/` 配下に展開（ADR 0002）
- docs を **`docs/user/`（利用者向け）と `docs/dev/`（開発者向け）に分離**
- Docker compose 操作を **`zoo` CLI に一本化** — Makefile は source repo / 配布物ともに含めない
- `pyproject.toml` を hatchling ビルドに切り替え、assets を `bundle/` から `zoo/_assets/.zoo/` へ map
- Release workflow に `concurrency` グループを追加し、同一 ref での重複実行を直列化

### Removed
- `bundle/Makefile` — maintainer 用の Docker compose 操作も `zoo build` / `zoo run` / `zoo reload` 等で代替（ADR 0002 D5 の最終状態）
- `zoo test smoke` コマンド — Makefile 依存だったため削除。同等の疎通確認は E2E P2 (`tests/e2e/test_proxy_block.py`) でカバー済みのため再実装しない
- `policy_candidate.toml` 経路（Sprint 002 D8）— inbox に完全移行、互換層も削除
- `docs/codex-integration.md` / `.en.md` — maintainer 用ガイドとしての役目終了
- `ROADMAP.md` / `TODO.md` — `BACKLOG.md` に集約
- repo root の空 `data/` ディレクトリ — `.zoo/data/` に集約されたため不要

## [0.1.0] - TBD

初回リリース。
