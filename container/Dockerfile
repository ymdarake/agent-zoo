# Claude Code agent image
# B-1: 共通 base （agent-zoo-base:latest）に Claude Code CLI を載せる。
# user/UID 固定は本ファイルで行う（base には含めない）。

FROM agent-zoo-base:latest

ARG HOST_UID=1001

RUN npm install -g @anthropic-ai/claude-code

RUN useradd -m -u ${HOST_UID} claude
RUN mkdir -p /home/claude/.claude && chown claude:claude /home/claude/.claude
USER claude
