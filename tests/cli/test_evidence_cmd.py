"""W8 / W9 — ``mergecraft evidence show|verify`` (#354 / D10)."""

from __future__ import annotations

import json
from typing import Any

import pytest
from tests.support.cc_batch import invoke, load_module, plain, require_registered
from tests.support.dead_package_wiring import CLI_DIR, cli_cmd_path, root_callback_source

from mergecraft.cli.exits import CLI_SUCCESS_EXIT_CODE, CLI_USAGE_EXIT_CODE

_W9 = pytest.mark.xfail(
    reason="green after W9: evidence states + CLI (#354)",
    strict=False,
)


def test_evidence_command_is_currently_a_usage_error() -> None:
    """W8 current state: ``evidence`` is not a root verb yet."""
    result = invoke("evidence", "--help")
    assert result.exit_code == CLI_USAGE_EXIT_CODE, plain(result.stdout + result.stderr)


@_W9
def test_evidence_cli_is_a_new_cmd_module() -> None:
    """D10 — ``mergecraft evidence`` lives in ``cli/evidence_cmd.py``."""
    path = cli_cmd_path("evidence")
    assert path is not None, "expected src/mergecraft/cli/evidence_cmd.py"
    source = path.read_text(encoding="utf-8")
    assert "typer.Typer" in source or "def show" in source
    assert path.resolve() != (CLI_DIR / "app.py").resolve()
    module = load_module("mergecraft.cli.evidence_cmd")
    assert getattr(module, "app", None) is not None or callable(getattr(module, "run", None))


@_W9
def test_root_help_lists_evidence() -> None:
    """Happy: root help advertises ``evidence``."""
    result = invoke("--help")
    help_text = plain(result.stdout + result.stderr).casefold()
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, help_text
    assert "evidence" in help_text


@_W9
def test_evidence_show_and_verify_help_are_registered() -> None:
    """Happy: ``evidence show`` and ``evidence verify`` exist."""
    show = require_registered("evidence", "show", "--help", label="mergecraft evidence show")
    verify = require_registered("evidence", "verify", "--help", label="mergecraft evidence verify")
    assert "finding" in plain(show.stdout + show.stderr).casefold()
    assert "finding" in plain(verify.stdout + verify.stderr).casefold()


@_W9
def test_evidence_show_unknown_finding_id_is_an_error() -> None:
    """Error: unknown finding id is a non-success exit."""
    require_registered("evidence", "show", "--help", label="mergecraft evidence show")
    result = invoke("evidence", "show", "FINDING-DOES-NOT-EXIST")
    combined = plain(result.stdout + result.stderr)
    assert result.exit_code != CLI_SUCCESS_EXIT_CODE, combined


@_W9
def test_evidence_show_json_is_exportable() -> None:
    """#354 — evidence packets export as JSON via global ``--format json``."""
    require_registered("evidence", "show", "--help", label="mergecraft evidence show")
    result = invoke("--format", "json", "evidence", "show", "FINDING-DOES-NOT-EXIST")
    combined = plain(result.stdout + result.stderr)
    if result.exit_code == CLI_SUCCESS_EXIT_CODE:
        payload: Any = json.loads(result.stdout)
        assert isinstance(payload, dict)
    else:
        assert result.exit_code != CLI_SUCCESS_EXIT_CODE
        assert "finding" in combined.casefold() or "not" in combined.casefold()


def test_w9_does_not_fold_evidence_into_root_callback() -> None:
    """D10 current state — root callback stays additive-only (W9 must not edit it)."""
    source = root_callback_source()
    assert "def _root(" in source
    assert '"--format"' in source
    assert '"--quiet"' in source
    assert '"--color"' in source
    root_block = source.split("def _root(", 1)[1].split("\n@app.", 1)[0]
    assert "evidence_cmd" not in root_block
    assert "decide_approval" not in root_block
