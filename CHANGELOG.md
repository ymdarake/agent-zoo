# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `zoo` CLI (typer ベース) — Makefile の全機能をサブコマンド化
- Python API (`zoo.run`, `zoo.task`, `zoo.up`, `zoo.down`, ...) — import して
  使える純粋な関数 API
- `zoo init [DIR]` — パッケージ同梱の docker-compose / policy / addons 等を
  任意ディレクトリに展開
- GitHub Actions CI — pytest (Python 3.11/3.12) と CLI smoke を自動実行
- PyPI 公開用のメタデータ（classifiers, urls, license など）
- Release workflow に TestPyPI デプロイ対応 — `workflow_dispatch` の
  `target` 入力で `none` / `testpypi` / `pypi` / `both` を選択可能。
  `both` の場合は TestPyPI が成功した時のみ PyPI に公開（フェイルセーフ）。

### Changed
- `pyproject.toml` を hatchling ビルドに切り替え、assets を wheel に同梱
- Release workflow に `concurrency` グループを追加し、同一 ref での
  重複実行を直列化（走行中のリリースは中断しない）

## [0.1.0] - TBD

初回リリース。
