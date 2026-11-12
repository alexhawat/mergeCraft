"""W14 / W17 — adversarial eval corpora (#363 / D15).

Seeds already exist in ``mergecraft.evals.adversarial`` and
``tests/security/hostile_corpus.py``. This wave wires three corpora into
``mergecraft eval gate`` so a regression blocks a release.

Out of scope: egress/SSRF (#362); expanding the human/reference review
corpus; publishing precision/recall numbers (#140 — do not close).
"""

from __future__ import annotations

from pathlib import Path

from tests.ci.workflow_support import REPO_ROOT
from tests.support.cc_batch import invoke, plain
from tests.support.cd_batch import (
    ADVERSARIAL_CORPORA_MODULE,
    ADVERSARIAL_CORPUS_KINDS,
    ISSUE_140_GATE_METRICS,
    require_callable,
    require_module,
)


def test_issue_140_gate_metrics_remain_the_published_numbers() -> None:
    """D15 current state — do not close or retarget #140 precision/recall."""
    from mergecraft.evals import gate as gate_mod

    source = Path(gate_mod.__file__).read_text(encoding="utf-8")
    assert "decision_replay_pass_rate" in source
    assert "unsafe_approval_rate" in source
    assert "corpus_confirmed_precision" in source
    assert "#140" in source or "Detection" in source


def test_three_adversarial_corpora_are_named_and_non_empty() -> None:
    """Happy: prompt-injection, malicious-repo, and malicious-ticket corpora."""
    module = require_module(ADVERSARIAL_CORPORA_MODULE)
    kinds = frozenset(module.ADVERSARIAL_CORPUS_KINDS)
    assert kinds == ADVERSARIAL_CORPUS_KINDS
    discover = require_callable(module, "discover_adversarial_corpora")
    found = discover()
    names = {getattr(item, "kind", None) or item.get("kind") for item in found}
    assert names == ADVERSARIAL_CORPUS_KINDS
    for item in found:
        cases = getattr(item, "cases", None)
        if cases is None:
            cases = item.get("cases")
        assert cases, f"empty {item} corpus is a failure, never a vacuous pass"


def test_adversarial_corpora_stay_out_of_the_human_reference_bank() -> None:
    """Edge: the three corpora are not top-level ``evals/cases/*.md`` files."""
    module = require_module(ADVERSARIAL_CORPORA_MODULE)
    discover = require_callable(module, "discover_adversarial_corpora")
    bank = REPO_ROOT / "evals" / "cases"
    human_ids = {path.stem for path in bank.glob("*.md")}
    for item in discover():
        cases = getattr(item, "cases", None) or item.get("cases")
        for case in cases:
            case_id = getattr(case, "case_id", None) or case.get("case_id") or str(case)
            assert Path(str(case_id)).stem not in human_ids or "/" in str(case_id)


def test_eval_gate_fails_the_release_on_an_adversarial_regression(tmp_path: Path) -> None:
    """Functional: ``mergecraft eval gate`` blocks when an adversarial case regresses."""
    module = require_module(ADVERSARIAL_CORPORA_MODULE)
    run_gate = require_callable(module, "eval_adversarial_gate")
    report = run_gate(candidate_failures=("prompt_injection:forge-fence",), bank=tmp_path)
    passed = getattr(report, "passed", None)
    if passed is None:
        passed = report.get("passed")
    assert passed is False
    result = invoke("eval", "gate", "--help")
    help_text = plain(result.stdout + result.stderr).casefold()
    assert "adversarial" in help_text


def test_cli_source_path_is_treated_as_attacker_controlled_input() -> None:
    """Happy: reviewing a local path or public URL is untrusted input."""
    module = require_module(ADVERSARIAL_CORPORA_MODULE)
    classify = require_callable(module, "classify_cli_source_trust")
    local = classify(source=".", kind="path")
    url = classify(source="https://example.com/repo.git", kind="url")
    for result in (local, url):
        trust = getattr(result, "trust_tier", None) or result.get("trust_tier")
        assert trust in {"untrusted", "attacker-controlled", "external"}


def test_adversarial_gate_does_not_publish_precision_recall_numbers() -> None:
    """D15 — corpora land; #140 precision/recall numbers are not published here."""
    module = require_module(ADVERSARIAL_CORPORA_MODULE)
    run_gate = require_callable(module, "eval_adversarial_gate")
    report = run_gate(candidate_failures=(), bank=None)
    payload = report.model_dump() if hasattr(report, "model_dump") else dict(report)
    for banned in ("precision", "recall", "f1", "corpus_confirmed_precision"):
        assert banned not in payload
    overlapping = ISSUE_140_GATE_METRICS & set(payload)
    assert not overlapping


def test_gate_evaluates_every_corpus_kind(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Each of the three corpora is exercised; a break in any one fails the gate."""
    from mergecraft.evals import adversarial_corpora as mod

    seen: set[str] = set()
    real = mod._fence_holds

    def spy(case):  # type: ignore[no-untyped-def]
        seen.add(case.kind)
        return real(case)

    monkeypatch.setattr(mod, "_fence_holds", spy)
    report = mod.eval_adversarial_gate()
    assert report.passed is True
    assert seen == {"prompt_injection", "malicious_repository", "malicious_ticket_comment"}


def test_gate_fails_when_a_non_prompt_injection_corpus_regresses(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from mergecraft.evals import adversarial_corpora as mod

    monkeypatch.setattr(mod, "_hook_stays_inert", lambda case: False)
    monkeypatch.setattr(mod, "_fence_holds", lambda case: case.kind != "malicious_ticket_comment")
    report = mod.eval_adversarial_gate()
    assert report.passed is False
    assert "malicious_repository:git-hook" in report.failed_cases
    assert "malicious_ticket_comment:issue-body" in report.failed_cases


def test_reported_failure_does_not_suppress_the_harness(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from mergecraft.evals import adversarial_corpora as mod

    monkeypatch.setattr(
        mod, "_fence_holds", lambda case: case.case_id != "prompt_injection:forge-fence"
    )
    report = mod.eval_adversarial_gate(candidate_failures=("malicious_repository:hostile-readme",))
    assert set(report.failed_cases) == {
        "malicious_repository:hostile-readme",
        "prompt_injection:forge-fence",
    }


def test_hostile_hook_stays_inert_under_the_hardened_argv() -> None:
    from mergecraft.evals.adversarial_corpora import (
        _hook_stays_inert,
        discover_adversarial_corpora,
    )

    case = next(
        c
        for corpus in discover_adversarial_corpora()
        for c in corpus.cases
        if c.case_id == "malicious_repository:git-hook"
    )
    assert _hook_stays_inert(case) is True
