"""Fix pull requests need a fail-then-pass receipt (#1056 part 5).

A pull request classified as a fix (conventional ``fix`` title or a
``review.fixLabels`` label) carries ``ChangeSet.fix_proof`` — a
``FixProofSignal`` of ``required`` and the ingested receipt ``status``. The
classifier turns it into one ``fix.*`` reason and a ``fix_proof`` gate appended
to ``GATE_ORDER``:

- not a fix → ``fix.not-required`` (``low``), gate ``true``;
- a fix with a ``proven`` receipt → ``fix.proven`` (``low``), gate ``true``;
- every other status → ``medium`` with its own code, gate ``false``.

The part-2 invariants still hold (``lane == max(reasons)``; ``eligible`` ⇔
every gate ``true`` ⇔ ``low``) and a ``high`` reason still wins. The run packet
builds the signal from ``ToolState.red_green`` plus the PR title and labels,
adds no packet section, and the deterministic run record names the ``fix.*``
code.

New names are read lazily (``_api()`` / ``_rg()``) so the suite collects before
they exist; ``GATE_ORDER`` position is asserted only as "after the part-2
gates", so another lane may append its own gate beside this one.
"""

from __future__ import annotations

import re
from importlib import import_module
from pathlib import Path
from typing import Any

import pytest

from mergecraft.classify.blast_radius import classify_blast_radius

REPO_ROOT = Path(__file__).resolve().parents[2]
_RANK: dict[str, int] = {"low": 0, "medium": 1, "high": 2}
_STATS: dict[str, object] = {"lines_added": 3, "lines_deleted": 1}
_DOCS: dict[str, Any] = {"changed_paths": ["docs/guide.md"], "diff_stats": dict(_STATS)}
_PART2_GATES: tuple[str, ...] = (
    "inputs",
    "migrations",
    "auth_security_payment",
    "secrets_config_deployment",
    "irreversible_infra",
    "public_api",
    "dependencies",
    "tests",
    "review_config",
    "source",
)
FIX_CODES: dict[str, str] = {
    "fix.not-required": "low",
    "fix.proven": "low",
    "fix.not-proven": "medium",
    "fix.no-receipt": "medium",
    "fix.receipt.invalid": "medium",
    "fix.receipt.mismatch": "medium",
}
# A fix PR's receipt status → the reason code it must emit.
FAILING_STATUS_CODES: dict[str, str] = {
    "not-proven": "fix.not-proven",
    "no-tests": "fix.not-proven",
    "no-receipt": "fix.no-receipt",
    "invalid": "fix.receipt.invalid",
    "mismatch": "fix.receipt.mismatch",
    "not-declared": "fix.no-receipt",
}
ALL_STATUSES = (
    "proven",
    "not-proven",
    "no-tests",
    "no-receipt",
    "invalid",
    "mismatch",
    "not-declared",
)


def _api() -> Any:
    return import_module("mergecraft.classify.blast_radius")


def _rg() -> Any:
    return import_module("mergecraft.ci.red_green")


def _change(
    status: str, *, required: bool = True, base: dict[str, Any] | None = None
) -> dict[str, Any]:
    change = dict(_DOCS if base is None else base)
    change["fix_proof"] = {"required": required, "status": status}
    return change


def _classify(change: Any) -> Any:
    return classify_blast_radius(change)


def _codes(result: Any) -> dict[str, Any]:
    return {reason.code: reason for reason in result.reasons}


def _gates(result: Any) -> dict[str, bool | None]:
    return {gate.gate: gate.passed for gate in result.checklist}


def _listed_in_gate_order(result: Any) -> bool:
    """The checklist is a subsequence of ``GATE_ORDER``: unsupplied signals are omitted."""
    order = list(_api().GATE_ORDER)
    listed = [gate.gate for gate in result.checklist]
    return listed == [gate for gate in order if gate in set(listed)]


def _fix_reasons(result: Any) -> list[Any]:
    return [reason for reason in result.reasons if reason.code.startswith("fix.")]


# ── catalogue and gate order ─────────────────────────────────────────────────


@pytest.mark.parametrize(("code", "lane"), sorted(FIX_CODES.items()))
def test_each_fix_code_is_in_the_catalogue_with_its_default_lane(code: str, lane: str) -> None:
    assert _api().LANE_REASON_CATALOGUE[code] == lane


def test_the_part2_codes_keep_their_lanes() -> None:
    catalogue = _api().LANE_REASON_CATALOGUE

    assert catalogue["baseline.clean"] == "low"
    assert catalogue["paths.migrations"] == "high"
    assert set(FIX_CODES) <= set(catalogue)


def test_fix_proof_is_appended_after_the_part2_gates_once() -> None:
    order = tuple(_api().GATE_ORDER)

    assert order[: len(_PART2_GATES)] == _PART2_GATES
    assert order.count("fix_proof") == 1
    assert order.index("fix_proof") >= len(_PART2_GATES)


