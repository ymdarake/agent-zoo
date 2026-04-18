# agent-zoo dev Makefile (repo root)
#
# 目的: 開発時の env 設定漏れを防ぎ、ローカル環境を汚さない。
#
# - PLAYWRIGHT_BROWSERS_PATH を `.venv/playwright-browsers/` に強制 export し、
#   system / user の `~/Library/Caches/ms-playwright/` を汚染しない仕組みにする。
# - bundle/Makefile は Docker compose 系（maintainer 用）。本ファイルとは責務が異なる。

PLAYWRIGHT_BROWSERS_PATH := $(CURDIR)/.venv/playwright-browsers
export PLAYWRIGHT_BROWSERS_PATH

.DEFAULT_GOAL := help

.PHONY: help
help:  ## このヘルプを表示
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z0-9_-]+:.*?## / {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

.PHONY: setup
setup:  ## dev + e2e extras を install
	uv sync --extra dev --extra e2e

.PHONY: e2e-install
e2e-install:  ## Playwright Chromium を .venv 配下に download (~150MB、初回のみ)
	uv run playwright install chromium

.PHONY: unit
unit:  ## ユニットテスト (tests/ 配下、e2e 除く)
	uv run python -m pytest tests/ -v

.PHONY: e2e
e2e:  ## E2E P1 (dashboard, Docker 不要)
	uv run pytest tests/e2e/test_dashboard.py -v

.PHONY: e2e-all
e2e-all:  ## E2E 全実行 (P2 は Docker daemon 必要)
	uv run pytest tests/e2e/ -v

.PHONY: test
test: unit e2e  ## unit + E2E P1
