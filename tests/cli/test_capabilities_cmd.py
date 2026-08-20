"""W3 — ``mergecraft capabilities`` capability manifest (#350 / D10).

Wave plan: ``.ignorelocal/waves/open-issues-sweep-2026-08-20c-wave-plan.md``.
New module ``mergecraft.cli.capabilities_cmd`` (leaf ``run``, like ``doctor`` /
``plan``). Root callback ``--format`` / ``--quiet`` / ``--color`` stay untouched
(D10); JSON uses the existing global ``--format json``.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import re
from typing import Any

import pytest
from tests.ci.workflow_support import REPO_ROOT
from typer.testing import CliRunner

from mergecraft.cli.app import app
from mergecraft.cli.exits import CLI_SUCCESS_EXIT_CODE, CLI_USAGE_EXIT_CODE
from mergecraft.cli.global_surface import CLI_JSON_SCHEMA_VERSION

runner = CliRunner()
_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_DUMB_ENV = {"TERM": "dumb", "NO_COLOR": "1"}

PRODUCTION_MODE_NAMES: frozenset[str] = frozenset({"Review", "IncrementalReview", "Plan"})
ALLOWED_CAPABILITIES: frozenset[str] = frozenset(
    {
        "identify",
        "investigate",
        "verify",
        "explain",
        "prioritize",
        "suggest",
    }
)
FORBIDDEN_CAPABILITIES: frozenset[str] = frozenset(
    {
        "edit_source",
        "apply_fixes",
        "commit",
        "push",
        "open_code_changing_pr",
    }
)
_CAPABILITIES_MODULE = "mergecraft.cli.capabilities_cmd"
_CAPABILITIES_PATH = REPO_ROOT / "src" / "mergecraft" / "cli" / "capabilities_cmd.py"


def _plain(text: str) -> str:
    return _ANSI.sub("", text)


def _load_capabilities_cmd() -> Any:
    spec = importlib.util.find_spec(_CAPABILITIES_MODULE)
    if spec is None:
        pytest.fail(f"expected new CLI module {_CAPABILITIES_MODULE} (D10)")
    return importlib.import_module(_CAPABILITIES_MODULE)


def _invoke(*argv: str) -> Any:
    return runner.invoke(app, list(argv), env=_DUMB_ENV)


def _json_payload(result: Any) -> dict[str, Any]:
    combined = _plain(result.stdout + result.stderr)
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, combined
    payload = json.loads(result.stdout)
    assert isinstance(payload, dict)
    return payload


def _require_capabilities_command() -> None:
    """Fail until ``capabilities`` is registered (avoids XPASS on Typer's generic usage exit)."""
    result = _invoke("capabilities", "--help")
    if result.exit_code != CLI_SUCCESS_EXIT_CODE:
        pytest.fail("mergecraft capabilities is not registered yet")


def test_capabilities_module_is_a_new_cli_file() -> None:
    """D10 — command lives in ``cli/capabilities_cmd.py``, not a root-callback edit."""
    assert _CAPABILITIES_PATH.is_file(), (
        "W3 must add src/mergecraft/cli/capabilities_cmd.py (additive CLI module)"
    )
    source = _CAPABILITIES_PATH.read_text(encoding="utf-8")
    assert "def run(" in source


def test_capabilities_module_exports_run_and_manifest() -> None:
    """Unit: new module exposes ``run`` and a zero-arg ``capabilities_manifest``."""
    module = _load_capabilities_cmd()
    run = getattr(module, "run", None)
    manifest_fn = getattr(module, "capabilities_manifest", None)
    assert callable(run)
    assert callable(manifest_fn)
    payload = manifest_fn()
    assert isinstance(payload, dict)
    assert payload.get("review_only") is True
    assert frozenset(payload["modes"]) == PRODUCTION_MODE_NAMES
    assert frozenset(payload["allowed"]) == ALLOWED_CAPABILITIES
    assert frozenset(payload["forbidden"]) == FORBIDDEN_CAPABILITIES
    assert "schema_version" not in payload


def test_root_help_lists_capabilities_command() -> None:
    """Happy: ``mergecraft --help`` advertises ``capabilities``."""
    result = _invoke("--help")
    help_text = _plain(result.stdout + result.stderr).casefold()
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, help_text
    assert "capabilities" in help_text


def test_capabilities_help_describes_manifest() -> None:
    """Happy: subcommand help names the capability manifest."""
    result = _invoke("capabilities", "--help")
    help_text = _plain(result.stdout + result.stderr).casefold()
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, help_text
    assert "manifest" in help_text or "review-only" in help_text


def test_capabilities_table_states_review_only() -> None:
    """Happy: default table/text output states the review-only product boundary."""
    result = _invoke("capabilities")
    output = _plain(result.stdout + result.stderr)
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, output
    collapsed = re.sub(r"\s+", " ", output.casefold())
    assert "review-only" in collapsed or "review only" in collapsed
    for mode in PRODUCTION_MODE_NAMES:
        assert mode.casefold() in collapsed


def test_capabilities_json_uses_global_format_flag() -> None:
    """Happy: inherit root ``--format json`` (D10 — no command-local format flag)."""
    payload = _json_payload(_invoke("--format", "json", "capabilities"))
    assert payload["schema_version"] == CLI_JSON_SCHEMA_VERSION
    assert payload["review_only"] is True
    assert frozenset(payload["modes"]) == PRODUCTION_MODE_NAMES
    assert frozenset(payload["allowed"]) == ALLOWED_CAPABILITIES
    assert frozenset(payload["forbidden"]) == FORBIDDEN_CAPABILITIES


def test_capabilities_json_forbidden_covers_write_surface() -> None:
    """Edge: manifest forbids edit/commit/push/code-changing PR — #350 write surface."""
    payload = _json_payload(_invoke("--format", "json", "capabilities"))
    forbidden = frozenset(payload["forbidden"])
    for name in FORBIDDEN_CAPABILITIES:
        assert name in forbidden


def test_capabilities_json_allowed_is_review_verbs_only() -> None:
    """Edge: allowed set is identify/investigate/verify/explain/prioritize/suggest."""
    payload = _json_payload(_invoke("--format", "json", "capabilities"))
    allowed = frozenset(payload["allowed"])
    assert allowed.isdisjoint(FORBIDDEN_CAPABILITIES)
    assert allowed == ALLOWED_CAPABILITIES


def test_capabilities_json_modes_exclude_write_capable_names() -> None:
    """Edge: production mode list does not advertise Fix/Build/Task/write modes."""
    payload = _json_payload(_invoke("--format", "json", "capabilities"))
    modes = {str(name) for name in payload["modes"]}
    for write_name in ("Fix", "Build", "Task", "AddressReviews", "ResolveConflicts"):
        assert write_name not in modes


def test_capabilities_rejects_unexpected_positional() -> None:
    """Error: extra argv is a usage failure, not a partial manifest."""
    _require_capabilities_command()
    result = _invoke("capabilities", "unexpected")
    combined = _plain(result.stdout + result.stderr)
    assert result.exit_code == CLI_USAGE_EXIT_CODE, combined
    assert "unexpected" in combined.casefold() or "usage" in combined.casefold()


def test_capabilities_unknown_option_is_usage_error() -> None:
    """Error: unknown flag exits usage (2), without inventing a local --format."""
    _require_capabilities_command()
    result = _invoke("capabilities", "--not-a-real-flag")
    combined = _plain(result.stdout + result.stderr)
    assert result.exit_code == CLI_USAGE_EXIT_CODE, combined
