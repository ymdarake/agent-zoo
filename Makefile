HOST_UID := $(shell id -u)
AGENT ?= claude

ifneq ($(filter $(AGENT),claude codex),$(AGENT))
$(error AGENT must be one of: claude, codex)
endif

ifeq ($(AGENT),claude)
AGENT_REQUIRED_ENV := CLAUDE_CODE_OAUTH_TOKEN
AGENT_RUN_HINT := 対話モード: 初回はコンテナ内で /login が必要です
AGENT_RUN_CMD := docker compose exec claude claude --append-system-prompt-file /harness/CLAUDE.harness.md
AGENT_RUN_DANGEROUS_CMD := docker compose exec claude claude --dangerously-skip-permissions --append-system-prompt-file /harness/CLAUDE.harness.md
AGENT_TASK_CMD := docker compose exec claude claude -p "$(PROMPT)" --dangerously-skip-permissions --append-system-prompt-file /harness/CLAUDE.harness.md
AGENT_ALLOWED_URL := https://api.anthropic.com/
else
AGENT_REQUIRED_ENV := OPENAI_API_KEY
AGENT_RUN_HINT := 対話モード: 初回は OPENAI_API_KEY またはコンテナ内で codex login が必要です
AGENT_RUN_CMD := docker compose exec codex /usr/local/bin/run-codex.sh interactive
AGENT_RUN_DANGEROUS_CMD := docker compose exec codex /usr/local/bin/run-codex.sh interactive-dangerous
AGENT_TASK_CMD := docker compose exec -e USER_PROMPT="$(PROMPT)" codex /usr/local/bin/run-codex.sh task
AGENT_ALLOWED_URL := https://api.openai.com/
endif

# === 証明書管理 ===
certs/mitmproxy-ca-cert.pem:
	@echo "Generating mitmproxy CA certificate..."
	@docker run --rm -v $$(pwd)/certs:/certs \
		mitmproxy/mitmproxy:10 \
		sh -c "timeout 5 mitmdump --set confdir=/certs 2>&1 || true"
	@test -f certs/mitmproxy-ca-cert.pem \
		&& echo "Certificate generated: certs/mitmproxy-ca-cert.pem" \
		|| (echo "Failed to generate certificate" && exit 1)

.PHONY: certs
certs: certs/mitmproxy-ca-cert.pem

# === ビルド ===
.PHONY: build
build: certs
	HOST_UID=$(HOST_UID) docker compose build $(AGENT) dashboard

# === コンテナモード ===
.PHONY: run
run: certs
	@touch policy.runtime.toml policy_candidate.toml
	HOST_UID=$(HOST_UID) docker compose up -d $(AGENT) dashboard
	@echo "$(AGENT_RUN_HINT) (AGENT=$(AGENT), WORKSPACE=$(or $(WORKSPACE),./workspace))"
	$(AGENT_RUN_CMD)

.PHONY: run-dangerous
run-dangerous: certs
	@touch policy.runtime.toml policy_candidate.toml
	HOST_UID=$(HOST_UID) docker compose up -d $(AGENT) dashboard
	@echo "箱庭モード: 承認なし自律実行（ネットワーク隔離で保護）"
	$(AGENT_RUN_DANGEROUS_CMD)

.PHONY: task
task: certs
ifeq ($(AGENT),claude)
ifndef CLAUDE_CODE_OAUTH_TOKEN
	$(error CLAUDE_CODE_OAUTH_TOKEN is required. Usage: CLAUDE_CODE_OAUTH_TOKEN=xxx make task PROMPT="...")
endif
else
ifndef OPENAI_API_KEY
	$(error OPENAI_API_KEY is required. Usage: OPENAI_API_KEY=xxx AGENT=codex make task PROMPT="...")
endif
endif
ifndef PROMPT
	$(error PROMPT is required. Usage: $(AGENT_REQUIRED_ENV)=xxx AGENT=$(AGENT) make task PROMPT="...")
endif
	HOST_UID=$(HOST_UID) docker compose up -d $(AGENT) dashboard
	$(AGENT_TASK_CMD)

.PHONY: up
up: certs
	HOST_UID=$(HOST_UID) docker compose up -d $(AGENT) dashboard

.PHONY: up-dashboard
up-dashboard: certs
	HOST_UID=$(HOST_UID) docker compose up -d proxy dashboard

.PHONY: reload
reload:
	@rm -rf addons/__pycache__
	docker compose restart proxy dashboard
	@echo "policy.toml reloaded (cache cleared)"

.PHONY: up-strict
up-strict: certs
	HOST_UID=$(HOST_UID) docker compose --profile strict -f docker-compose.yml -f docker-compose.strict.yml up -d $(AGENT) dashboard

.PHONY: down
down:
	docker compose --profile strict -f docker-compose.yml -f docker-compose.strict.yml down 2>/dev/null || docker compose down

# === ログ管理 ===
.PHONY: clear-logs
clear-logs:
	@if [ -f data/harness.db ]; then \
		rm -f data/harness.db data/harness.db-wal data/harness.db-shm; \
		echo "Logs cleared (DB + WAL/SHM removed)"; \
	else \
		echo "No log database found"; \
	fi