def test_the_signal_types_carry_the_contract_keys() -> None:
    api = _api()

    keys = set(api.FixProofSignal.__annotations__)
    assert {"required", "status", "detail"} <= keys
    assert keys <= {"required", "status", "detail"}
    assert "fix_proof" in api.ChangeSet.__annotations__


# ── fix PR with a proven receipt ─────────────────────────────────────────────


def test_a_fix_with_a_proven_receipt_passes_the_gate_and_stays_low() -> None:
    result = _classify(_change("proven"))
    reasons = _codes(result)

    assert result.lane == "low"
    assert result.auto_merge_lane == "eligible"
    assert reasons["fix.proven"].lane == "low"
    assert reasons["fix.proven"].message
    assert _gates(result)["fix_proof"] is True
    assert all(passed is True for passed in _gates(result).values())


def test_a_non_fix_pull_request_is_not_required_and_passes_the_gate() -> None:
    result = _classify(_change("not-declared", required=False))
    reasons = _codes(result)

    assert result.lane == "low"
    assert result.auto_merge_lane == "eligible"
    assert reasons["fix.not-required"].lane == "low"
    assert _gates(result)["fix_proof"] is True


@pytest.mark.parametrize("status", [*ALL_STATUSES, "not-required"])
def test_a_non_fix_pull_request_is_not_required_whatever_the_status(status: str) -> None:
    result = _classify(_change(status, required=False))

    assert [reason.code for reason in _fix_reasons(result)] == ["fix.not-required"]
    assert _gates(result)["fix_proof"] is True
    assert result.lane == "low"


# ── fix PR without a proven receipt ──────────────────────────────────────────


@pytest.mark.parametrize(
    ("status", "code"),
    sorted(FAILING_STATUS_CODES.items()),
    ids=sorted(FAILING_STATUS_CODES),
)
def test_a_fix_without_a_proven_receipt_is_medium_with_its_code(status: str, code: str) -> None:
    result = _classify(_change(status))
    reasons = _codes(result)

    assert result.lane == "medium"
    assert result.auto_merge_lane == "assisted"
    assert reasons[code].lane == "medium"
    assert reasons[code].message
    assert _gates(result)["fix_proof"] is False
    assert [reason.code for reason in _fix_reasons(result)] == [code]


def test_an_undeclared_receipt_on_a_fix_names_the_setting() -> None:
    reason = _codes(_classify(_change("not-declared")))["fix.no-receipt"]

    assert "ciEvidence.redGreen" in reason.message
    assert "redGreenArtifacts" not in reason.message


def test_a_missing_receipt_message_differs_from_an_undeclared_one() -> None:
    missing = _codes(_classify(_change("no-receipt")))["fix.no-receipt"]
    undeclared = _codes(_classify(_change("not-declared")))["fix.no-receipt"]

    assert missing.message != undeclared.message
    assert "ciEvidence.redGreen" in undeclared.message


# ── the evidence detail reaches the reason message ──────────────────────────

DETAIL_CASES: list[tuple[str, str, str]] = [
    (
        "invalid",
        "fix.receipt.invalid",
        "receipt oversized: 1000001 bytes, past the 1000000-byte cap",
    ),
    (
        "no-receipt",
        "fix.no-receipt",
        "workflow run 99 ran in the fork attacker/demo, not acme/demo",
    ),
    ("no-receipt", "fix.no-receipt", "the change set could not be verified: the diff is truncated"),
    (
        "mismatch",
        "fix.receipt.mismatch",
        "the receipt names head 3333333, this pull request is at 2222222",
    ),
]


@pytest.mark.parametrize(
    ("status", "code", "detail"),
    DETAIL_CASES,
    ids=["oversized", "fork", "truncated", "mismatch"],
)
def test_the_reason_message_carries_the_evidence_detail(
    status: str, code: str, detail: str
) -> None:
    change = {**_DOCS, "fix_proof": {"required": True, "status": status, "detail": detail}}

    reason = _codes(_classify(change))[code]

    assert detail in reason.message
    assert reason.lane == "medium"


@pytest.mark.parametrize(
    ("status", "code"),
    [("invalid", "fix.receipt.invalid"), ("no-receipt", "fix.no-receipt")],
)
def test_a_signal_without_a_detail_still_has_a_message(status: str, code: str) -> None:
    reason = _codes(_classify(_change(status)))[code]

    assert reason.message.strip()
    assert "None" not in reason.message


@pytest.mark.parametrize("status", [status for status in ALL_STATUSES if status != "proven"])
def test_a_fix_pr_is_never_eligible_without_a_proven_receipt(status: str) -> None:
    result = _classify(_change(status))

    assert result.auto_merge_lane != "eligible"
    assert _RANK[result.lane] >= _RANK["medium"]
    assert _gates(result)["fix_proof"] is False


# ── high still wins; the floor is a floor ────────────────────────────────────

_MIGRATION: dict[str, Any] = {
    "changed_paths": ["migrations/0001_init.sql"],
    "diff_stats": dict(_STATS),
}


