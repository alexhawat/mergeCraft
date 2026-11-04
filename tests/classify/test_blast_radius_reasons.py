"""Coded lane reasons and the true/false/unknown checklist (#1056 part 2).

A blast-radius classification used to carry one free-text ``reason``: nobody
could tell which measurement drove the lane or which gates were never
measured. Each classification now carries ``reasons`` (stable dotted codes,
each with the lane it forces after repository overrides and the small
isolated-source carve-out) and a ``checklist`` of gates in a fixed order whose
``passed`` is ``True`` / ``False`` / ``None`` (not measured).

The new names are read through the ``api`` fixture (``import_module``) so the
suite collects before the production symbols exist.

Invariants pinned here:

- ``lane == max(r.lane for r in reasons)`` and ``reasons`` is never empty.
- ``auto_merge_lane == "eligible"`` exactly when every gate passed, exactly
  when ``lane == "low"``.
"""

from __future__ import annotations

import inspect
import re
from importlib import import_module
from typing import Any

import pytest
from pydantic import ValidationError

from mergecraft.classify.blast_radius import classify_blast_radius

_RANK: dict[str, int] = {"low": 0, "medium": 1, "high": 2}
_STATS: dict[str, object] = {"lines_added": 40, "lines_deleted": 10}
_SMALL: dict[str, object] = {"lines_added": 2, "lines_deleted": 1}
_LOCKED_GATE_ORDER: tuple[str, ...] = (
    "inputs",
    "migrations",
    "auth_security_payment",
    "secrets_config_deployment",
    "irreversible_infra",
    "public_api",
    "dependencies",
    "tests",
    "review_config",
)


@pytest.fixture
def api() -> Any:
    """Load the classifier module lazily so new names fail per test, not at collection."""
    return import_module("mergecraft.classify.blast_radius")


def _c(paths: list[str], stats: dict[str, object] | None = None) -> dict[str, Any]:
    """A complete change: changed paths plus diff statistics (defaults to a broad edit)."""
    return {"changed_paths": paths, "diff_stats": dict(_STATS if stats is None else stats)}


def _classify(change: Any, rule_set: Any = None) -> Any:
    """Classify a plain-dict table row (rows are untyped on purpose, some malformed)."""
    return classify_blast_radius(change, rule_set=rule_set)


def _reasons_by_code(result: Any) -> dict[str, Any]:
    return {reason.code: reason for reason in result.reasons}


def _gates(result: Any) -> dict[str, bool | None]:
    return {gate.gate: gate.passed for gate in result.checklist}


