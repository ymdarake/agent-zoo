FROM node:20-slim

ARG HOST_UID=1001

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates git sqlite3 curl \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g @anthropic-ai/claude-code

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

WORKDIR /workspace
RUN useradd -m -u ${HOST_UID} claude
USER claude
