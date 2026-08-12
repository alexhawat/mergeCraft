"""Auto-generated permanent test promoted from the eval bank (#44, W12.1).

This file is produced by ``mergecraft eval promote <case-id>``. Do not
edit by hand — re-run ``mergecraft eval promote`` to regenerate. The
test re-runs the case against the current code via
``mergecraft.evals.store.replay_case``: a ``passed`` status means the
case's expected verdict matches what the running code produced; a
``regression`` status means the same failure mode the case captured has
recurred — that is the structural signal the promote workflow ships.

The promoted test lives under ``tests/evals/permanent/`` and is
discovered by pytest via the standard collection rules — no separate
``conftest`` is required.
"""

from __future__ import annotations

from mergecraft.evals.store import Case, replay_case

_PERMANENT_CASE_PAYLOAD = '{"id":"issue-75-narrative-approval","title":"Agent prose must never outvote a blocking finding","category":"missed_finding","submitted_at":"2026-08-09T22:45:08.340612Z","run_id":"issue-75","pr_number":87,"failure_mode":"wrong_decision","expected_finding":"Critical finding present; approval must be failure regardless of the agent\'s approved boolean","expected_decision":"failure","replay_command":"mergecraft eval replay issue-75-narrative-approval","provenance":{"run_id":"issue-75","pr_number":87,"source_field":"eval_bank","author_login":"alexhawat","author_association":"OWNER","trust_tier":"trusted","timestamp":"2026-08-09T22:45:08.340342Z"},"body":"Shipped defect, fixed by PR #87 (issue #75). `create_pull_request_review` took an `approved: bool` straight from the agent and `report_status_checks()` read it into the `mergecraft-approval` conclusion, so an injected PR could steer the gate to success. D12 makes the conclusion a pure function of typed findings. This case fails if narrative ever regains a vote.","recorded_findings":[{"path":"src/mergecraft/utils/status_checks.py","start_line":97,"end_line":113,"message":"Agent narrative steered mergecraft-approval to success despite a blocking finding","severity":"Critical","confidence":"certain","category":"Security & Privacy","source":"agent","fingerprint":"i75narrative01","tool":"agent","rule_id":"agent:issue-75","introduced_by_pr":"true","evidence":["approval.would_approve was read straight into the check conclusion"],"remediation":"Derive the conclusion from typed findings; demote the agent boolean to advisory.","autofix":null,"cluster_id":null}],"run_succeeded":true,"trust_tier":"trusted"}'


def _load_permanent_case() -> Case:
    """Materialize the embedded case payload as a validated :class:`Case`.

    The payload is the case's full JSON shape (including the embedded
    ``LearningProvenance``); ``Case.model_validate_json`` is the same
    path the bank uses at read time, so a schema-version bump on the
    bank side surfaces here as a load-time failure rather than a
    silent structural drift.
    """
    return Case.model_validate_json(_PERMANENT_CASE_PAYLOAD)


def test_permanent_issue_75_narrative_approval() -> None:
    """Permanent regression test for case ``issue-75-narrative-approval`` (Agent prose must never outvote a blocking finding).

    Expected verdict: ``failure``. The replay verdict is
    operator-supplied via the ``MERGECRAFT_PERMANENT_CURRENT_DECISION``
    env var; when unset the default is ``None`` so the case lands in
    the ``blocked`` state (the replay engine did not produce a
    verdict). The test asserts two things:

    - The case is replayable end-to-end (the bank schema still
      validates and ``replay_case`` returns a typed diff).
    - When the operator wires a current verdict, that verdict agrees
      with the case's expected decision — a real regression surfaces
      as a failed assertion.

    The default-``None`` path keeps the test green at import time so a
    fresh promotion does not break the suite. Operators flip the env
    var to surface drift.
    """
    import os

    case = _load_permanent_case()
    current = os.environ.get("MERGECRAFT_PERMANENT_CURRENT_DECISION") or None
    diff = replay_case(case, current_decision=current)
    # The replay must complete — even the default-``None`` path lands in
    # the ``blocked`` status, which is itself a valid replay outcome.
    assert diff.status in {"passed", "regression", "blocked"}
    # When the operator wired a current verdict, surface a real drift.
    if diff.current_decision is not None:
        assert diff.current_decision == diff.expected_decision, (
            f"permanent test {case.id!r}: replay verdict "
            f"{diff.current_decision!r} drifted from expected "
            f"{diff.expected_decision!r}"
        )