def test_a_proven_fix_beside_a_high_reason_stays_high() -> None:
    result = _classify(_change("proven", base=_MIGRATION))
    reasons = _codes(result)

    assert result.lane == "high"
    assert result.auto_merge_lane == "forbidden"
    assert reasons["paths.migrations"].lane == "high"
    assert reasons["fix.proven"].lane == "low"
    assert _gates(result)["fix_proof"] is True
    assert _gates(result)["migrations"] is False


def test_an_unproven_fix_beside_a_high_reason_stays_high() -> None:
    result = _classify(_change("mismatch", base=_MIGRATION))

    assert result.lane == "high"
    assert _codes(result)["fix.receipt.mismatch"].lane == "medium"
    assert _gates(result)["fix_proof"] is False


def test_a_proven_fix_cannot_lower_a_medium_source_change() -> None:
    base = {
        "changed_paths": ["src/pkg/a.py", "tests/test_a.py"],
        "diff_stats": {"lines_added": 40, "lines_deleted": 10},
    }

    result = _classify(_change("proven", base=base))

    assert result.lane == "medium"
    assert _codes(result)["source.changed"].lane == "medium"
    assert _gates(result)["fix_proof"] is True
    assert _gates(result)["source"] is False


def test_a_proven_fix_with_missing_inputs_stays_medium() -> None:
    result = _classify(_change("proven", base={"diff_stats": dict(_STATS)}))

    assert result.lane == "medium"
    assert _codes(result)["signal.missing.paths"].lane == "medium"
    assert _gates(result)["inputs"] is False
    assert _gates(result)["fix_proof"] is True


# ── no signal supplied: the gate is omitted, not unknown ─────────────────────


def test_no_signal_omits_the_fix_proof_gate_and_emits_no_fix_reason() -> None:
    """No ``fix_proof`` key: the signal is not part of this classification.

    The ``fix_proof`` gate is left out of the checklist (not ``null``), no
    ``fix.*`` reason is emitted, and a complete low change still passes every
    listed gate and stays ``eligible``. Supplying the signal is what adds the gate.
    """
    without = _classify(dict(_DOCS))
    with_signal = _classify(_change("not-proven"))

    assert "fix_proof" in _api().GATE_ORDER
    assert "fix_proof" not in _gates(without)
    assert _fix_reasons(without) == []
    assert [reason.code for reason in without.reasons] == ["baseline.clean"]
    assert without.lane == "low"
    assert without.auto_merge_lane == "eligible"
    assert all(passed is True for passed in _gates(without).values())
    assert set(_PART2_GATES) <= set(_gates(without))
    assert _listed_in_gate_order(without)
    assert _gates(with_signal)["fix_proof"] is False
    assert "fix.not-proven" in _codes(with_signal)


@pytest.mark.parametrize(
    "change",
    [
        {"diff_stats": dict(_STATS)},
        {"changed_paths": ["docs/a.md"]},
        dict(_MIGRATION),
    ],
    ids=["missing-paths", "missing-diff", "migration"],
)
def test_no_signal_omits_the_gate_whatever_else_the_change_holds(change: dict[str, Any]) -> None:
    result = _classify(change)

    assert "fix_proof" in _api().GATE_ORDER
    assert "fix_proof" not in _gates(result)
    assert _fix_reasons(result) == []
    assert _listed_in_gate_order(result)


@pytest.mark.parametrize("status", ALL_STATUSES)
@pytest.mark.parametrize("required", [True, False], ids=["fix", "non-fix"])
def test_a_supplied_signal_always_measures_the_gate(required: bool, status: str) -> None:
    """A supplied signal is never ``null``: every fix-proof status is a measurement."""
    passed = _gates(_classify(_change(status, required=required)))["fix_proof"]

    assert isinstance(passed, bool)
    assert passed is (not required or status == "proven")


# ── invariants over a table ──────────────────────────────────────────────────

INVARIANT_CASES: list[tuple[str, dict[str, Any]]] = [
    *((f"fix-{status}", _change(status)) for status in ALL_STATUSES),
    *(
        (f"non-fix-{status}", _change(status, required=False))
        for status in ("proven", "no-receipt")
    ),
    ("proven-beside-migration", _change("proven", base=_MIGRATION)),
    ("invalid-beside-migration", _change("invalid", base=_MIGRATION)),
    ("proven-missing-paths", _change("proven", base={"diff_stats": dict(_STATS)})),
    ("not-proven-missing-diff", _change("not-proven", base={"changed_paths": ["docs/a.md"]})),
    (
        "proven-small-source",
        _change(
            "proven",
            base={
                "changed_paths": ["src/pkg/t.py"],
                "diff_stats": {"lines_added": 1, "lines_deleted": 1},
            },
        ),
    ),
]
_INVARIANT_IDS = [case_id for case_id, _change in INVARIANT_CASES]
_INVARIANT_CHANGES = [change for _id, change in INVARIANT_CASES]


