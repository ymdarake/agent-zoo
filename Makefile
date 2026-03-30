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
	HOST_UID=$(HOST_UID) docker compose up -d claude
	docker compose exec claude claude

.PHONY: task
task: certs
ifndef PROMPT
	$(error PROMPT is required. Usage: make task PROMPT="...")
endif
	HOST_UID=$(HOST_UID) docker compose up -d claude
	docker compose exec claude claude -p "$(PROMPT)" --dangerously-skip-permissions

.PHONY: up
up: certs
	HOST_UID=$(HOST_UID) docker compose up -d

.PHONY: down
down:
	docker compose down

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
	@echo "--- Test 1: Allowed domain (expect HTTP response) ---"
	@docker compose run --rm --no-deps --entrypoint="" \
		-e HTTP_PROXY=http://proxy:8080 -e HTTPS_PROXY=http://proxy:8080 \
		-e SSL_CERT_FILE=/certs/mitmproxy-ca-cert.pem \
		claude curl -x http://proxy:8080 --cacert /certs/mitmproxy-ca-cert.pem \
		-s -o /dev/null -w "  Status: %{http_code}\n" https://api.anthropic.com/ 2>&1 || true
	@echo ""
	@echo "--- Test 2: Blocked domain (expect connection reset/error) ---"
	@docker compose run --rm --no-deps --entrypoint="" \
		-e HTTP_PROXY=http://proxy:8080 -e HTTPS_PROXY=http://proxy:8080 \
		claude curl -x http://proxy:8080 \
		-s -o /dev/null -w "  Status: %{http_code}\n" --connect-timeout 5 https://evil.com/ 2>&1 || echo "  (Blocked as expected)"
	@echo ""
	@echo "--- Test 3: Direct access without proxy (expect timeout) ---"
	@docker compose run --rm --no-deps --entrypoint="" \
		-e HTTP_PROXY= -e HTTPS_PROXY= \
		claude curl -s --connect-timeout 5 https://api.anthropic.com/ 2>&1 || echo "  (Network isolated as expected)"
	@echo ""
	@echo "--- Test 4: Check SQLite logs ---"
	@docker compose exec proxy python3 -c "import sqlite3; db = sqlite3.connect('/data/harness.db'); rows = db.execute('SELECT host, status FROM requests ORDER BY id').fetchall(); print(f'  Logged {len(rows)} requests:'); [print(f'    {r[0]} -> {r[1]}') for r in rows]; blocks = db.execute('SELECT host, reason FROM blocks').fetchall(); print(f'  Blocked {len(blocks)} requests:'); [print(f'    {b[0]}: {b[1]}') for b in blocks]" 2>&1 || true
	@echo ""
	docker compose down
	@echo "=== Smoke Test Complete ==="

# === ログ分析（ホスト側Claude CLI利用）===
.PHONY: analyze
analyze:
	@sqlite3 data/harness.db -json \
	  "SELECT host, COUNT(*) as n FROM requests WHERE status='BLOCKED' GROUP BY host ORDER BY n DESC" \
	| claude -p "ブロックログとcurrent policy.tomlを比較して改善案をTOML形式で提案して。" \
	  --file policy.toml

.PHONY: alerts
alerts:
	@sqlite3 data/harness.db -json \
	  "SELECT * FROM requests WHERE status='BLOCKED' ORDER BY ts DESC LIMIT 50" \
	| claude -p "セキュリティ上の懸念があるパターンを報告して"