# (code, change, default lane, gate the code must fail — None when the code is low
# or the contract does not name a gate for it)
CODE_CASES: list[tuple[str, dict[str, Any], str, str | None]] = [
    ("signal.missing.paths", {"diff_stats": dict(_STATS)}, "medium", "inputs"),
    ("signal.missing.diff", {"changed_paths": ["docs/guide.md"]}, "medium", "inputs"),
    ("paths.migrations", _c(["migrations/0001_init.sql"]), "high", "migrations"),
    (
        "paths.auth",
        _c(["src/auth/session.py", "tests/auth/test_session.py"]),
        "high",
        "auth_security_payment",
    ),
    (
        "paths.security",
        _c(["src/security/tokens.py", "tests/test_tokens.py"]),
        "high",
        "auth_security_payment",
    ),
    (
        "paths.payment",
        _c(["src/payments/checkout.py", "tests/test_checkout.py"]),
        "high",
        "auth_security_payment",
    ),
    (
        "paths.permissions",
        _c(["src/permissions/policy.py", "tests/test_policy.py"]),
        "high",
        "auth_security_payment",
    ),
    ("paths.secrets_config", _c(["config/production.yaml"]), "high", "secrets_config_deployment"),
    (
        "paths.deployment",
        _c([".github/workflows/deploy.yml"]),
        "high",
        "secrets_config_deployment",
    ),
    ("paths.irreversible_infra", _c(["infra/terraform/network.tf"]), "high", "irreversible_infra"),
    (
        "diff.destructive_sql",
        _c(["docs/notes.md"], {"diff": "+DROP TABLE users;", "lines_added": 1, "lines_deleted": 0}),
        "high",
        "migrations",
    ),
    (
        "diff.secret_assignment",
        _c(
            ["docs/notes.md"], {"diff": "+password = hunter2", "lines_added": 1, "lines_deleted": 0}
        ),
        "high",
        "secrets_config_deployment",
    ),
    (
        "diff.irreversible_command",
        _c(
            ["docs/runbook.md"], {"diff": "+rm -rf /var/data", "lines_added": 1, "lines_deleted": 0}
        ),
        "high",
        "irreversible_infra",
    ),
    ("paths.public_api", _c(["src/pkg/__init__.py", "tests/test_pkg.py"]), "medium", "public_api"),
    ("deps.changed", _c(["uv.lock"]), "medium", "dependencies"),
    ("tests.missing", _c(["src/pkg/module.py"]), "medium", "tests"),
    ("paths.review_config", _c(["ruff.toml"]), "medium", "review_config"),
    ("source.changed", _c(["src/pkg/a.py", "tests/test_a.py"]), "medium", None),
    ("paths.generated", _c(["generated/client.py"]), "low", None),
    ("source.small_isolated", _c(["src/pkg/time.py"], _SMALL), "low", None),
    ("baseline.clean", _c(["docs/guide.md"], {"lines_added": 3, "lines_deleted": 0}), "low", None),
]
_CODE_IDS = [code for code, _change, _lane, _gate in CODE_CASES]


# ── each code fires with its default lane ────────────────────────────────────


@pytest.mark.parametrize(
    ("code", "change", "lane"),
    [(code, change, lane) for code, change, lane, _gate in CODE_CASES],
    ids=_CODE_IDS,
)
def test_each_code_fires_with_its_default_lane(
    code: str, change: dict[str, Any], lane: str
) -> None:
    reasons = _reasons_by_code(_classify(change))

    assert code in reasons
    assert reasons[code].lane == lane
    assert isinstance(reasons[code].message, str)
    assert reasons[code].message.strip()


@pytest.mark.parametrize(
    ("code", "lane"),
    [(code, lane) for code, _change, lane, _gate in CODE_CASES],
    ids=_CODE_IDS,
)
def test_each_case_lane_is_the_catalogue_default(api: Any, code: str, lane: str) -> None:
    assert api.LANE_REASON_CATALOGUE[code] == lane


def test_the_case_table_exercises_every_catalogue_code(api: Any) -> None:
    assert set(_CODE_IDS) == set(api.LANE_REASON_CATALOGUE)


@pytest.mark.parametrize(
    ("change", "gate"),
    [(change, gate) for _code, change, _lane, gate in CODE_CASES if gate is not None],
    ids=[code for code, _change, _lane, gate in CODE_CASES if gate is not None],
)
def test_a_code_above_low_fails_its_gate(change: dict[str, Any], gate: str) -> None:
    assert _gates(_classify(change))[gate] is False


@pytest.mark.parametrize(
    "change",
    [change for _code, change, lane, _gate in CODE_CASES if lane == "low"],
    ids=[code for code, _change, lane, _gate in CODE_CASES if lane == "low"],
)
def test_a_low_code_alone_passes_every_gate(change: dict[str, Any]) -> None:
    result = _classify(change)

    assert result.lane == "low"
    assert result.auto_merge_lane == "eligible"
    assert all(passed is True for passed in _gates(result).values())
    assert all(reason.lane == "low" for reason in result.reasons)


