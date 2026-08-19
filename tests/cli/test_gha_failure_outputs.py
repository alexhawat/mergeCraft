"""Plan W5 — structured failure outputs + ``evidence_packet`` wiring (``#32/#37/#38``).

Contracts:

- W5.3: failure paths write the ``result`` output as JSON carrying
  ``outcome`` + ``error.code`` + a sanitized message — not only ``::error::``
  + exit 1.
- W5.4: the declared ``evidence_packet`` output is actually written, and its
  value parses as the packet schema (multiline heredoc handling stays as-is).
- W5.5: the dead entry-point writer under ``src/mergecraft/action/`` (module
  ``entry``) is deleted and unreferenced.

The happy-path ``result`` output behavior, W5.3, and W5.4 are pinned plain —
they landed in W5 (see ``cli/gha_cmd.py``'s ``_structured_failure_result`` /
``_write_evidence_packet_output``). W5.5 (the dead-entrypoint deletion) is now
plain green too — W5.5 deleted ``src/mergecraft/action/entry.py``, so the
``xfail`` marker was removed from ``test_action_entry_module_is_gone`` below.

``test_action_entry_module_is_gone`` below deliberately builds the dead
module's dotted/slashed path from parts rather than spelling it as a
contiguous literal, so this file does not itself show up when an
implementation wave grep-sweeps ``tests/`` for lingering references before
deleting the module (that sweep is the W5.5 precondition).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
import typer

from mergecraft.cli.gha_cmd import (
    _run_main,
    _structured_failure_result,
    _write_evidence_packet_output,
)
from mergecraft.evidence.packet import PACKET_SCHEMA_VERSION
from mergecraft.run_outcome import RunOutcome

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _read_output_file(path: Path) -> dict[str, str]:
    """Parse a ``$GITHUB_OUTPUT`` file including heredoc multiline entries."""
    entries: dict[str, str] = {}
    lines = path.read_text(encoding="utf-8").splitlines()
    idx = 0
    while idx < len(lines):
        line = lines[idx]
        if "<<" in line:
            name, delimiter = line.split("<<", 1)
            body: list[str] = []
            idx += 1
            while idx < len(lines) and lines[idx] != delimiter:
                body.append(lines[idx])
                idx += 1
            entries[name] = "\n".join(body)
        elif "=" in line:
            name, value = line.split("=", 1)
            entries[name] = value
        idx += 1
    return entries


def _patch_main(monkeypatch: pytest.MonkeyPatch, result) -> None:
    import mergecraft.main as main_mod

    async def _fake_main():
        return result

    monkeypatch.setattr(main_mod, "main", _fake_main)


def test_success_writes_result_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Baseline — a successful run writes the ``result`` output (already true)."""
    from mergecraft.main import MainResult

    out = tmp_path / "github_output"
    out.touch()
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    _patch_main(monkeypatch, MainResult(success=True, output="review-body", result="review-body"))

    asyncio.run(_run_main())

    entries = _read_output_file(out)
    assert entries.get("result") == "review-body"