@pytest.mark.parametrize("change", _INVARIANT_CHANGES, ids=_INVARIANT_IDS)
def test_the_lane_is_the_max_over_reasons_with_a_fix_signal(change: dict[str, Any]) -> None:
    result = _classify(change)

    assert len(_fix_reasons(result)) == 1
    assert result.lane == max((reason.lane for reason in result.reasons), key=_RANK.__getitem__)


@pytest.mark.parametrize("change", _INVARIANT_CHANGES, ids=_INVARIANT_IDS)
def test_eligible_iff_every_gate_passed_iff_low_with_a_fix_signal(change: dict[str, Any]) -> None:
    result = _classify(change)
    all_passed = all(gate.passed is True for gate in result.checklist)

    assert "fix_proof" in _gates(result)
    assert (result.auto_merge_lane == "eligible") is all_passed
    assert (result.lane == "low") is all_passed


@pytest.mark.parametrize("change", _INVARIANT_CHANGES, ids=_INVARIANT_IDS)
def test_every_code_with_a_fix_signal_is_in_the_catalogue(change: dict[str, Any]) -> None:
    result = _classify(change)

    codes = {reason.code for reason in result.reasons}
    assert codes <= set(_api().LANE_REASON_CATALOGUE)
    assert codes & set(FIX_CODES)
    assert "fix_proof" in _gates(result)
    assert _listed_in_gate_order(result)
    assert set(_PART2_GATES) <= set(_gates(result))


def test_the_invariant_table_has_both_eligible_and_non_eligible_rows() -> None:
    results = [_classify(change) for change in _INVARIANT_CHANGES]
    lanes = {result.auto_merge_lane for result in results}

    assert {"eligible", "assisted", "forbidden"} <= lanes
    assert all(_gates(result)["fix_proof"] is not None for result in results)


def test_the_rendered_reason_names_the_fix_code() -> None:
    result = _classify(_change("invalid"))

    assert "fix.receipt.invalid" in result.reason


# ── run-diff classifier ──────────────────────────────────────────────────────

_DOCS_DIFF = """\
diff --git a/docs/guide.md b/docs/guide.md
--- a/docs/guide.md
+++ b/docs/guide.md
@@ -1,2 +1,2 @@
 # Guide
-old line
+new line
"""


def _state(red_green: Any = None) -> Any:
    from mergecraft.mcp.tool_state import init_tool_state

    state = init_tool_state(owner="acme", name="demo", dir="/nonexistent")
    if red_green is not None:
        state.red_green = red_green
    return state


def _signal(state: Any, *, title: str, labels: list[str], fix_labels: list[str]) -> Any:
    from mergecraft.evidence.run_packet import fix_proof_signal_for_state

    return fix_proof_signal_for_state(state, title=title, labels=labels, fix_labels=fix_labels)


_DEFAULT_FIX_LABELS = ["bug", "fix"]


def test_the_shared_helper_builds_a_proven_signal_from_tool_state() -> None:
    signal = _signal(
        _state(_evidence("proven")), title="fix(ci): x", labels=[], fix_labels=_DEFAULT_FIX_LABELS
    )

    assert (signal["required"], signal["status"]) == (True, "proven")
    result = _classify({**_DOCS, "fix_proof": signal})
    assert "fix.proven" in _codes(result)
    assert result.lane == "low"


@pytest.mark.parametrize("status", sorted(FAILING_STATUS_CODES), ids=sorted(FAILING_STATUS_CODES))
def test_the_shared_helper_carries_the_recorded_status(status: str) -> None:
    signal = _signal(
        _state(_evidence(status)), title="fix: x", labels=[], fix_labels=_DEFAULT_FIX_LABELS
    )

    assert (signal["required"], signal["status"]) == (True, status)
    assert signal.get("detail") == f"receipt {status}"
    assert FAILING_STATUS_CODES[status] in _codes(_classify({**_DOCS, "fix_proof": signal}))


def test_the_shared_helper_without_evidence_on_a_fix_is_a_missing_receipt() -> None:
    signal = _signal(_state(), title="fix: x", labels=[], fix_labels=_DEFAULT_FIX_LABELS)

    assert signal["required"] is True
    assert signal["status"] in {"no-receipt", "not-declared"}
    result = _classify({**_DOCS, "fix_proof": signal})
    assert "fix.no-receipt" in _codes(result)
    assert result.lane == "medium"


@pytest.mark.parametrize(
    ("title", "labels", "fix_labels", "required"),
    [
        ("feat: x", [], _DEFAULT_FIX_LABELS, False),
        ("feat: x", ["Bug"], _DEFAULT_FIX_LABELS, True),
        ("feat: x", ["regression"], ["regression"], True),
        ("feat: x", ["bug"], ["regression"], False),
        ("Fix: x", [], _DEFAULT_FIX_LABELS, True),
        ("  fix(ci): x", [], [], True),
    ],
    ids=[
        "feature",
        "default-label",
        "configured-label",
        "configured-list-replaces-default",
        "capitalised-type",
        "leading-whitespace",
    ],
)
def test_the_shared_helper_decides_whether_proof_is_required(
    title: str, labels: list[str], fix_labels: list[str], required: bool
) -> None:
    signal = _signal(_state(_evidence("proven")), title=title, labels=labels, fix_labels=fix_labels)

    assert signal["required"] is required
    expected = "fix.proven" if required else "fix.not-required"
    assert expected in _codes(_classify({**_DOCS, "fix_proof": signal}))