def test_source_changed_with_tests_is_medium_and_not_every_gate_passes() -> None:
    """A broad ``src/`` edit with tests has no category but still lifts the lane."""
    result = _classify(_c(["src/pkg/a.py", "tests/test_a.py"]))

    assert result.lane == "medium"
    assert _reasons_by_code(result)["source.changed"].lane == "medium"
    assert any(passed is not True for passed in _gates(result).values())


# ── checklist shape ──────────────────────────────────────────────────────────


def test_gate_order_starts_with_the_locked_gates(api: Any) -> None:
    order = tuple(api.GATE_ORDER)

    assert order[: len(_LOCKED_GATE_ORDER)] == _LOCKED_GATE_ORDER
    assert len(set(order)) == len(order)


@pytest.mark.parametrize(
    "change", [change for _code, change, _lane, _gate in CODE_CASES], ids=_CODE_IDS
)
def test_the_checklist_lists_every_gate_in_gate_order(api: Any, change: dict[str, Any]) -> None:
    result = _classify(change)
    names = [gate.gate for gate in result.checklist]

    # Gates fed by an optional signal (``scope``, #1056 part 3) are listed only when
    # the change set supplies that signal; every gate here is always listed, in order.
    assert names == [gate for gate in api.GATE_ORDER if gate in names]
    assert set(_LOCKED_GATE_ORDER) | {"source"} <= set(names)
    assert "scope" not in names


@pytest.mark.parametrize(
    "change",
    [change for code, change, _lane, _gate in CODE_CASES if not code.startswith("signal.")],
    ids=[code for code in _CODE_IDS if not code.startswith("signal.")],
)
def test_a_complete_change_measures_every_gate(change: dict[str, Any]) -> None:
    gates = _gates(_classify(change))

    assert gates["inputs"] is True
    assert all(isinstance(passed, bool) for passed in gates.values())


# ── invariants over a table of changes ───────────────────────────────────────

INVARIANT_CASES: list[tuple[str, dict[str, Any], dict[str, Any] | None]] = [
    *((f"code-{code}", change, None) for code, change, _lane, _gate in CODE_CASES),
    ("empty-change", {}, None),
    ("empty-paths", {"changed_paths": [], "diff_stats": {}}, None),
    ("migration-without-stats", {"changed_paths": ["migrations/0001_init.sql"]}, None),
    ("docs-empty-stats", {"changed_paths": ["docs/guide.md"], "diff_stats": {}}, None),
    ("generated-and-migration", _c(["src/generated/schema.py", "migrations/0002.sql"]), None),
    ("auth-and-deps", _c(["src/auth/login.py", "uv.lock"]), None),
    ("small-source-carve-out", _c(["src/pkg/time.py"], _SMALL), None),
    (
        "carve-out-blocked-by-source-override",
        _c(["src/pkg/time.py"], _SMALL),
        {"source_without_tests": {"lane": "medium"}},
    ),
    ("small-review-config-in-src", _c(["src/mergecraft/pkg/ruff.toml"], _SMALL), None),
    ("override-deps-to-low", _c(["uv.lock"]), {"dependency_changes": {"lane": "low"}}),
    ("override-review-config-to-low", _c(["ruff.toml"]), {"review_config": {"lane": "low"}}),
    (
        "override-source-to-high",
        _c(["src/mergecraft/utils/time.py"], {"files_changed": 1}),
        {"source_without_tests": {"lane": "high"}},
    ),
    (
        "override-generated-to-low-without-stats",
        {"changed_paths": ["generated/client.py"]},
        {"generated_files": {"lane": "low"}},
    ),
]
_INVARIANT_IDS = [case_id for case_id, _change, _rule_set in INVARIANT_CASES]
_INVARIANT_ARGS = [(change, rule_set) for _id, change, rule_set in INVARIANT_CASES]


@pytest.mark.parametrize(("change", "rule_set"), _INVARIANT_ARGS, ids=_INVARIANT_IDS)
def test_the_lane_is_the_max_over_reasons(
    change: dict[str, Any], rule_set: dict[str, Any] | None
) -> None:
    result = _classify(change, rule_set)

    assert len(result.reasons) >= 1
    assert result.lane == max((reason.lane for reason in result.reasons), key=_RANK.__getitem__)


