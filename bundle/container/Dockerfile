# Claude Code agent image
# B-1: 共通 base （agent-zoo-base:latest）に Claude Code CLI を載せる。
# user/UID 固定は本ファイルで行う（base には含めない）。
#
# NOTE: `agent-zoo-base:latest` は **ローカルビルド前提** のタグ（registry push なし）。
#   ビルドには `zoo build` を使うこと（base を先にビルドする依存）。
#   直接 `docker build` するなら事前に base image をビルドする必要がある。

FROM agent-zoo-base:latest

ARG HOST_UID=1001

RUN npm install -g @anthropic-ai/claude-code

RUN useradd -m -u ${HOST_UID} claude
RUN mkdir -p /home/claude/.claude && chown claude:claude /home/claude/.claude
USER claude
