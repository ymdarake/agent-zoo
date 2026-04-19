# 包括レビュー M-3 (Sprint 006 PR E): mutable tag を sha256 digest で pin。
# multi-arch manifest list の digest（amd64 / arm64 / armv5/v7 を含む）。Dependabot
# の docker ecosystem が週次で更新 PR を出す。
FROM python:3.12-slim@sha256:804ddf3251a60bbf9c92e73b7566c40428d54d0e79d3428194edf40da6521286

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8080

CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "1", "--threads", "2", "app:app"]