@pytest.mark.parametrize(("change", "rule_set"), _INVARIANT_ARGS, ids=_INVARIANT_IDS)
def test_eligible_iff_every_gate_passed_iff_low(
    change: dict[str, Any], rule_set: dict[str, Any] | None
) -> None:
    result = _classify(change, rule_set)
    all_passed = all(gate.passed is True for gate in result.checklist)

    assert (result.auto_merge_lane == "eligible") is all_passed
    assert (result.lane == "low") is all_passed


@pytest.mark.parametrize(("change", "rule_set"), _INVARIANT_ARGS, ids=_INVARIANT_IDS)
def test_every_reason_code_is_in_the_catalogue(
    api: Any, change: dict[str, Any], rule_set: dict[str, Any] | None
) -> None:
    result = _classify(change, rule_set)

    assert {reason.code for reason in result.reasons} <= set(api.LANE_REASON_CATALOGUE)


def test_the_invariant_table_has_both_eligible_and_non_eligible_rows() -> None:
    """Guard against a vacuous equivalence: the table must exercise both sides."""
    lanes = {_classify(change, rule_set).auto_merge_lane for change, rule_set in _INVARIANT_ARGS}
    eligible_gates = [
        _gates(_classify(change, rule_set))
        for change, rule_set in _INVARIANT_ARGS
        if _classify(change, rule_set).auto_merge_lane == "eligible"
    ]

    assert {"eligible", "assisted", "forbidden"} <= lanes
    assert eligible_gates
    assert all(all(p is True for p in gates.values()) for gates in eligible_gates)


# ── overrides and the carve-out become visible reasons ───────────────────────


def test_an_override_to_low_is_a_visible_reason_and_passes_its_gate(api: Any) -> None:
    result = _classify(_c(["uv.lock"]), {"dependency_changes": {"lane": "low"}})
    reason = _reasons_by_code(result)["deps.changed"]

    assert result.lane == "low"
    assert result.auto_merge_lane == "eligible"
    assert reason.lane == "low"
    assert "repository override" in reason.message
    assert _gates(result)["dependencies"] is True
    assert api.LANE_REASON_CATALOGUE["deps.changed"] == "medium"


def test_an_override_up_raises_the_reason_lane_and_says_so() -> None:
    result = _classify(
        _c(["src/mergecraft/utils/time.py"], {"files_changed": 1}),
        {"source_without_tests": {"lane": "high"}},
    )
    reason = _reasons_by_code(result)["tests.missing"]

    assert result.lane == "high"
    assert reason.lane == "high"
    assert "repository override" in reason.message
    assert _gates(result)["tests"] is False


def test_a_review_config_override_cannot_lower_its_floor() -> None:
    result = _classify(_c(["ruff.toml"]), {"review_config": {"lane": "low"}})
    reason = _reasons_by_code(result)["paths.review_config"]

    assert result.lane == "medium"
    assert result.auto_merge_lane == "assisted"
    assert reason.lane == "medium"
    assert _gates(result)["review_config"] is False


def test_a_signal_floor_cannot_be_lowered_by_an_unknown_override_key() -> None:
    result = _classify({"changed_paths": ["docs/guide.md"]}, {"signal_missing": {"lane": "low"}})
    reason = _reasons_by_code(result)["signal.missing.diff"]

    assert result.lane == "medium"
    assert reason.lane == "medium"
    assert _gates(result)["inputs"] is False


def test_the_small_isolated_carve_out_is_a_reason_and_the_tests_gate_passes() -> None:
    result = _classify(_c(["src/pkg/time.py"], _SMALL))

    assert result.lane == "low"
    assert _reasons_by_code(result)["source.small_isolated"].lane == "low"
    assert _gates(result)["tests"] is True
    assert all(reason.lane == "low" for reason in result.reasons)


