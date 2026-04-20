# dashboard image は agent-zoo-base:latest を継承する。
# base 側が `certs/extra/` COPY + `update-ca-certificates` + 4 つの CA env
# (SSL_CERT_FILE / REQUESTS_CA_BUNDLE / PIP_CERT / NODE_EXTRA_CA_CERTS) を
# 済ませているので、dashboard 側で corporate root CA 対応を重複実装する必要なし。
# base は node:20-slim 派生 + apt で python3 / python3-pip を含むため、ここで
# pip install / gunicorn が動く。
FROM agent-zoo-base:latest

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8080

CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "1", "--threads", "2", "app:app"]
