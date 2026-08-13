"""Plan W12.2 / W12.4 — ``action.yml`` ↔ runtime metadata sync (``#21``, ``#29``).

Contract: for every action input, the documented default equals the resolved
runtime default. These tests parse the real ``action.yml`` and feed each
documented default string through the same parser the runtime uses.

W12 landed: ``suggest_eval_add`` default is ``disabled`` (bool-ish values
normalized via ``_normalize_suggest_eval_add``); ``push`` prose says
``Default: restricted`` matching runtime resolution.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ACTION_YML = _REPO_ROOT / "action.yml"


@pytest.fixture(scope="module")
def action_yml() -> dict[str, Any]:
    with _ACTION_YML.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _plain_string_defaults(yml: dict[str, Any]) -> dict[str, str]:
    """Inputs whose ``default:`` is a plain string (not a ``${{ }}`` expression)."""
    out: dict[str, str] = {}
    for name, spec in yml.get("inputs", {}).items():
        default = (spec or {}).get("default")
        if isinstance(default, str) and not default.startswith("${{"):
            out[name] = default
    return out


class TestDeclaredDefaultsParse:
    """Every default string in action.yml must be accepted by its runtime parser."""

    def test_suggest_eval_add_default_parses(
        self, action_yml: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """W12.4 — the shipped default must not crash startup."""
        default = _plain_string_defaults(action_yml)["suggest_eval_add"]
        from mergecraft.utils.payload import resolve_non_prompt_inputs

        monkeypatch.setenv("INPUT_SUGGEST_EVAL_ADD", default)
        inputs = resolve_non_prompt_inputs()
        assert inputs.suggest_eval_add in (None, "disabled"), (
            f"default {default!r} must resolve to the disabled semantic, "
            f"got {inputs.suggest_eval_add!r}"
        )

    @pytest.mark.parametrize(
        ("input_name", "env_var"),
        [
            ("model_pin", "INPUT_MODEL_PIN"),
            ("analyzers", "INPUT_ANALYZERS"),
            ("sarif_upload", "INPUT_SARIF_UPLOAD"),
            ("allow_pr_target_comments", "INPUT_ALLOW_PR_TARGET_COMMENTS"),
            ("tracing", "INPUT_TRACING"),
            ("tracing-to", "INPUT_TRACING_TO"),
            ("logfire-token", "INPUT_LOGFIRE_TOKEN"),
            ("otel-endpoint", "INPUT_OTEL_ENDPOINT"),
        ],
        ids=[
            "model_pin",
            "analyzers",
            "sarif_upload",
            "allow_pr_target_comments",
            "tracing",
            "tracing-to",
            "logfire-token",
            "otel-endpoint",
        ],
    )
    def test_default_string_is_accepted(
        self,
        action_yml: dict[str, Any],
        monkeypatch: pytest.MonkeyPatch,
        input_name: str,
        env_var: str,
    ) -> None:
        """The declared default for each input must survive its runtime parser."""
        defaults = _plain_string_defaults(action_yml)
        assert input_name in defaults, f"{input_name}: no plain-string default in action.yml"
        monkeypatch.setenv(env_var, defaults[input_name])
        if input_name in {"tracing", "tracing-to", "logfire-token", "otel-endpoint"}:
            from mergecraft.action.inputs import resolve_tracing_from_action_inputs

            resolved = resolve_tracing_from_action_inputs()
            assert resolved is not None
        elif input_name == "sarif_upload":
            from mergecraft.analyzers.sarif_upload import resolve_sarif_upload_enabled

            assert (
                resolve_sarif_upload_enabled(action_input=os.environ[env_var], repo_setting=False)
                is False
            )
        elif input_name == "allow_pr_target_comments":
            from mergecraft.utils.payload import _allow_pr_target_comments_optin

            assert _allow_pr_target_comments_optin() is False
        else:
            from mergecraft.utils.payload import resolve_non_prompt_inputs

            resolve_non_prompt_inputs()


class TestDocumentedDefaultsMatchRuntime:
    """The prose default in each input's description must equal the runtime value."""

    def test_push_default_prose_matches_resolution(
        self, action_yml: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """W12.4 — ``push`` unset must resolve to what the description promises."""
        description = action_yml["inputs"]["push"]["description"]
        for env in ("INPUT_PUSH",):
            monkeypatch.delenv(env, raising=False)
        from mergecraft.config.settings import RepoSettings
        from mergecraft.utils.payload import resolve_non_prompt_inputs

        inputs = resolve_non_prompt_inputs()
        settings = RepoSettings()
        resolved = inputs.push or settings.push or "restricted"
        if "Default: enabled" in description:
            assert resolved == "enabled", (
                f"description promises 'Default: enabled' but unset resolves to {resolved!r}"
            )
        else:  # docs fixed — resolution must match the new prose
            assert "Default: restricted" in description
            assert resolved == "restricted"

    def test_timeout_default_prose_matches_resolution(self, action_yml: dict[str, Any]) -> None:
        """W12.2 — ``timeout`` unset resolves to the documented 1h fallback."""
        description = action_yml["inputs"]["timeout"]["description"]
        assert "Default: 1h" in description
        from mergecraft.utils.time_parse import resolve_timeout_ms

        assert resolve_timeout_ms(None) is None, "unset must defer to the caller's fallback"
        # S1/S3/S5 split (commit 4e8f420+): the 1h fallback moved out of
        # ``main.py`` into ``main_models._resolve_run_budget``. The orchestrator
        # delegates to that helper, so the documented default's runtime anchor
        # now lives next to the budget resolver.
        main_models_source = (_REPO_ROOT / "src" / "mergecraft" / "main_models.py").read_text(
            encoding="utf-8"
        )
        assert "3_600_000" in main_models_source, (
            "main_models.py lost its 1h fallback — the documented default has no runtime anchor"
        )

    def test_status_checks_default_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """W12.2 — ``status_checks`` unset resolves to disabled (as documented)."""
        monkeypatch.delenv("INPUT_STATUS_CHECKS", raising=False)
        from mergecraft.utils.payload import resolve_non_prompt_inputs

        inputs = resolve_non_prompt_inputs()
        assert (inputs.status_checks == "enabled") is False

    def test_token_input_is_not_confused_with_logfire_token(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """W12.2 — GitHub auth token and logfire token never cross-wire."""
        monkeypatch.setenv("INPUT_TOKEN", "ghs_github_token")
        monkeypatch.setenv("INPUT_LOGFIRE_TOKEN", "lf_logfire_token")
        monkeypatch.setenv("INPUT_TRACING", "true")
        monkeypatch.setenv("INPUT_TRACING_TO", "logfire")
        from mergecraft.action.inputs import resolve_tracing_from_action_inputs

        resolved = resolve_tracing_from_action_inputs()
        assert resolved["logfire_token"] == "lf_logfire_token"
        assert "ghs_github_token" not in repr(resolved)


class TestActionYmlHygiene:
    """Static hygiene on the action manifest itself."""

    def test_every_input_maps_to_env_arg(self, action_yml: dict[str, Any]) -> None:
        """Every declared input is wired into the container's env (else it's dead)."""
        env = action_yml.get("runs", {}).get("env", {})
        env_vars = set(env)
        for name in action_yml.get("inputs", {}):
            expected = "INPUT_" + name.upper().replace("-", "_")
            if name == "codex_sandbox":  # deliberately routed to MERGECRAFT_CODEX_SANDBOX
                assert "MERGECRAFT_CODEX_SANDBOX" in env_vars
                continue
            assert expected in env_vars, f"input {name!r} not wired to {expected} in runs.env"

    def test_every_env_arg_references_an_input(self, action_yml: dict[str, Any]) -> None:
        """No env entry smuggles a value that bypasses the declared inputs."""
        env = action_yml.get("runs", {}).get("env", {})
        declared = {
            "INPUT_" + name.upper().replace("-", "_") for name in action_yml.get("inputs", {})
        } | {"MERGECRAFT_CODEX_SANDBOX"}
        for env_var, expr in env.items():
            assert env_var in declared, f"runs.env {env_var} has no matching declared input"
            assert isinstance(expr, str), f"{env_var}: non-string value {expr!r}"
            assert expr.startswith("${{"), (
                f"{env_var} hard-codes a value instead of referencing inputs.*: {expr!r}"
            )