def test_a_source_override_blocks_the_carve_out_and_fails_the_tests_gate() -> None:
    result = _classify(
        _c(["src/pkg/time.py"], _SMALL), {"source_without_tests": {"lane": "medium"}}
    )

    assert result.lane == "medium"
    assert _reasons_by_code(result)["tests.missing"].lane == "medium"
    assert _gates(result)["tests"] is False


def test_review_config_under_src_is_not_carved_out() -> None:
    result = _classify(_c(["src/mergecraft/pkg/ruff.toml"], _SMALL))

    assert result.lane == "medium"
    assert _reasons_by_code(result)["paths.review_config"].lane == "medium"
    assert _gates(result)["review_config"] is False


def test_a_high_code_wins_over_a_low_generated_reason() -> None:
    result = _classify(_c(["src/generated/schema.py", "migrations/0002.sql"]))
    reasons = _reasons_by_code(result)

    assert result.lane == "high"
    assert result.auto_merge_lane == "forbidden"
    assert reasons["paths.migrations"].lane == "high"
    assert reasons["paths.generated"].lane == "low"


# ── compatibility fields stay ────────────────────────────────────────────────


def test_the_rendered_reason_names_every_code_and_keeps_the_sentence() -> None:
    result = _classify(_c(["migrations/0001_init.sql", "uv.lock"]))

    for reason in result.reasons:
        assert reason.code in result.reason
    assert "Detected blast-radius categories" in result.reason
    assert "migrations" in result.categories
    assert result.next_action


def test_a_missing_signal_reason_keeps_the_missing_input_sentence() -> None:
    result = _classify({"changed_paths": ["docs/guide.md"]})

    assert "signal.missing.diff" in result.reason
    assert "Missing classifier input: diff_stats." in result.reason
    assert "signal_missing" in result.categories


# ── typed models ─────────────────────────────────────────────────────────────


def test_lane_reason_carries_code_lane_and_message(api: Any) -> None:
    reason = api.LaneReason(code="deps.changed", lane="medium", message="dependency manifest")

    assert (reason.code, reason.lane, reason.message) == (
        "deps.changed",
        "medium",
        "dependency manifest",
    )


@pytest.mark.parametrize(
    ("payload", "loc"),
    [
        ({"code": "deps.changed", "lane": "critical", "message": "m"}, "lane"),
        ({"code": "deps.changed", "lane": "low", "message": "m", "severity": "x"}, "severity"),
        ({"lane": "low", "message": "m"}, "code"),
    ],
    ids=["unknown-lane", "extra-field-forbidden", "missing-code"],
)
def test_lane_reason_rejects_a_malformed_row(api: Any, payload: dict[str, Any], loc: str) -> None:
    with pytest.raises(ValidationError) as excinfo:
        api.LaneReason.model_validate(payload)

    assert any(loc in error["loc"] for error in excinfo.value.errors())


@pytest.mark.parametrize("passed", [True, False, None])
def test_checklist_gate_accepts_true_false_and_unknown(api: Any, passed: bool | None) -> None:
    gate = api.ChecklistGate(gate="tests", passed=passed)

    assert gate.gate == "tests"
    assert gate.passed is passed
    assert api.ChecklistGate.model_validate_json(gate.model_dump_json()).passed is passed


def test_an_unmeasured_gate_serialises_as_json_null() -> None:
    result = _classify({"changed_paths": ["docs/guide.md"]})
    dumped = result.model_dump(mode="json")

    assert {"gate": "tests", "passed": None} in dumped["checklist"]
    assert {"gate": "inputs", "passed": False} in dumped["checklist"]


def test_a_classification_round_trips_reasons_and_checklist() -> None:
    result = _classify(_c(["migrations/0001_init.sql"]))
    restored = type(result).model_validate_json(result.model_dump_json())

    assert restored.reasons == result.reasons
    assert restored.checklist == result.checklist
    assert restored == result


