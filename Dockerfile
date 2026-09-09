# SPDX-License-Identifier: MIT
# syntax=docker/dockerfile:1.7
# Production Action image for mergeCraft (standalone BYOK runtime).
# Pins (W7 / D7): base + uv + node by digest; gh source + dependency patch by checksum;
# agent CLIs via docker/agent-clis lockfile (npm ci).
#
# Reproducible rebuilds: pass SOURCE_DATE_EPOCH and build with
#   docker buildx build --provenance=false --sbom=false \
#     --output type=docker,dest=out.tar,rewrite-timestamp=true ...
ARG SOURCE_DATE_EPOCH=1700000000

# Build the upstream gh release with its remaining vulnerable Go module patched.
# The archive, Go toolchain and dependency checksums are immutable inputs.
FROM --platform=$BUILDPLATFORM golang:1.27.1-bookworm@sha256:648f440f42a0958804efb24df176f806f9d353b41f1c0627f666428e40310f6b AS gh-builder
ARG TARGETARCH
ENV GOTOOLCHAIN=local CGO_ENABLED=0
ADD --checksum=sha256:e16749bc0d99dc0633a3d5ebadf48ffff1c24beb1ce83e8f6a71bb64ce477e9a \
    https://codeload.github.com/cli/cli/tar.gz/45437bc7eeeb3359bbfddd1742f79de7652fd3e2 /tmp/gh-source.tar.gz
WORKDIR /src/gh
COPY docker/gh/dependencies.patch /tmp/dependencies.patch
RUN tar -xzf /tmp/gh-source.tar.gz --strip-components=1 -C /src/gh \
    && git apply --no-index /tmp/dependencies.patch \
    && GOOS=linux GOARCH=${TARGETARCH} go build -mod=readonly -trimpath -buildvcs=false \
        -ldflags="-s -w -X github.com/cli/cli/v2/internal/build.Version=2.100.0-mergecraft.1" \
        -o /out/gh ./cmd/gh

FROM python:3.14-slim-bookworm@sha256:9ab8d9c8514b44f90cf0029dd42fdd7e9e211e639c8b995304cc04568dee900f

ARG SOURCE_DATE_EPOCH
ARG SOURCE_REVISION=""
ENV SOURCE_DATE_EPOCH=${SOURCE_DATE_EPOCH}
LABEL org.opencontainers.image.revision=${SOURCE_REVISION}

COPY --from=ghcr.io/astral-sh/uv:0.11.29@sha256:eb2843a1e56fd9e30c7276ce1a52cba86e64c7b385f5e3279a0e08e02dd058fc \
    /uv /usr/local/bin/uv

# Node 22 (node + npm) from the official image — no NodeSource installer pipe.
COPY --from=node:22-bookworm-slim@sha256:d649c27dae7ba0137b3cef5dd75baa422c08dc3d9e3fc0c23dfb172dc3cc6436 \
    /usr/local/bin/node /usr/local/bin/node
# npm's bundled dependencies are independently pinned; Node 22 still ships
# the vulnerable npm 10 bundle. No floating global installation is used.
ADD --checksum=sha256:9f58bff01604cb1b14008fef14dceb14d836a49225e45c6c2e37de3be3e707f0 \
    https://registry.npmjs.org/npm/-/npm-11.19.1.tgz /tmp/npm.tgz
RUN mkdir -p /usr/local/lib/node_modules/npm \
    && tar -xzf /tmp/npm.tgz --strip-components=1 -C /usr/local/lib/node_modules/npm \
    && ln -sf ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -sf ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
    && rm /tmp/npm.tgz

# uv is the supported Python package installer in this image. Even pip's
# latest release vendors vulnerable msgpack/setuptools; remove that unused
# installer and its ensurepip bootstrap copy rather than suppress the scan.
RUN uv pip uninstall --python /usr/local/bin/python pip \
    && rm -rf /usr/local/lib/python3.14/ensurepip

COPY --from=gh-builder /out/gh /usr/bin/gh
COPY --from=gh-builder /src/gh/LICENSE /usr/share/doc/gh/LICENSE

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

RUN apt-get update -qq \
    && apt-get install -qq -y --no-install-recommends \
        ca-certificates \
        curl \
        git \
        jq \
        openssh-client \
        sudo \
        unzip \
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

COPY pyproject.toml uv.lock README.md hatch_build.py ./
COPY src/mergecraft ./src/mergecraft
COPY evals/corpora/recall_pass_corpus.json ./evals/corpora/recall_pass_corpus.json

# ``--extra tracing`` installs logfire + the OpenTelemetry SDK/exporter. Without
# it the sink factory degrades a ``logfire`` / ``otel`` sink to ``NullSink``
# with a warning (src/mergecraft/tracing/sinks.py), so an Action run wired with
# ``tracing-to: logfire`` would silently export nothing. The extra is exact-pinned
# in pyproject and covered by ``uv.lock``, so ``--frozen`` still applies.
RUN uv sync --frozen --no-dev --extra tracing \
    && useradd -m -u 10001 -s /bin/bash mergecraft \
    && chown -R mergecraft:mergecraft /opt/mergecraft \
    && rm -f /opt/mergecraft/.venv/lib/python3.14/site-packages/merge_craft-*.dist-info/uv_cache.json \
    && sed -i '/uv_cache\.json/d' \
        /opt/mergecraft/.venv/lib/python3.14/site-packages/merge_craft-*.dist-info/RECORD \
    && rm -rf /root/.cache/uv /tmp/* \
    && { command -v setpriv >/dev/null && getent passwd mergecraft >/dev/null || { echo "FATAL: privilege drop unavailable (setpriv or mergecraft user missing)"; exit 1; }; }

# The container build has no .git directory. Stamp only the source S, never
# the future manifest commit C or this image's own digest D.
RUN SOURCE_REVISION="${SOURCE_REVISION}" python - <<'PYTHON'
import os
import pathlib
import re

value = os.environ["SOURCE_REVISION"]
if value and not re.fullmatch("[0-9a-f]{40}", value):
    raise ValueError("invalid source revision")
pathlib.Path("src/mergecraft/_build_metadata.py").write_text(
    "__commit__: str | None = " + repr(value or None) + "\n"
)
PYTHON

COPY docker-entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Runs as root (no USER directive). A GitHub Docker Action mounts
# GITHUB_OUTPUT / GITHUB_ENV / GITHUB_WORKSPACE owned by the host runner uid; a
# non-root container user cannot write those file-commands (set_output → EACCES)
# nor operate on the runner-owned checkout (git "dubious ownership"). Root is the
# norm for Docker actions; the agent is still sandboxed via the shell/push inputs.
ENTRYPOINT ["/entrypoint.sh"]
CMD ["--help"]
