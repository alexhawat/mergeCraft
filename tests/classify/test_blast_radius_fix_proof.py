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

    assert set(api.FixProofSignal.__annotations__) == {"required", "status"}
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


@pytest.mark.parametrize("status", ALL_STATUSES)
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


def test_a_fix_whose_receipt_lists_no_tests_never_passes() -> None:
    result = _classify(_change("no-tests"))
    fix_reasons = _fix_reasons(result)

    assert result.lane == "medium"
    assert result.auto_merge_lane != "eligible"
    assert len(fix_reasons) == 1
    assert fix_reasons[0].code in set(FIX_CODES) - {"fix.proven", "fix.not-required"}
    assert fix_reasons[0].lane == "medium"
    assert _gates(result)["fix_proof"] is False


def test_an_undeclared_receipt_on_a_fix_names_the_setting() -> None:
    reason = _codes(_classify(_change("not-declared")))["fix.no-receipt"]

    assert "redGreenArtifacts" in reason.message


def test_a_missing_receipt_message_differs_from_an_undeclared_one() -> None:
    missing = _codes(_classify(_change("no-receipt")))["fix.no-receipt"]
    undeclared = _codes(_classify(_change("not-declared")))["fix.no-receipt"]

    assert missing.message != undeclared.message
    assert "redGreenArtifacts" in undeclared.message


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


# ── no signal supplied ───────────────────────────────────────────────────────


def test_no_signal_leaves_the_part2_classification_unchanged() -> None:
    """No ``fix_proof`` key (the verification tool's diff-only call): no ``fix.*`` reason.

    The part-2 tests require a complete low change without the signal to pass
    every gate and stay ``eligible``; this pins the same for the docs change, and
    that a supplied signal is what adds the ``fix.*`` reason.
    """
    without = _classify(dict(_DOCS))
    with_signal = _classify(_change("not-proven"))

    assert [reason.code for reason in without.reasons] == ["baseline.clean"]
    assert without.lane == "low"
    assert without.auto_merge_lane == "eligible"
    assert [gate.gate for gate in without.checklist] == list(_api().GATE_ORDER)
    assert "fix.not-proven" in _codes(with_signal)


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
    assert [gate.gate for gate in result.checklist] == list(_api().GATE_ORDER)


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


def test_the_run_diff_classifier_passes_the_signal_through() -> None:
    from mergecraft.evidence.run_packet import classify_run_blast_radius

    proven = classify_run_blast_radius(_DOCS_DIFF, fix_proof={"required": True, "status": "proven"})
    unproven = classify_run_blast_radius(
        _DOCS_DIFF, fix_proof={"required": True, "status": "not-proven"}
    )

    assert proven is not None
    assert unproven is not None
    assert proven.lane == "low"
    assert "fix.proven" in _codes(proven)
    assert unproven.lane == "medium"
    assert "fix.not-proven" in _codes(unproven)


def test_the_run_diff_classifier_takes_the_signal_by_keyword_only() -> None:
    from mergecraft.evidence.run_packet import classify_run_blast_radius

    signal = {"required": True, "status": "proven"}

    with pytest.raises(TypeError):
        classify_run_blast_radius(_DOCS_DIFF, signal)
    assert classify_run_blast_radius(_DOCS_DIFF, fix_proof=signal) is not None


def test_the_run_diff_classifier_without_a_signal_adds_no_fix_reason() -> None:
    from mergecraft.evidence.run_packet import classify_run_blast_radius

    result = classify_run_blast_radius(_DOCS_DIFF, fix_proof=None)

    assert result is not None
    assert [reason.code for reason in result.reasons] == ["baseline.clean"]


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
) -> Any:
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
    snapshot = None
    if fix_labels is not None:
        from mergecraft.config.settings import default_settings
        from mergecraft.config.settings_snapshot import RepoSettingsSnapshot

        settings = default_settings()
        settings.review.fix_labels = list(fix_labels)
        snapshot = RepoSettingsSnapshot(settings=settings, config_hash="", repo_root=tmp_path)
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
    assert "redGreenArtifacts" in section
    assert "fixLabels" in section
    assert "red-green-receipts.md" in section


def test_the_receipt_doc_documents_the_format_and_the_cap() -> None:
    path = REPO_ROOT / "docs" / "red-green-receipts.md"
    text = path.read_text(encoding="utf-8")

    assert "mergecraft.red-green/1" in text
    assert re.search(r"1\s?MB|1[ ,_]?000[ ,_]?000\s*bytes", text)
    assert "redGreenArtifacts" in text
    for key in ("base_sha", "head_sha", "tests"):
        assert f"`{key}`" in text or f'"{key}"' in text
    assert "${{" not in text


def test_review_checks_says_receipts_never_run_tests() -> None:
    text = (REPO_ROOT / "REVIEW-CHECKS.md").read_text(encoding="utf-8")
    paragraphs = [p for p in re.split(r"\n\s*\n", text) if "redGreenArtifacts" in p]

    assert paragraphs
    assert any(
        re.search(r"never\s+(?:run|runs|execute|executes)\b", p, re.IGNORECASE) for p in paragraphs
    )


def test_the_changelog_adds_the_receipts_under_unreleased() -> None:
    text = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    unreleased = text.split("## [Unreleased]", 1)[1].split("\n## [", 1)[0]
    added = unreleased.split("### Added", 1)[1].split("\n### ", 1)[0]

    assert "redGreenArtifacts" in added
