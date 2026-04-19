# 包括レビュー M-3 (Sprint 006 PR E): mutable tag を sha256 digest で pin。
# multi-arch manifest list の digest（amd64 / arm64 / armv5/v7 を含む）。Dependabot
# の docker ecosystem が週次で更新 PR を出す。
FROM python:3.14-slim@sha256:bc389f7dfcb21413e72a28f491985326994795e34d2b86c8ae2f417b4e7818aa

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8080

CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "1", "--threads", "2", "app:app"]