def test_the_verification_tool_lane_matches_the_packet_lane(tmp_path: Path) -> None:
    """``mcp/verification.py`` builds the signal through the same helper as the packet."""
    from mergecraft.mcp.verification import _run_lane

    ctx = _packet_ctx(tmp_path, title="fix: handle x")
    packet = _packet(tmp_path, title="fix: handle x")

    assert packet.blast_radius is not None
    assert packet.blast_radius.lane == "medium"
    assert _run_lane(ctx) == packet.blast_radius.lane


def test_the_verification_tool_lane_is_low_for_a_proven_fix(tmp_path: Path) -> None:
    from mergecraft.mcp.verification import _run_lane

    ctx = _packet_ctx(tmp_path, title="fix: handle x", red_green=_evidence("proven"))
    no_receipt = _packet_ctx(tmp_path, title="fix: handle x")

    assert _run_lane(ctx) == "low"
    assert _run_lane(no_receipt) == "medium"


# ── run packet: the signal comes from ToolState.red_green + title/labels ─────


def _evidence(status: str) -> Any:
    return _rg().RedGreenEvidence(
        status=status,
        test_count=1 if status in {"proven", "not-proven"} else 0,
        artifact="red-green-receipt" if status != "not-declared" else None,
        run_url="https://github.com/acme/demo/actions/runs/88",
        detail=f"receipt {status}",
    )


def _packet_ctx(
    tmp_path: Path,
    *,
    title: str,
    labels: list[str] | None = None,
    red_green: Any = None,
    fix_labels: list[str] | None = None,
    operator_owned: bool = True,
    base_fix_labels: tuple[str, ...] | None = None,
) -> Any:
    """A packet-ready context; ``fix_labels`` is the run-start snapshot's ``fixLabels``.

    ``operator_owned`` says whether that snapshot is the operator's (base) config;
    ``base_fix_labels`` is what run start resolved from the base and stored on
    ``ToolState.fix_labels``.
    """
    from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
    from mergecraft.mcp.tool_state import ApprovalRecord, init_tool_state, primary_repo_state
    from mergecraft.modes import compute_modes
    from mergecraft.utils.github import GitHubClient

    tool_state = init_tool_state(owner="acme", name="demo", dir=str(tmp_path))
    diff_path = tmp_path / "pr-42.diff"
    diff_path.write_text(_DOCS_DIFF, encoding="utf-8")
    primary_repo_state(tool_state).diff_path = str(diff_path)
    tool_state.approval = ApprovalRecord(would_approve=True, sha="deadbeef")
    if red_green is not None:
        tool_state.red_green = red_green
    if base_fix_labels is not None:
        tool_state.fix_labels = base_fix_labels
    if hasattr(tool_state, "scope_declaration"):
        # Once declared scope lands (#1056 part 3) a run without one is ``scope.unknown``
        # at ``medium``; declare the diff's one path so only the fix proof moves the lane.
        ingest = import_module("mergecraft.requirements.ingest")
        tool_state.scope_declaration = ingest.ScopeDeclaration(
            declared=True, globs=("docs/guide.md",), source_ref="pr_description", rejected=()
        )
    snapshot = None
    if fix_labels is not None:
        from mergecraft.config.settings import default_settings
        from mergecraft.config.settings_snapshot import RepoSettingsSnapshot

        settings = default_settings()
        settings.review.fix_labels = list(fix_labels)
        snapshot = RepoSettingsSnapshot(
            settings=settings, config_hash="", repo_root=tmp_path, operator_owned=operator_owned
        )
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(
            event=PayloadEvent(trigger="pull_request", issue_number=42, is_pr=True, title=title),
        ),
        github=GitHubClient(token=""),
        modes=compute_modes("claude"),
        tool_state=tool_state,
        tmpdir=str(tmp_path),
        resolved_model="claude-sonnet-4-5",
        trust_tier="trusted",
        repo_settings_snapshot=snapshot,
        gh_event={
            "pull_request": {
                "number": 42,
                "title": title,
                "labels": [{"name": name} for name in (labels or [])],
                "base": {"sha": "1" * 40},
                "head": {"sha": "2" * 40},
            }
        },
    )


def _packet(tmp_path: Path, **kwargs: Any) -> Any:
    from mergecraft.evidence.run_packet import build_run_packet

    return build_run_packet(_packet_ctx(tmp_path, **kwargs), run_succeeded=True)


def _packet_codes(packet: Any) -> list[str]:
    assert packet.blast_radius is not None
    return [reason.code for reason in packet.blast_radius.reasons]


