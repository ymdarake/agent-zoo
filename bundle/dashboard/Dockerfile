# dashboard image は agent-zoo-base:latest を継承する。
# base 側が `certs/extra/` COPY + `update-ca-certificates` + 4 つの CA env
# (SSL_CERT_FILE / REQUESTS_CA_BUNDLE / PIP_CERT / NODE_EXTRA_CA_CERTS) を
# 済ませているので、dashboard 側で corporate root CA 対応を重複実装する必要なし。
# base は node:20-slim 派生 + apt で python3 / python3-pip / python3-venv を含む。
FROM agent-zoo-base:latest

# Debian 系 system python は PEP 668 で `EXTERNALLY-MANAGED` マーク付き、
# system への `pip install` が block されるため dashboard 専用 virtualenv を
# /opt/venv に作る。PATH 先頭に venv bin を置き、以降の pip / python /
# gunicorn はこの venv 実行形を使う。
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8080

CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "1", "--threads", "2", "app:app"]