# ── seams: the run's diff classifier and the run record ──────────────────────

_MIGRATION_DIFF = """\
diff --git a/migrations/0001_init.sql b/migrations/0001_init.sql
new file mode 100644
--- /dev/null
+++ b/migrations/0001_init.sql
@@ -0,0 +1,2 @@
+CREATE TABLE widgets (id INTEGER PRIMARY KEY);
+CREATE INDEX widgets_id ON widgets (id);
"""


def _classify_run(diff_text: str) -> Any:
    """Call the run's diff classifier with an undeclared scope once it requires one.

    #1056 part 3 makes ``scope`` a required keyword on ``classify_run_blast_radius``;
    an undeclared signal leaves every part-2 gate exactly as before.
    """
    from mergecraft.evidence.run_packet import classify_run_blast_radius

    if "scope" in inspect.signature(classify_run_blast_radius).parameters:
        undeclared = {"declared": False, "globs": [], "invalid": False}
        return classify_run_blast_radius(diff_text, scope=undeclared)
    return classify_run_blast_radius(diff_text)


def test_the_run_diff_classifier_emits_reasons_and_a_measured_checklist() -> None:
    result: Any = _classify_run(_MIGRATION_DIFF)

    assert result is not None
    assert _reasons_by_code(result)["paths.migrations"].lane == "high"
    assert _gates(result)["inputs"] is True
    assert _gates(result)["migrations"] is False


def _record_for(paths: list[str]) -> str:
    from mergecraft.evidence.build import build_packet
    from mergecraft.findings.ledger import render_deterministic_review_block

    packet = build_packet(
        change_id="acme/demo#1056",
        agent_id="claude",
        agent_version="0.0.1",
        model="claude-sonnet-4-5",
        files_changed=paths,
        findings=[],
        deterministic_checks=[],
        blast_radius=classify_blast_radius({"changed_paths": paths, "diff_stats": dict(_STATS)}),
    )
    return render_deterministic_review_block(packet=packet, trust_tier="trusted")


def test_the_run_record_prints_the_lane_and_its_codes_on_one_line() -> None:
    block = _record_for(["migrations/0001_init.sql", "src/auth/session.py"])
    lines = [line for line in block.splitlines() if "paths.migrations" in line]

    assert len(lines) == 1
    assert "paths.auth" in lines[0]
    assert "high" in lines[0]


def test_the_run_record_line_follows_the_classification() -> None:
    block = _record_for(["ruff.toml"])
    lines = [line for line in block.splitlines() if "paths.review_config" in line]

    assert len(lines) == 1
    assert "medium" in lines[0]
    assert "paths.migrations" not in block


# ── a generated path exempts only itself ─────────────────────────────────────

_BIG: dict[str, object] = {"lines_added": 400, "lines_deleted": 50}

# (id, changed paths, whether a test changed)
GENERATED_SIBLING_CASES: list[tuple[str, list[str], bool]] = [
    (
        "docs-generated-with-tests",
        ["src/big.py", "tests/test_big.py", "docs/generated/api.md"],
        True,
    ),
    ("docs-generated-without-tests", ["src/big.py", "docs/generated/api.md"], False),
    ("src-generated-without-tests", ["src/big.py", "src/generated/pb.py"], False),
    ("src-generated-with-tests", ["src/big.py", "tests/test_big.py", "src/generated/pb.py"], True),
]