def test_a_fix_titled_run_with_a_proven_receipt_is_low(tmp_path: Path) -> None:
    packet = _packet(tmp_path, title="fix(ci): handle x", red_green=_evidence("proven"))

    assert "fix.proven" in _packet_codes(packet)
    assert packet.blast_radius.lane == "low"
    assert _gates(packet.blast_radius)["fix_proof"] is True


def test_a_fix_titled_run_without_receipt_evidence_is_no_receipt(tmp_path: Path) -> None:
    packet = _packet(tmp_path, title="fix: handle x")

    assert "fix.no-receipt" in _packet_codes(packet)
    assert packet.blast_radius.lane == "medium"
    assert _gates(packet.blast_radius)["fix_proof"] is False


@pytest.mark.parametrize(
    ("status", "code"),
    sorted(FAILING_STATUS_CODES.items()),
    ids=sorted(FAILING_STATUS_CODES),
)
def test_a_fix_titled_run_maps_the_recorded_status_to_its_code(
    tmp_path: Path, status: str, code: str
) -> None:
    packet = _packet(tmp_path, title="fix: handle x", red_green=_evidence(status))

    assert code in _packet_codes(packet)
    assert packet.blast_radius.lane == "medium"


@pytest.mark.parametrize(
    ("status", "code"),
    [
        ("invalid", "fix.receipt.invalid"),
        ("no-receipt", "fix.no-receipt"),
        ("mismatch", "fix.receipt.mismatch"),
    ],
)
def test_the_packet_reason_shows_the_recorded_evidence_detail(
    tmp_path: Path, status: str, code: str
) -> None:
    evidence = _evidence(status)
    packet = _packet(tmp_path, title="fix: handle x", red_green=evidence)

    assert packet.blast_radius is not None
    reasons = {reason.code: reason for reason in packet.blast_radius.reasons}
    assert evidence.detail in reasons[code].message


def test_a_feature_run_is_not_required(tmp_path: Path) -> None:
    packet = _packet(tmp_path, title="feat: add a thing")

    assert "fix.not-required" in _packet_codes(packet)
    assert packet.blast_radius.lane == "low"
    assert _gates(packet.blast_radius)["fix_proof"] is True


def test_a_default_fix_label_makes_the_run_a_fix(tmp_path: Path) -> None:
    packet = _packet(tmp_path, title="feat: add a thing", labels=["Bug"])

    assert "fix.no-receipt" in _packet_codes(packet)
    assert "fix.not-required" not in _packet_codes(packet)


def test_the_configured_fix_labels_replace_the_defaults(tmp_path: Path) -> None:
    custom = _packet(
        tmp_path, title="feat: add a thing", labels=["regression"], fix_labels=["regression"]
    )
    default_label = _packet(
        tmp_path, title="feat: add a thing", labels=["bug"], fix_labels=["regression"]
    )

    assert "fix.no-receipt" in _packet_codes(custom)
    assert "fix.not-required" in _packet_codes(default_label)


# ── fix labels come from the operator's base-side config only ───────────────


def test_tool_state_starts_with_no_resolved_fix_labels(tmp_path: Path) -> None:
    from mergecraft.mcp.tool_state import init_tool_state

    state = init_tool_state(owner="acme", name="demo", dir=str(tmp_path))

    assert hasattr(state, "fix_labels")
    assert state.fix_labels is None


def test_a_head_only_empty_fix_labels_cannot_switch_off_label_detection(tmp_path: Path) -> None:
    """A fork's head config sets ``fixLabels: []``; the ``bug`` label still marks a fix."""
    packet = _packet(
        tmp_path, title="feat: add a thing", labels=["bug"], fix_labels=[], operator_owned=False
    )

    assert "fix.no-receipt" in _packet_codes(packet)
    assert "fix.not-required" not in _packet_codes(packet)
    assert packet.blast_radius.lane == "medium"
    assert _gates(packet.blast_radius)["fix_proof"] is False


def test_a_head_only_fix_label_list_is_ignored_for_the_defaults(tmp_path: Path) -> None:
    hotfix = _packet(
        tmp_path,
        title="feat: add a thing",
        labels=["hotfix"],
        fix_labels=["hotfix"],
        operator_owned=False,
    )
    bug = _packet(
        tmp_path,
        title="feat: add a thing",
        labels=["bug"],
        fix_labels=["hotfix"],
        operator_owned=False,
    )

    assert "fix.not-required" in _packet_codes(hotfix)
    assert "fix.no-receipt" in _packet_codes(bug)


def test_an_operator_owned_snapshot_fix_label_list_is_honoured(tmp_path: Path) -> None:
    packet = _packet(
        tmp_path,
        title="feat: add a thing",
        labels=["hotfix"],
        fix_labels=["hotfix"],
        operator_owned=True,
    )

    assert "fix.no-receipt" in _packet_codes(packet)
    assert packet.blast_radius.lane == "medium"


