# agent-zoo dev Makefile (repo root, dev / maintainer only)
#
# 責務: **`.github/workflows/ci.yml` と同じコマンドをローカルで再現するエイリアス**。
#
# - ローカル <-> CI の実行差異を最小化（dev 確認の信頼性を担保）
# - `PLAYWRIGHT_BROWSERS_PATH` を `.venv/playwright-browsers/` に強制 export し、
#   system / user の `~/Library/Caches/ms-playwright/` を汚染しない
# - 配布物には含めない（`.zoo/` 配下にコピーされない。user は `zoo` CLI のみを使う）
# - 配布用 Docker compose 操作は `zoo` CLI (`zoo build` / `zoo run` / `zoo reload` 等) に一本化済

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
e2e:  ## E2E P1 (dashboard + offline、Docker 不要)
	uv run pytest tests/e2e/test_dashboard.py tests/e2e/test_dashboard_offline.py -v

.PHONY: e2e-all
e2e-all:  ## E2E 全実行 (P2 は Docker daemon 必要)
	uv run pytest tests/e2e/ -v

.PHONY: test
test: unit e2e  ## unit + E2E P1

# --- リリース用 (issue #68) -----------------------------------------------

.PHONY: release
release:  ## pyproject.toml を bump → commit → tag (例: make release 0.1.0b1)。push は手動
	@[ -n "$(RELEASE_ARG)" ] || { echo "Usage: make release <VERSION>  (例: make release 0.1.0b1)" >&2; exit 1; }
	@./scripts/release-prepare.sh "$(RELEASE_ARG)"

.PHONY: release-dry-run
release-dry-run:  ## release の dry-run: format / working tree / tag 未存在を副作用なしで検証
	@[ -n "$(RELEASE_ARG)" ] || { echo "Usage: make release-dry-run <VERSION>" >&2; exit 1; }
	@./scripts/release-prepare.sh --dry-run "$(RELEASE_ARG)"

# `make release 0.1.0b1` の 2 つ目の word (`0.1.0b1`) を positional arg として拾う。
# wildcard rule `%:` は make の他 typo target も silent no-op にしてしまう副作用が
# あるため、release / release-dry-run を叩いた時だけ有効化する ifeq guard 付き。
ifneq ($(filter release release-dry-run,$(firstword $(MAKECMDGOALS))),)
    RELEASE_ARG := $(word 2,$(MAKECMDGOALS))
    # 偽 target (VERSION 文字列) を no-op で受ける
    $(eval $(RELEASE_ARG):;@:)
endif