@pytest.mark.parametrize(
    ("paths", "has_tests"),
    [(paths, has_tests) for _id, paths, has_tests in GENERATED_SIBLING_CASES],
    ids=[case_id for case_id, _paths, _has_tests in GENERATED_SIBLING_CASES],
)
def test_a_generated_sibling_does_not_mask_a_source_change(
    paths: list[str], has_tests: bool
) -> None:
    result = _classify(_c(paths, _BIG))
    reasons = _reasons_by_code(result)

    assert result.lane == "medium"
    assert result.auto_merge_lane == "assisted"
    assert reasons["source.changed"].lane == "medium"
    assert _gates(result)["source"] is False
    if has_tests:
        assert _gates(result)["tests"] is True
    else:
        assert reasons["tests.missing"].lane == "medium"
        assert _gates(result)["tests"] is False


@pytest.mark.parametrize(
    "paths",
    [
        ["src/generated/pb.py", "docs/generated/api.md"],
        ["src/generated/pb.py"],
        ["generated/client.py", "src/generated/models.py"],
    ],
    ids=["src-and-docs-generated", "src-generated-only", "two-generated-trees"],
)
def test_a_change_of_only_generated_paths_stays_low(paths: list[str]) -> None:
    result = _classify(_c(paths, _BIG))
    reasons = _reasons_by_code(result)

    assert result.lane == "low"
    assert result.auto_merge_lane == "eligible"
    assert reasons["paths.generated"].lane == "low"
    assert all(reason.lane == "low" for reason in result.reasons)


# ── the carve-out does not apply beside a high reason ────────────────────────


@pytest.mark.parametrize(
    ("paths", "high_code"),
    [
        # One path, so the single-file size check passes and only the high-reason
        # guard keeps the carve-out away.
        (["src/auth/x.py"], "paths.auth"),
        (["src/pkg/mod.py", "migrations/0001.sql"], "paths.migrations"),
    ],
    ids=["single-high-risk-source", "source-beside-migration"],
)
def test_the_carve_out_is_not_emitted_beside_a_high_reason(
    paths: list[str], high_code: str
) -> None:
    result = _classify(_c(paths, _SMALL))
    reasons = _reasons_by_code(result)
    gates = _gates(result)

    assert result.lane == "high"
    assert reasons[high_code].lane == "high"
    assert reasons["tests.missing"].lane == "medium"
    assert "source.small_isolated" in set(_CODE_IDS)
    assert "source.small_isolated" not in reasons
    assert gates["tests"] is False
    assert gates["source"] is False


# ── the run-record line names the gates that were not measured ───────────────


def _record_for_change(change: dict[str, Any]) -> tuple[str, Any]:
    from mergecraft.evidence.build import build_packet
    from mergecraft.findings.ledger import render_deterministic_review_block

    classification = _classify(change)
    raw_paths = change.get("changed_paths")
    packet = build_packet(
        change_id="acme/demo#1056",
        agent_id="claude",
        agent_version="0.0.1",
        model="claude-sonnet-4-5",
        files_changed=list(raw_paths) if isinstance(raw_paths, list) else [],
        findings=[],
        deterministic_checks=[],
        blast_radius=classification,
    )
    return render_deterministic_review_block(packet=packet, trust_tier="trusted"), classification


def test_the_run_record_line_lists_the_unmeasured_gates() -> None:
    block, classification = _record_for_change({"changed_paths": ["docs/guide.md"]})
    lines = [line for line in block.splitlines() if "signal.missing.diff" in line]
    unmeasured = [gate.gate for gate in classification.checklist if gate.passed is None]

    assert len(lines) == 1
    assert "not measured:" in lines[0]
    suffix = lines[0].split("not measured:", 1)[1]
    assert unmeasured
    assert "tests" in unmeasured
    assert re.findall(r"`([^`]+)`", suffix) == unmeasured


def test_the_run_record_line_has_no_suffix_when_every_gate_is_measured() -> None:
    block, classification = _record_for_change(_c(["migrations/0001_init.sql"]))
    lines = [line for line in block.splitlines() if "paths.migrations" in line]

    assert all(gate.passed is not None for gate in classification.checklist)
    assert len(lines) == 1
    assert "high" in lines[0]
    assert "not measured" not in lines[0]