def test_the_base_resolved_fix_labels_win_over_a_head_that_removes_them(tmp_path: Path) -> None:
    """Base ``fixLabels: [hotfix]`` resolved at run start; the head config drops it."""
    hotfix = _packet(
        tmp_path,
        title="feat: add a thing",
        labels=["hotfix"],
        fix_labels=[],
        operator_owned=False,
        base_fix_labels=("hotfix",),
    )
    bug = _packet(
        tmp_path,
        title="feat: add a thing",
        labels=["bug"],
        fix_labels=[],
        operator_owned=False,
        base_fix_labels=("hotfix",),
    )

    assert "fix.no-receipt" in _packet_codes(hotfix)
    assert "fix.not-required" in _packet_codes(bug)


def test_the_verification_tool_reads_the_same_base_side_fix_labels(tmp_path: Path) -> None:
    from mergecraft.mcp.verification import _run_lane

    head_only = _packet_ctx(
        tmp_path, title="feat: add a thing", labels=["bug"], fix_labels=[], operator_owned=False
    )
    base = _packet_ctx(
        tmp_path,
        title="feat: add a thing",
        labels=["hotfix"],
        fix_labels=[],
        operator_owned=False,
        base_fix_labels=("hotfix",),
    )

    assert _run_lane(head_only) == "medium"
    assert _run_lane(base) == "medium"


def test_a_proven_receipt_on_a_non_fix_run_is_still_not_required(tmp_path: Path) -> None:
    packet = _packet(tmp_path, title="docs: tidy", red_green=_evidence("proven"))

    assert "fix.not-required" in _packet_codes(packet)
    assert "fix.proven" not in _packet_codes(packet)


def test_the_fix_proof_adds_no_packet_section(tmp_path: Path) -> None:
    fix_packet = _packet(tmp_path, title="fix: handle x", red_green=_evidence("mismatch"))
    feature_packet = _packet(tmp_path, title="feat: x")

    fix_keys = set(fix_packet.model_dump(mode="json"))
    assert fix_keys == set(feature_packet.model_dump(mode="json"))
    assert "fix.receipt.mismatch" in _packet_codes(fix_packet)
    assert not any("red_green" in key or "fix_proof" in key for key in fix_keys)


def test_the_run_record_names_the_fix_code(tmp_path: Path) -> None:
    from mergecraft.findings.ledger import render_deterministic_review_block

    packet = _packet(tmp_path, title="fix: handle x")
    block = render_deterministic_review_block(packet=packet, trust_tier="trusted")
    lines = [line for line in block.splitlines() if "fix.no-receipt" in line]

    assert lines
    assert any(line.startswith("- **") for line in lines)


# ── approval gate: a checklist missing a GATE_ORDER gate was not fully measured ─


def _decided_packet(blast_radius: Any, *, files_changed: list[str]) -> Any:
    from mergecraft.agents.gates import TRUSTED_PACKET_DECIDED_BY
    from mergecraft.evidence.packet import (
        PACKET_SCHEMA_VERSION,
        AgentMetadata,
        Decision,
        MergeEvidencePacket,
    )

    return MergeEvidencePacket(
        schema_version=PACKET_SCHEMA_VERSION,
        change_id="acme/demo#42",
        agent=AgentMetadata(id="claude", version="0.0.0", model="claude-sonnet-4-5"),
        files_changed=files_changed,
        findings=[],
        deterministic_checks=[],
        blast_radius=blast_radius,
        decision=Decision(verdict="success", reason="clean", decided_by=TRUSTED_PACKET_DECIDED_BY),
    )


def _hand_built(
    *, lane: str, gates: dict[str, bool], categories: list[str], code: str = "baseline.clean"
) -> Any:
    from mergecraft.classify.blast_radius import BlastRadiusClassification

    return BlastRadiusClassification.model_validate(
        {
            "lane": lane,
            "auto_merge_lane": {"low": "eligible", "medium": "assisted"}[lane],
            "reason": "hand-built",
            "next_action": "hand-built",
            "categories": categories,
            "reasons": [{"code": code, "lane": lane, "message": "hand-built"}],
            "checklist": [{"gate": gate, "passed": passed} for gate, passed in gates.items()],
        }
    )


def _all_gates_true(*, without: str | None = None) -> dict[str, bool]:
    return {gate: True for gate in _api().GATE_ORDER if gate != without}


def test_a_low_packet_whose_checklist_lacks_fix_proof_is_refused() -> None:
    from mergecraft.agents.gates import _is_clean_pass, _is_low_risk_passing, select_rule_id

    gates = _all_gates_true(without="fix_proof")
    packet = _decided_packet(
        _hand_built(lane="low", gates=gates, categories=[]), files_changed=["docs/guide.md"]
    )

    assert "fix_proof" in _api().GATE_ORDER
    assert all(gates.values())
    assert _is_low_risk_passing(packet) is False
    assert _is_clean_pass(packet) is False
    assert select_rule_id(packet) not in {"low_risk_passing", "clean_pass"}