def test_success_multiline_result_uses_heredoc(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#38 — multiline values keep the UUID-heredoc form (regression anchor)."""
    from mergecraft.main import MainResult

    out = tmp_path / "github_output"
    out.touch()
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    _patch_main(monkeypatch, MainResult(success=True, output="line1\nline2", result="line1\nline2"))

    asyncio.run(_run_main())

    raw = out.read_text(encoding="utf-8")
    assert "result<<ghadelimiter_" in raw
    assert _read_output_file(out)["result"] == "line1\nline2"


def test_failure_writes_structured_result_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """W5.3 — a failed run must leave machine-readable output, not just logs."""
    from mergecraft.main import MainResult

    out = tmp_path / "github_output"
    out.touch()
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    _patch_main(monkeypatch, MainResult(success=False, error="provider exploded"))

    with pytest.raises(typer.Exit):
        asyncio.run(_run_main())

    entries = _read_output_file(out)
    assert "result" in entries, "failure path wrote no result output"
    payload = json.loads(entries["result"])
    assert payload["outcome"] != "passed"
    assert payload["error"]["code"], "structured error must carry a stable code"
    assert "provider exploded" in payload["error"]["message"]


def test_evidence_packet_output_parses_as_packet_schema(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """W5.4 — ``evidence_packet`` output is emitted and conforms to the schema.

    Interpretation pinned for the impl wave: the output value is the packet
    JSON itself (heredoc-delimited), per the W5.4 contract text; the packet
    bytes already exist at ``MainResult.evidence_packet_path``.
    """
    from mergecraft.evidence.packet import MergeEvidencePacket
    from mergecraft.main import MainResult

    # `schema_version` is a deliberately-required pinned field (D7,
    # `_PinnedRequiredFieldInfo` in `evidence/packet.py`) — omitting it made
    # this fixture raise `pydantic.ValidationError` before the W5.4 wiring
    # under test ever ran. Fixture bug, unrelated to the wiring; see the W5
    # notes in the wave plan.
    packet = MergeEvidencePacket(
        schema_version=PACKET_SCHEMA_VERSION,
        change_id="0123456789abcdef0123456789abcdef01234567",
        agent={"id": "claude", "version": "1.0", "model": "claude-opus"},
        files_changed=["a.py"],
        findings=[],
        deterministic_checks=[],
    )
    packet_path = tmp_path / "packet.json"
    packet_path.write_text(packet.model_dump_json(), encoding="utf-8")

    out = tmp_path / "github_output"
    out.touch()
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    _patch_main(
        monkeypatch,
        MainResult(success=True, output="ok", result="ok", evidence_packet_path=str(packet_path)),
    )

    asyncio.run(_run_main())

    entries = _read_output_file(out)
    assert "evidence_packet" in entries, "evidence_packet output was never written"
    parsed = json.loads(entries["evidence_packet"])
    reparsed = MergeEvidencePacket.model_validate(parsed)
    assert reparsed.schema_version == PACKET_SCHEMA_VERSION


class TestStructuredFailureResult:
    """Direct unit coverage for ``_structured_failure_result`` (W5.3, ``#32``)."""

    def test_payload_carries_outcome_code_and_message(self) -> None:
        payload = json.loads(
            _structured_failure_result(RunOutcome.infra_error, "provider exploded")
        )
        assert payload["outcome"] == "infra_error"
        assert payload["error"]["code"] == "mergecraft.infra_error"
        assert payload["error"]["message"] == "provider exploded"

    def test_message_is_redacted_before_it_reaches_the_payload(self) -> None:
        """The message must go through ``redact_secrets`` — never raw secret bytes on disk."""
        secret = "ghp_" + "a" * 36
        payload = json.loads(
            _structured_failure_result(RunOutcome.infra_error, f"token leaked: {secret}")
        )
        assert secret not in payload["error"]["message"]

    @pytest.mark.parametrize("outcome", list(RunOutcome))
    def test_error_code_matches_error_code_for_outcome(self, outcome: RunOutcome) -> None:
        from mergecraft.run_outcome import error_code_for_outcome

        payload = json.loads(_structured_failure_result(outcome, "boom"))
        assert payload["error"]["code"] == error_code_for_outcome(outcome)


class TestWriteEvidencePacketOutput:
    """Direct unit coverage for ``_write_evidence_packet_output`` (W5.4, ``#37``)."""

    def test_writes_the_packet_bytes_as_the_output_value(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        packet_path = tmp_path / "packet.json"
        packet_path.write_text('{"schema_version": "1.5.0"}', encoding="utf-8")
        out = tmp_path / "github_output"
        out.touch()
        monkeypatch.setenv("GITHUB_OUTPUT", str(out))

        _write_evidence_packet_output(str(packet_path))

        entries = _read_output_file(out)
        assert entries.get("evidence_packet") == '{"schema_version": "1.5.0"}'

    def test_missing_packet_file_does_not_raise(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A stale/unreadable path logs a warning and skips the output — it must not crash the run."""
        out = tmp_path / "github_output"
        out.touch()
        monkeypatch.setenv("GITHUB_OUTPUT", str(out))

        _write_evidence_packet_output(str(tmp_path / "does-not-exist.json"))

        assert "evidence_packet" not in _read_output_file(out)


class TestVerdictDiagnosticOutput:
    """Plan W6.2 / D10 — the declared ``verdict_diagnostic`` output is actually written (``#265``).

    ``action.yml`` has declared a ``verdict_diagnostic`` output since the
    terminal-verdict work landed, but ``_run_main`` writes only
    ``evidence_packet`` and ``result``: no code path ever calls
    ``_set_output("verdict_diagnostic", …)``, so the documented output is
    permanently empty and consumers cannot branch on the closed
    ``VerdictDiagnostic`` code the run already computed.

    D10 pins **both** arms deliberately. The empty arm is the one a naive
    implementation misses: writing nothing at all leaves the key absent, so a
    consumer's ``steps.run.outputs.verdict_diagnostic`` is undefined rather
    than the documented empty string ("Empty when the run did not evaluate
    terminal protocol policy").

    The diagnostic is currently computed in ``main_outcome._verdict_protocol_publish``
    and only reaches ``span_attrs_for_verdict_diagnostic`` — ``MainResult`` has
    no field for it, which is why constructing one below is red today.
    """

    @staticmethod
    def _run(monkeypatch: pytest.MonkeyPatch, out: Path, **fields: object) -> dict[str, str]:
        from mergecraft.main import MainResult

        out.touch()
        monkeypatch.setenv("GITHUB_OUTPUT", str(out))
        _patch_main(monkeypatch, MainResult(**fields))  # type: ignore[arg-type]
        asyncio.run(_run_main())
        return _read_output_file(out)

    @pytest.mark.xfail(
        reason="green after W8: thread the diagnostic into _set_output('verdict_diagnostic', …)",
        strict=False,
    )
    def test_success_with_diagnostic_writes_the_code(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A successful run that produced a diagnostic exposes its closed code."""
        from mergecraft.mcp.verdict import VerdictDiagnostic

        entries = self._run(
            monkeypatch,
            tmp_path / "github_output",
            success=True,
            output="ok",
            result="ok",
            verdict_diagnostic=VerdictDiagnostic.approved.value,
        )
        assert entries.get("verdict_diagnostic") == VerdictDiagnostic.approved.value

    @pytest.mark.xfail(
        reason="green after W8: thread the diagnostic into _set_output('verdict_diagnostic', …)",
        strict=False,
    )
    def test_success_without_diagnostic_writes_empty_string(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """D10's empty arm — the key is present and empty, never absent."""
        entries = self._run(
            monkeypatch,
            tmp_path / "github_output",
            success=True,
            output="ok",
            result="ok",
        )
        assert "verdict_diagnostic" in entries, (
            "no diagnostic must still write the output as an empty string, not omit it"
        )
        assert entries["verdict_diagnostic"] == ""

    @pytest.mark.xfail(
        reason="green after W8: thread the diagnostic into _set_output('verdict_diagnostic', …)",
        strict=False,
    )
    @pytest.mark.parametrize(
        "code",
        [
            "approved",
            "policy_rejection",
            "provider_failure",
            "provider_success_without_submission",
            "fallback_triggered",
        ],
    )
    def test_every_closed_code_round_trips(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, code: str
    ) -> None:
        """The output is the raw closed code — no prefixing, quoting, or truncation."""
        from mergecraft.mcp.verdict import VerdictDiagnostic

        assert code in {member.value for member in VerdictDiagnostic}, (
            f"{code!r} left the closed VerdictDiagnostic vocabulary"
        )
        entries = self._run(
            monkeypatch,
            tmp_path / "github_output",
            success=True,
            output="ok",
            result="ok",
            verdict_diagnostic=code,
        )
        assert entries.get("verdict_diagnostic") == code

    @pytest.mark.xfail(
        reason="green after W8: thread the diagnostic into _set_output('verdict_diagnostic', …)",
        strict=False,
    )
    def test_failure_path_still_writes_the_diagnostic(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A failed run is exactly when the consumer needs the code — it must not be dropped.

        ``_run_main`` raises ``typer.Exit`` on the failure path *after* the
        outputs are written, so the write has to happen before that exit.
        """
        from mergecraft.main import MainResult

        out = tmp_path / "github_output"
        out.touch()
        monkeypatch.setenv("GITHUB_OUTPUT", str(out))
        _patch_main(
            monkeypatch,
            MainResult(  # type: ignore[call-arg]
                success=False,
                error="agent blocked",
                verdict_diagnostic="policy_rejection",
            ),
        )

        with pytest.raises(typer.Exit):
            asyncio.run(_run_main())

        assert _read_output_file(out).get("verdict_diagnostic") == "policy_rejection"

    def test_set_output_writes_an_empty_value_as_a_present_key(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Green today — the transport D10's empty arm relies on already behaves.

        ``_set_output`` short-circuits masking on an empty value but still
        appends ``name=``, so W8 does not need a new writer for the empty case.
        """
        out = tmp_path / "github_output"
        monkeypatch.setenv("GITHUB_OUTPUT", str(out))
        from mergecraft.cli.gha_cmd import _set_output

        _set_output("verdict_diagnostic", "")

        assert out.read_text(encoding="utf-8") == "verdict_diagnostic=\n"
        assert _read_output_file(out)["verdict_diagnostic"] == ""


def test_action_entry_module_is_gone() -> None:
    """W5.5 — the dead, malformed entry writer must not exist or be referenced.

    Builds the dead module's dotted/slashed path from parts rather than a
    contiguous literal — the missing symbol under test is exactly the string
    an implementation wave's pre-deletion grep sweep of ``tests/`` searches
    for, and this test must not be a false positive in that sweep.
    """
    import importlib.util

    _pkg, _mod = "action", "entry"
    dead_module = f"mergecraft.{_pkg}.{_mod}"
    assert importlib.util.find_spec(dead_module) is None, (
        f"mergecraft.{_pkg}.{_mod} still exists — W5.5 deletes it"
    )
    entry_file = _REPO_ROOT / "src" / "mergecraft" / _pkg / f"{_mod}.py"
    assert not entry_file.exists()
    offenders = []
    needle_dotted = f"{_pkg}.{_mod}"
    needle_slashed = f"{_pkg}/{_mod}"
    for source in (_REPO_ROOT / "src").rglob("*.py"):
        text = source.read_text(encoding="utf-8")
        if needle_dotted in text or needle_slashed in text:
            offenders.append(str(source.relative_to(_REPO_ROOT)))
    assert not offenders, f"stale references to the dead action-entry module: {offenders}"
