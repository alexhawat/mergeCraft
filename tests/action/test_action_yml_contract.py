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
            ("tracing-content", "INPUT_TRACING_CONTENT"),
            ("tracing-export-untrusted-content", "INPUT_TRACING_EXPORT_UNTRUSTED_CONTENT"),
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
            "tracing-content",
            "tracing-export-untrusted-content",
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
        if input_name in {
            "tracing",
            "tracing-to",
            "logfire-token",
            "otel-endpoint",
            "tracing-content",
            "tracing-export-untrusted-content",
        }:
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
        # S1/S3/S5 merge: the 1h fallback is inline in the merged base
        # ``main.py`` (``main()``). The documented default's runtime anchor
        # lives there, so keep it in sync with the ``action.yml`` prose.
        main_source = (_REPO_ROOT / "src" / "mergecraft" / "main.py").read_text(encoding="utf-8")
        assert "3_600_000" in main_source, (
            "main.py lost its 1h fallback — the documented default has no runtime anchor"
        )

    def test_status_checks_default_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """W12.2 — ``status_checks`` unset resolves to disabled (as documented)."""
        monkeypatch.delenv("INPUT_STATUS_CHECKS", raising=False)
        from mergecraft.utils.payload import resolve_non_prompt_inputs

        inputs = resolve_non_prompt_inputs()
        assert (inputs.status_checks == "enabled") is False

    def test_setup_timeout_unset_preserves_yaml_value(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """S1 review — unset ``setup_timeout`` input must not clobber a YAML value.

        Precedence is action input > YAML ``setup_timeout_s`` > default (10m).
        An unset ``INPUT_SETUP_TIMEOUT`` must resolve to ``None`` so
        ``apply_setup_overrides`` leaves the YAML-layer value alone — the old
        resolver returned the 600 s default unconditionally, always overwriting
        a YAML-configured timeout.
        """
        from mergecraft.action.inputs import apply_setup_overrides, resolve_setup_timeout_s
        from mergecraft.config.settings import RepoSettings

        monkeypatch.delenv("INPUT_SETUP_TIMEOUT", raising=False)
        assert resolve_setup_timeout_s() is None, (
            "unset INPUT_SETUP_TIMEOUT must resolve to None (defer to YAML/default)"
        )

        yaml_value = 300
        settings = RepoSettings(setup_timeout_s=yaml_value)
        updated = apply_setup_overrides(settings)
        assert updated.setup_timeout_s == yaml_value, (
            "YAML-configured setup_timeout_s must survive an unset action input"
        )

    def test_setup_timeout_input_wins_over_yaml(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """S1 review — an explicit action input wins over the YAML value."""
        from mergecraft.action.inputs import apply_setup_overrides
        from mergecraft.config.settings import RepoSettings

        monkeypatch.setenv("INPUT_SETUP_TIMEOUT", "2m")
        settings = RepoSettings(setup_timeout_s=300)
        updated = apply_setup_overrides(settings)
        assert updated.setup_timeout_s == 120, "explicit action input must override the YAML value"

    def test_declared_action_defaults_defer_to_runtime(
        self, action_yml: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """S1 review — the declared Action defaults must not defeat YAML precedence.

        ``action.yml`` declares ``default: ""`` for ``setup_timeout`` and
        ``setup_failure_policy`` so ``INPUT_SETUP_TIMEOUT`` /
        ``INPUT_SETUP_FAILURE_POLICY`` are absent when the operator does not
        set them. Feeding the declared defaults through ``apply_setup_overrides``
        must leave the ``RepoSettings`` values alone (no clobber to the runtime
        default, no override of a YAML value).
        """
        from mergecraft.action.inputs import apply_setup_overrides
        from mergecraft.config.settings import RepoSettings

        for name, env_var in (
            ("setup_timeout", "INPUT_SETUP_TIMEOUT"),
            ("setup_failure_policy", "INPUT_SETUP_FAILURE_POLICY"),
        ):
            spec = action_yml["inputs"][name]
            assert spec.get("default", "") == "", (
                f"{name}: Action default must be empty so YAML precedence survives"
            )
            monkeypatch.setenv(env_var, str(spec.get("default", "")))

        # ``_read_input`` treats empty as unset — a YAML value survives.
        settings = RepoSettings(setup_timeout_s=300, setup_failure_policy="fail")
        updated = apply_setup_overrides(settings)
        assert updated.setup_timeout_s == 300
        assert updated.setup_failure_policy == "fail"

        # And the runtime defaults still apply for a bare settings object.
        bare = apply_setup_overrides(RepoSettings())
        assert bare.setup_timeout_s == 600
        assert bare.setup_failure_policy == "inconclusive"

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

    def test_docker_action_declares_no_output_values(self, action_yml: dict[str, Any]) -> None:
        """Plan W6.3 — ``outputs.*.value`` is inert for a Docker action (``#272``).

        ``value:`` under ``outputs`` is composite-action wiring: it maps a
        *step's* output onto the action's output. A ``runs.using: docker``
        action has no steps, so ``${{ steps.run.outputs.* }}`` resolves to
        nothing and every declared value is dead metadata. The real transport
        is the container writing ``$GITHUB_OUTPUT`` directly (``_set_output``
        in ``cli/gha_cmd.py``). Keeping the ``value:`` lines advertises a
        wiring that does not exist.
        """
        assert action_yml["runs"]["using"] == "docker", (
            "this contract is docker-specific; a composite action legitimately "
            "needs outputs.*.value"
        )
        with_value = sorted(
            name
            for name, spec in (action_yml.get("outputs") or {}).items()
            if "value" in (spec or {})
        )
        assert not with_value, (
            f"docker action declares inert outputs.*.value for: {with_value} — "
            "delete the value: keys, keep the descriptions"
        )

    def test_docker_action_pulls_digest_pinned_slim_image(self, action_yml: dict[str, Any]) -> None:
        """#526 — published Action must resolve to a GHCR pull, not a Dockerfile build."""
        image = action_yml["runs"]["image"]
        assert image != "Dockerfile"
        assert image.startswith("docker://ghcr.io/alexhawat/mergecraft@sha256:")
        assert "analyzers" not in image

    def test_every_output_keeps_its_description(self, action_yml: dict[str, Any]) -> None:
        """W8.1 deletes ``value:`` only — the consumer-facing prose must survive."""
        outputs = action_yml.get("outputs") or {}
        assert outputs, "action.yml declares no outputs"
        missing = sorted(
            name for name, spec in outputs.items() if not (spec or {}).get("description")
        )
        assert not missing, f"outputs without a description: {missing}"

    def test_verdict_diagnostic_output_is_declared(self, action_yml: dict[str, Any]) -> None:
        """#265 — the output consumers read must stay declared (only its ``value:`` goes)."""
        assert "verdict_diagnostic" in (action_yml.get("outputs") or {})

    def test_no_expression_survives_in_any_output_block(self) -> None:
        """W8.1 must not leave a ``${{ }}`` behind anywhere under ``outputs:``.

        Greps the raw file: PyYAML keeps the expression as an opaque string, so
        a parsed-dict check cannot distinguish a deleted ``value:`` from one
        that moved into description prose. The needle is assembled from parts
        so this test file never contains the literal that
        ``scripts/check_action_yml_hygiene.py`` and the repo rule forbid.
        """
        needle = "$" + "{" * 2
        raw = _ACTION_YML.read_text(encoding="utf-8")
        _preamble, marker, outputs_onward = raw.partition("\noutputs:\n")
        assert marker, "action.yml has no top-level outputs: block"
        outputs_block, _runs_marker, _rest = outputs_onward.partition("\nruns:\n")
        offending = [line for line in outputs_block.splitlines() if needle in line]
        assert not offending, f"expression(s) left in the outputs block: {offending}"

    def test_no_secrets_expression_in_manifest_text(self) -> None:
        """A ``${{ secrets.* }}`` expression anywhere in action.yml fails to load.

        GitHub evaluates ``${{ ... }}`` wherever it appears lexically in a
        composite action's YAML — including inside plain ``description:``
        prose meant only as a consumer-facing example — and ``secrets`` is
        not a valid named-value in a composite action's own metadata scope.
        This previously broke every consumer pinning past a specific commit
        with "Unrecognized named-value: 'secrets'" at action-load time, not
        at review time, so it surfaced only when something (a self-review
        pin bump) finally pinned past the offending commit. Parsed YAML
        loses the literal ``${{ }}`` text once it's inside a string value,
        so this greps the raw file rather than the parsed dict.
        """
        raw = _ACTION_YML.read_text(encoding="utf-8")
        offending = [line for line in raw.splitlines() if "${{" in line and "secrets." in line]
        assert not offending, f"literal secrets.* expression(s) in action.yml: {offending}"