def test_a_low_packet_with_every_gate_true_selects_low_risk_passing() -> None:
    """Control: the completeness rule is not a blanket refusal."""
    from mergecraft.agents.gates import _is_low_risk_passing, select_rule_id

    gates = _all_gates_true()
    packet = _decided_packet(
        _hand_built(lane="low", gates=gates, categories=[]), files_changed=["docs/guide.md"]
    )

    assert "fix_proof" in gates
    assert _is_low_risk_passing(packet) is True
    assert select_rule_id(packet) == "low_risk_passing"


def test_a_medium_packet_whose_checklist_lacks_fix_proof_never_reaches_clean_pass() -> None:
    from mergecraft.agents.gates import _is_clean_pass, select_rule_id

    gates = _all_gates_true(without="fix_proof")
    gates["dependencies"] = False
    packet = _decided_packet(
        _hand_built(
            lane="medium", gates=gates, categories=["dependency_changes"], code="deps.changed"
        ),
        files_changed=["uv.lock"],
    )

    assert "fix_proof" in _api().GATE_ORDER
    assert _is_clean_pass(packet) is False
    assert select_rule_id(packet) != "clean_pass"


def test_a_medium_packet_with_every_gate_listed_reaches_clean_pass() -> None:
    from mergecraft.agents.gates import select_rule_id

    gates = _all_gates_true()
    gates["dependencies"] = False
    packet = _decided_packet(
        _hand_built(
            lane="medium", gates=gates, categories=["dependency_changes"], code="deps.changed"
        ),
        files_changed=["uv.lock"],
    )

    assert "fix_proof" in gates
    assert select_rule_id(packet) == "clean_pass"


def test_a_feature_run_packet_reaches_low_risk_passing(tmp_path: Path) -> None:
    """The production packet supplies the signal, so a clean feature run stays mergeable."""
    from mergecraft.agents.gates import _is_low_risk_passing

    packet = _packet(tmp_path, title="docs: tidy the guide")

    assert packet.blast_radius is not None
    assert _gates(packet.blast_radius)["fix_proof"] is True
    assert _is_low_risk_passing(packet) is True


def test_a_fix_run_packet_without_a_receipt_never_reaches_low_risk_passing(
    tmp_path: Path,
) -> None:
    from mergecraft.agents.gates import _is_low_risk_passing, select_rule_id

    packet = _packet(tmp_path, title="fix: handle x")

    assert packet.blast_radius is not None
    assert _gates(packet.blast_radius)["fix_proof"] is False
    assert _is_low_risk_passing(packet) is False
    assert select_rule_id(packet) != "low_risk_passing"


# ── docs ─────────────────────────────────────────────────────────────────────


def _section(text: str, title: str) -> str:
    heading = re.compile(r"^(?P<level>#{2,4})\s+(?P<title>.+?)\s*$")
    lines = text.splitlines()
    for index, line in enumerate(lines):
        match = heading.match(line)
        if match and match["title"].strip().lower() == title.lower():
            level = len(match["level"])
            body: list[str] = []
            for following in lines[index + 1 :]:
                nested = heading.match(following)
                if nested and len(nested["level"]) <= level:
                    break
                body.append(following)
            return "\n".join(body)
    raise AssertionError(f"no `{title}` section")


def test_the_blast_radius_doc_has_a_fix_proof_section() -> None:
    section = _section(
        (REPO_ROOT / "docs" / "blast-radius.md").read_text(encoding="utf-8"), "Fix proof"
    )

    assert "`fix_proof`" in section
    assert "redGreen" in section
    assert "redGreenArtifacts" not in section
    assert "fixLabels" in section
    assert "red-green-receipts.md" in section


def test_the_receipt_doc_documents_the_format_and_the_cap() -> None:
    path = REPO_ROOT / "docs" / "red-green-receipts.md"
    text = path.read_text(encoding="utf-8")

    assert "mergecraft.red-green/1" in text
    assert re.search(r"1\s?MB|1[ ,_]?000[ ,_]?000\s*bytes", text)
    assert "redGreen" in text
    assert "redGreenArtifacts" not in text
    assert "`workflow`" in text
    assert "fork" in text.lower()
    for key in ("base_sha", "head_sha", "tests"):
        assert f"`{key}`" in text or f'"{key}"' in text
    assert "${{" not in text


def test_review_checks_says_receipts_never_run_tests() -> None:
    text = (REPO_ROOT / "docs" / "REVIEW-CHECKS.md").read_text(encoding="utf-8")
    paragraphs = [p for p in re.split(r"\n\s*\n", text) if "redGreen" in p]

    assert paragraphs
    assert any(
        re.search(r"never\s+(?:run|runs|execute|executes)\b", p, re.IGNORECASE) for p in paragraphs
    )


def test_the_changelog_adds_the_receipts_under_unreleased() -> None:
    text = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    unreleased = text.split("## [Unreleased]", 1)[1].split("\n## [", 1)[0]
    added = unreleased.split("### Added", 1)[1].split("\n### ", 1)[0]

    assert "redGreen" in added
    assert "redGreenArtifacts" not in added
