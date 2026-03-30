HOST_UID := $(shell id -u)

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
	HOST_UID=$(HOST_UID) docker compose build

# === コンテナモード ===
.PHONY: run
run: certs
ifndef ANTHROPIC_AUTH_TOKEN
	$(error ANTHROPIC_AUTH_TOKEN is required. Usage: ANTHROPIC_AUTH_TOKEN=xxx make run)
endif
	HOST_UID=$(HOST_UID) ANTHROPIC_AUTH_TOKEN=$(ANTHROPIC_AUTH_TOKEN) docker compose up -d claude
	docker compose exec claude claude

.PHONY: task
task: certs
ifndef ANTHROPIC_AUTH_TOKEN
	$(error ANTHROPIC_AUTH_TOKEN is required. Usage: ANTHROPIC_AUTH_TOKEN=xxx make task PROMPT="...")
endif
ifndef PROMPT
	$(error PROMPT is required. Usage: ANTHROPIC_AUTH_TOKEN=xxx make task PROMPT="...")
endif
	HOST_UID=$(HOST_UID) ANTHROPIC_AUTH_TOKEN=$(ANTHROPIC_AUTH_TOKEN) docker compose up -d claude
	docker compose exec claude claude -p "$(PROMPT)" --dangerously-skip-permissions

.PHONY: up
up: certs
	HOST_UID=$(HOST_UID) docker compose up -d

.PHONY: up-dashboard
up-dashboard: certs
	HOST_UID=$(HOST_UID) docker compose --profile dashboard up -d

.PHONY: up-strict
up-strict: certs
	HOST_UID=$(HOST_UID) docker compose --profile strict -f docker-compose.yml -f docker-compose.strict.yml up -d

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
		claude curl -x http://proxy:8080 --cacert /certs/mitmproxy-ca-cert.pem \
		-s -o /dev/null -w "%{http_code}" https://api.anthropic.com/ 2>/dev/null); \
	if [ "$$STATUS" -gt 0 ] 2>/dev/null; then echo "  PASS (HTTP $$STATUS)"; else echo "  FAIL (no response)"; exit 1; fi
	@echo ""
	@echo "--- Test 2: Blocked domain → expect 403 ---"
	@STATUS=$$(docker compose run --rm --no-deps --entrypoint="" \
		-e HTTP_PROXY=http://proxy:8080 -e HTTPS_PROXY=http://proxy:8080 \
		claude curl -x http://proxy:8080 \
		-s -o /dev/null -w "%{http_code}" --connect-timeout 5 https://evil.com/ 2>/dev/null); \
	if [ "$$STATUS" = "403" ]; then echo "  PASS (403 Blocked)"; \
	elif [ "$$STATUS" = "000" ]; then echo "  PASS (connection reset)"; \
	else echo "  FAIL (unexpected: $$STATUS)"; exit 1; fi
	@echo ""
	@echo "--- Test 3: Direct access without proxy → expect failure ---"
	@docker compose run --rm --no-deps --entrypoint="" \
		-e HTTP_PROXY= -e HTTPS_PROXY= \
		claude curl -s --connect-timeout 3 https://api.anthropic.com/ >/dev/null 2>&1; \
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
	@sqlite3 data/harness.db -json \
	  "SELECT host, COUNT(*) as n, GROUP_CONCAT(DISTINCT status) as statuses \
	   FROM requests WHERE status IN ('BLOCKED','RATE_LIMITED','PAYLOAD_BLOCKED') \
	   GROUP BY host ORDER BY n DESC" \
	| claude -p "ブロックログとcurrent policy.tomlを比較して改善案をTOML形式で提案して。\
	  許可すべきドメインとその理由、危険なドメインとその理由を分けて。" \
	  --file policy.toml

.PHONY: summarize
summarize:
	@sqlite3 data/harness.db -json \
	  "SELECT tool_name, input, input_size, ts FROM tool_uses ORDER BY ts DESC LIMIT 100" \
	| claude -p "このtool_use履歴からホストモード用settings.jsonの最小権限設定を提案して"

.PHONY: alerts
alerts:
	@sqlite3 data/harness.db -json \
	  "SELECT * FROM alerts ORDER BY ts DESC LIMIT 50" \
	| claude -p "セキュリティ上の懸念があるパターンを報告して"
