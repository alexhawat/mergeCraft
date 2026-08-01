# SPDX-License-Identifier: MIT
# Production Action image for mergeCraft (standalone BYOK runtime).
FROM python:3.14-slim-bookworm

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/mergecraft/.venv/bin:${PATH}" \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1

# The action runs as root in an ephemeral CI container; Claude Code treats this
# as a sandbox context. Scoped to the image, so local `mergecraft diff-review`
# (non-root) is unaffected.
ENV IS_SANDBOX=1

RUN apt-get update -qq \
    && apt-get install -qq -y --no-install-recommends \
        ca-certificates \
        curl \
        git \
        gnupg \
        jq \
        openssh-client \
        sudo \
        unzip \
    && mkdir -p /etc/apt/keyrings \
    && curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
        | gpg --dearmor -o /etc/apt/keyrings/githubcli-archive-keyring.gpg \
    && chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
        > /etc/apt/sources.list.d/github-cli.list \
    && apt-get update -qq \
    && apt-get install -qq -y --no-install-recommends gh nodejs npm \
    && rm -rf /var/lib/apt/lists/*

# Claude Code CLI — required by the `claude` agent (BYOK auth via
# CLAUDE_CODE_OAUTH_TOKEN / ANTHROPIC_API_KEY). Installed globally so it is on
# PATH for the unprivileged `mergecraft` runtime user.
RUN npm install -g @anthropic-ai/claude-code @openai/codex @google/gemini-cli \
    && npm cache clean --force \
    && claude --version \
    && codex --version \
    && gemini --version

WORKDIR /opt/mergecraft

COPY pyproject.toml uv.lock README.md ./
COPY src/mergecraft ./src/mergecraft

RUN uv sync --frozen --no-dev \
    && useradd -m -u 10001 -s /bin/bash mergecraft \
    && chown -R mergecraft:mergecraft /opt/mergecraft

COPY docker-entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Runs as root (no USER directive). A GitHub Docker Action mounts
# GITHUB_OUTPUT / GITHUB_ENV / GITHUB_WORKSPACE owned by the host runner uid; a
# non-root container user cannot write those file-commands (set_output → EACCES)
# nor operate on the runner-owned checkout (git "dubious ownership"). Root is the
# norm for Docker actions; the agent is still sandboxed via the shell/push inputs.
ENTRYPOINT ["/entrypoint.sh"]
CMD ["--help"]
