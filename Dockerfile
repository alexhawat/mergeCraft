# SPDX-License-Identifier: MIT
# syntax=docker/dockerfile:1.7
# Production Action image for mergeCraft (standalone BYOK runtime).
# Pins (W7 / D7): base + uv + node by digest; gh via pinned .deb + SHA256;
# agent CLIs via docker/agent-clis lockfile (npm ci).
#
# Reproducible rebuilds: pass SOURCE_DATE_EPOCH and build with
#   docker buildx build --provenance=false --sbom=false \
#     --output type=docker,dest=out.tar,rewrite-timestamp=true ...
ARG SOURCE_DATE_EPOCH=1700000000

FROM python:3.14-slim-bookworm@sha256:23c59390fc717bf09f9336908199a0ae75d9c4264bf296123f94ad772fea3b52

ARG SOURCE_DATE_EPOCH
ENV SOURCE_DATE_EPOCH=${SOURCE_DATE_EPOCH}

COPY --from=ghcr.io/astral-sh/uv:0.11.29@sha256:eb2843a1e56fd9e30c7276ce1a52cba86e64c7b385f5e3279a0e08e02dd058fc \
    /uv /usr/local/bin/uv

# Node 22 (node + npm) from the official image — no NodeSource installer pipe.
COPY --from=node:22-bookworm-slim@sha256:d649c27dae7ba0137b3cef5dd75baa422c08dc3d9e3fc0c23dfb172dc3cc6436 \
    /usr/local/bin/node /usr/local/bin/node
COPY --from=node:22-bookworm-slim@sha256:d649c27dae7ba0137b3cef5dd75baa422c08dc3d9e3fc0c23dfb172dc3cc6436 \
    /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -sf ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -sf ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/mergecraft/.venv/bin:${PATH}" \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    NPM_CONFIG_CACHE=/tmp/npm-cache \
    NODE_OPTIONS=--disable-warning=ExperimentalWarning

# The action runs as root in an ephemeral CI container; Claude Code treats this
# as a sandbox context. Scoped to the image, so local `mergecraft diff-review`
# (non-root) is unaffected.
ENV IS_SANDBOX=1

# gh CLI — pinned .deb URL + SHA256 (no floating vendor apt repo).
ARG GH_VERSION=2.97.0
ARG GH_SHA256_AMD64=7c7fa3bb890db0934baf65910d97b8c0fa437b2e590f7f7daf6bdf82c5c486d7
ARG GH_SHA256_ARM64=0ba7a76739c865d82ebde24667d875d9b8caa55db47c7597c24accdd4defd2bb

RUN apt-get update -qq \
    && apt-get install -qq -y --no-install-recommends \
        ca-certificates \
        curl \
        git \
        jq \
        openssh-client \
        sudo \
        unzip \
    && arch="$(dpkg --print-architecture)" \
    && case "$arch" in \
         amd64) gh_sha="${GH_SHA256_AMD64}" ;; \
         arm64) gh_sha="${GH_SHA256_ARM64}" ;; \
         *) echo "unsupported arch for gh: $arch" >&2; exit 1 ;; \
       esac \
    && curl -fsSL -o /tmp/gh.deb \
        "https://github.com/cli/cli/releases/download/v${GH_VERSION}/gh_${GH_VERSION}_linux_${arch}.deb" \
    && echo "${gh_sha}  /tmp/gh.deb" | sha256sum -c - \
    && apt-get install -qq -y /tmp/gh.deb \
    && rm -f /tmp/gh.deb \
    && rm -rf /var/lib/apt/lists/* /var/log/apt /var/log/dpkg.log \
        /var/log/alternatives.log /var/cache/ldconfig /var/cache/apt /tmp/*

# Claude Code / Codex / Gemini / OpenCode CLIs — lockfile-pinned (Cursor is
# API-only, no CLI to pin). Installed under /opt/agent-clis with bins on PATH
# for the unprivileged `mergecraft` runtime user.
#
# opencode-ai backs the `opencode` agent, which resolve_runtime_agent() picks for
# every model whose provider is not anthropic/openai/google/cursor. Without it
# that path raised FileNotFoundError, so no third-party OpenAI-compatible
# provider was reachable at all.
COPY docker/agent-clis/package.json docker/agent-clis/package-lock.json /opt/agent-clis/
RUN cd /opt/agent-clis \
    && npm ci \
    && ln -sf /opt/agent-clis/node_modules/.bin/claude /usr/local/bin/claude \
    && ln -sf /opt/agent-clis/node_modules/.bin/codex /usr/local/bin/codex \
    && ln -sf /opt/agent-clis/node_modules/.bin/gemini /usr/local/bin/gemini \
    && ln -sf /opt/agent-clis/node_modules/.bin/opencode /usr/local/bin/opencode \
    && claude --version \
    && codex --version \
    && gemini --version \
    && opencode --version \
    && rm -rf /tmp/npm-cache /root/.npm /root/.codex /root/.gemini \
        /tmp/node-compile-cache /tmp/* /var/cache/ldconfig

WORKDIR /opt/mergecraft

COPY pyproject.toml uv.lock README.md ./
COPY src/mergecraft ./src/mergecraft

RUN uv sync --frozen --no-dev \
    && useradd -m -u 10001 -s /bin/bash mergecraft \
    && chown -R mergecraft:mergecraft /opt/mergecraft \
    && rm -f /opt/mergecraft/.venv/lib/python3.14/site-packages/merge_craft-*.dist-info/uv_cache.json \
    && sed -i '/uv_cache\.json/d' \
        /opt/mergecraft/.venv/lib/python3.14/site-packages/merge_craft-*.dist-info/RECORD \
    && rm -rf /root/.cache/uv /tmp/* \
    && command -v setpriv >/dev/null \
    && getent passwd mergecraft >/dev/null \
    || { echo "FATAL: privilege drop unavailable (setpriv or mergecraft user missing)"; exit 1; }

COPY docker-entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Runs as root (no USER directive). A GitHub Docker Action mounts
# GITHUB_OUTPUT / GITHUB_ENV / GITHUB_WORKSPACE owned by the host runner uid; a
# non-root container user cannot write those file-commands (set_output → EACCES)
# nor operate on the runner-owned checkout (git "dubious ownership"). Root is the
# norm for Docker actions; the agent is still sandboxed via the shell/push inputs.
ENTRYPOINT ["/entrypoint.sh"]
CMD ["--help"]
