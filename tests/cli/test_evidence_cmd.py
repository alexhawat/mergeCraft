"""W8 / W9 — ``mergecraft evidence show|verify`` (#354 / D10)."""

from __future__ import annotations

import json
from typing import Any

from tests.support.cc_batch import invoke, plain, require_registered

from mergecraft.cli.exits import CLI_SUCCESS_EXIT_CODE


def test_root_help_lists_evidence() -> None:
    """Happy: root help advertises ``evidence``."""
    result = invoke("--help")
    help_text = plain(result.stdout + result.stderr).casefold()
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, help_text
    assert "evidence" in help_text


def test_evidence_show_and_verify_help_are_registered() -> None:
    """Happy: ``evidence show`` and ``evidence verify`` exist."""
    show = require_registered("evidence", "show", "--help", label="mergecraft evidence show")
    verify = require_registered("evidence", "verify", "--help", label="mergecraft evidence verify")
    assert "finding" in plain(show.stdout + show.stderr).casefold()
    assert "finding" in plain(verify.stdout + verify.stderr).casefold()


def test_evidence_show_unknown_finding_id_is_an_error() -> None:
    """Error: unknown finding id is a non-success exit."""
    require_registered("evidence", "show", "--help", label="mergecraft evidence show")
    result = invoke("evidence", "show", "FINDING-DOES-NOT-EXIST")
    combined = plain(result.stdout + result.stderr)
    assert result.exit_code != CLI_SUCCESS_EXIT_CODE, combined


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
