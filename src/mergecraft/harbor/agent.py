"""Harbor ``BaseInstalledAgent`` wrapper around ``mergecraft diff-review --json``."""

from __future__ import annotations

import json
import os
import re
import shlex
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any, override

from harbor.agents.installed.base import BaseInstalledAgent, with_prompt_template
from harbor.agents.utils import get_api_key_var_names_from_model_name
from harbor.models.trial.paths import EnvironmentPaths

if TYPE_CHECKING:
    from harbor.environments.base import BaseEnvironment
    from harbor.models.agent.context import AgentContext

DEFAULT_INSTALL_REF = "pre-0.0.1"
MERGECRAFT_GIT_URL = "git+https://github.com/alexhawat/mergeCraft"
FINDINGS_FILENAME = "findings.json"
_PATCH_CANDIDATES = ("task.patch", "changes.patch", "diff.patch", "review.patch")


def _path_env() -> str:
    return (
        'if [ -f "$HOME/.local/bin/env" ]; then . "$HOME/.local/bin/env"; '
        'else export PATH="$HOME/.local/bin:$PATH"; fi'
    )


def _resolve_patch_path(instruction: str) -> str | None:
    """Return an in-container patch path from the task instruction, if any."""
    for candidate in _PATCH_CANDIDATES:
        if candidate in instruction:
            return candidate
    match = re.search(r"(?:^|\s)([\w./-]+\.patch)\b", instruction)
    if match:
        return match.group(1)
    return None


class MergecraftReviewAgent(BaseInstalledAgent):
    """Install mergecraft with ``uv tool install`` and run structured diff reviews."""

    @staticmethod
    @override
    def name() -> str:
        return "mergecraft"

    @override
    def get_version_command(self) -> str | None:
        return f"{_path_env()}; mergecraft --help | head -1"

    @override
    def parse_version(self, stdout: str) -> str:
        text = stdout.strip()
        for line in text.splitlines():
            line = line.strip()
            if line:
                return line
        return text or "unknown"

    @override
    async def install(self, environment: BaseEnvironment) -> None:
        install_ref = self._get_env("MERGECRAFT_INSTALL_REF") or DEFAULT_INSTALL_REF
        install_spec = f"{MERGECRAFT_GIT_URL}@{install_ref}"

        await self.exec_as_root(
            environment,
            command=(
                "if command -v apt-get &>/dev/null; then"
                "  apt-get update && apt-get install -y curl git;"
                " elif command -v apk &>/dev/null; then"
                "  apk add --no-cache curl bash git;"
                " elif command -v yum &>/dev/null; then"
                "  yum install -y curl git;"
                " elif command -v dnf &>/dev/null; then"
                "  dnf install -y curl git;"
                " else"
                '  echo "Warning: No known package manager found, assuming curl/git exist" >&2;'
                " fi"
            ),
            env={"DEBIAN_FRONTEND": "noninteractive"},
        )

        await self.exec_as_agent(
            environment,
            command=(
                "set -euo pipefail; "
                "if ! command -v uv >/dev/null 2>&1; then"
                "  curl -LsSf https://astral.sh/uv/install.sh | sh;"
                " fi && "
                f"{_path_env()} && "
                'if ! grep -q \'export PATH="$HOME/.local/bin:$PATH"\' "$HOME/.bashrc" 2>/dev/null; then'
                '  echo \'export PATH="$HOME/.local/bin:$PATH"\' >> "$HOME/.bashrc";'
                " fi && "
                f"uv tool install {shlex.quote(install_spec)} && "
                "mergecraft --help | head -1"
            ),
        )

    def _build_run_env(self) -> dict[str, str]:
        env: dict[str, str] = {}
        for key in (
            "ANTHROPIC_API_KEY",
            "OPENAI_API_KEY",
            "MERGECRAFT_MODEL",
            "MERGECRAFT_AGENT",
        ):
            value = self._get_env(key)
            if value is not None:
                env[key] = value

        if self.model_name:
            env["MERGECRAFT_MODEL"] = self.model_name
            try:
                for api_key_var in get_api_key_var_names_from_model_name(self.model_name):
                    if api_key_var not in env:
                        api_value = self._get_env(api_key_var)
                        if api_value is not None:
                            env[api_key_var] = api_value
            except ValueError:
                pass

        for key, value in os.environ.items():
            if key.startswith("MERGECRAFT_") and key not in env:
                env[key] = value
        for key, value in self._extra_env.items():
            if key.startswith("MERGECRAFT_"):
                env[key] = value

        return env

    @override
    @with_prompt_template
    async def run(
        self,
        instruction: str,
        environment: BaseEnvironment,
        context: AgentContext,
    ) -> None:
        findings_path = PurePosixPath(EnvironmentPaths.agent_dir) / FINDINGS_FILENAME
        patch_path = _resolve_patch_path(instruction)

        cmd_parts = [
            _path_env() + ";",
            "mergecraft diff-review",
            "--cwd .",
            f"--json {findings_path.as_posix()}",
        ]
        if patch_path is not None:
            cmd_parts.append(f"--diff {shlex.quote(patch_path)}")
        if self.model_name:
            cmd_parts.append(f"--model {shlex.quote(self.model_name)}")
        if instruction.strip():
            cmd_parts.append(f"--prompt {shlex.quote(instruction)}")

        await self.exec_as_agent(
            environment,
            command=" ".join(cmd_parts),
            env=self._build_run_env(),
        )

    @override
    def populate_context_post_run(self, context: AgentContext) -> None:
        findings_file = self.logs_dir / FINDINGS_FILENAME
        if not findings_file.exists():
            self.logger.debug("No findings.json produced at %s", findings_file)
            return

        try:
            payload: dict[str, Any] = json.loads(findings_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            self.logger.debug("Failed to read findings.json: %s", exc)
            return

        findings = payload.get("findings")
        if isinstance(findings, list):
            metadata = context.metadata or {}
            metadata["findings_count"] = len(findings)
            context.metadata = metadata