# === ホストモード ===
.PHONY: host
host:
	./host/setup.sh

.PHONY: host-stop
host-stop:
	./host/stop.sh

# === テスト ===
.PHONY: unit
unit:
	uv run python -m pytest tests/ -v

.PHONY: test
test: certs
	@echo "=== Smoke Test ==="
	@mkdir -p data workspace
	HOST_UID=$(HOST_UID) docker compose up -d proxy
	@echo "Waiting for proxy to be healthy..."
	@docker compose exec proxy python3 -c "import socket; s = socket.create_connection(('localhost', 8080), timeout=10); s.close()" 2>/dev/null \
		|| sleep 5
	@echo ""
	@echo "--- Test 1: Allowed domain → expect HTTP response ---"
	@STATUS=$$(docker compose run --rm --no-deps --entrypoint="" \
		-e HTTP_PROXY=http://proxy:8080 -e HTTPS_PROXY=http://proxy:8080 \
		-e SSL_CERT_FILE=/certs/mitmproxy-ca-cert.pem \
		$(AGENT) curl -x http://proxy:8080 --cacert /certs/mitmproxy-ca-cert.pem \
		-s -o /dev/null -w "%{http_code}" $(AGENT_ALLOWED_URL) 2>/dev/null); \
	if [ "$$STATUS" -gt 0 ] 2>/dev/null; then echo "  PASS (HTTP $$STATUS)"; else echo "  FAIL (no response)"; exit 1; fi
	@echo ""
	@echo "--- Test 2: Blocked domain → expect 403 ---"
	@STATUS=$$(docker compose run --rm --no-deps --entrypoint="" \
		-e HTTP_PROXY=http://proxy:8080 -e HTTPS_PROXY=http://proxy:8080 \
		$(AGENT) curl -x http://proxy:8080 \
		-s -o /dev/null -w "%{http_code}" --connect-timeout 5 https://evil.com/ 2>/dev/null); \
	if [ "$$STATUS" = "403" ]; then echo "  PASS (403 Blocked)"; \
	elif [ "$$STATUS" = "000" ]; then echo "  PASS (connection reset)"; \
	else echo "  FAIL (unexpected: $$STATUS)"; exit 1; fi
	@echo ""
	@echo "--- Test 3: Direct access without proxy → expect failure ---"
	@docker compose run --rm --no-deps --entrypoint="" \
		-e HTTP_PROXY= -e HTTPS_PROXY= \
		$(AGENT) curl -s --connect-timeout 3 $(AGENT_ALLOWED_URL) >/dev/null 2>&1; \
	if [ $$? -ne 0 ]; then echo "  PASS (network isolated)"; else echo "  FAIL (direct access succeeded)"; exit 1; fi
	@echo ""
	@echo "--- Test 4: SQLite logs → expect ALLOWED and BLOCKED records ---"
	@docker compose exec proxy python3 -c "\
	import sqlite3, sys; \
	db = sqlite3.connect('/data/harness.db'); \
	allowed = db.execute(\"SELECT COUNT(*) FROM requests WHERE status='ALLOWED'\").fetchone()[0]; \
	blocked = db.execute(\"SELECT COUNT(*) FROM requests WHERE status IN ('BLOCKED','RATE_LIMITED','PAYLOAD_BLOCKED')\").fetchone()[0]; \
	print(f'  ALLOWED: {allowed}, BLOCKED: {blocked}'); \
	sys.exit(0 if allowed > 0 and blocked > 0 else 1)" 2>&1; \
	if [ $$? -eq 0 ]; then echo "  PASS"; else echo "  FAIL (missing log records)"; exit 1; fi
	@echo ""
	docker compose down
	@echo "=== All Smoke Tests Passed ==="

# === ログ分析（ホスト側Claude CLI利用）===
.PHONY: analyze
analyze:
	@(echo "=== ブロックログ ==="; \
	sqlite3 data/harness.db -json \
	  "SELECT host, COUNT(*) as n, GROUP_CONCAT(DISTINCT status) as statuses \
	   FROM requests WHERE status IN ('BLOCKED','RATE_LIMITED','PAYLOAD_BLOCKED') \
	   GROUP BY host ORDER BY n DESC"; \
	echo "=== 現在のpolicy.toml ==="; \
	cat policy.toml) \
	| claude -p "ブロックログとpolicy.tomlを比較して改善案をTOML形式で提案して。許可すべきドメインとその理由、危険なドメインとその理由を分けて。"

.PHONY: summarize
summarize:
	@sqlite3 data/harness.db -json \
	  "SELECT tool_name, input, input_size, ts FROM tool_uses ORDER BY ts DESC LIMIT 100" \
	| claude -p "このtool_use履歴からホストモード用settings.jsonの最小権限設定を提案して"

.PHONY: candidates
candidates:
	@echo "=== Policy Candidates ==="
	@python3 scripts/show_candidates.py
	@echo ""

.PHONY: alerts
alerts:
	@sqlite3 data/harness.db -json \
	  "SELECT * FROM alerts ORDER BY ts DESC LIMIT 50" \
	| claude -p "セキュリティ上の懸念があるパターンを報告して"
