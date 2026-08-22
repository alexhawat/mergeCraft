"""Synthetic recall-pass corpus fixtures for convergence eval gates (RC10, W7)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from mergecraft.evals.convergence import ConvergenceRound

RECALL_CORPUS_DIFF: Final[str] = """\
diff --git a/src/app.py b/src/app.py
index 1111111..2222222 100644
--- a/src/app.py
+++ b/src/app.py
@@ -10,3 +10,6 @@ def handler():
     pass
+    timeout = None
+    return timeout
diff --git a/src/util.py b/src/util.py
index 3333333..4444444 100644
--- a/src/util.py
+++ b/src/util.py
@@ -40,3 +40,5 @@ def helper():
     pass
+    cache = {}
+    return cache
"""


def recall_corpus_body(label: str) -> str:
    return f"{label} — recall pass corpus fixture."


def recall_case_id(index: int) -> str:
    return f"recall-pass-corpus-{index:03d}"


def recall_corpus_cases() -> list[tuple[str, str, str]]:
    return [
        (
            recall_case_id(1),
            recall_corpus_body("missing timeout on retry"),
            recall_corpus_body("unchecked null before return"),
        ),
        (
            recall_case_id(2),
            recall_corpus_body("race when claiming row"),
            recall_corpus_body("retry loop never assigns timeout"),
        ),
        (
            recall_case_id(3),
            recall_corpus_body("stale cache key after rename"),
            recall_corpus_body("caller still imports removed symbol"),
        ),
    ]


def recall_round_one(
    *,
    case_id: str,
    drafted_body: str,
    missed_body: str,
    with_recall: bool,
) -> ConvergenceRound:
    from mergecraft.evals.convergence import ConvergenceRound
    from mergecraft.findings.ledger import FindingLedger
    from mergecraft.review_taxonomy import finding_fingerprint

    path = "src/app.py"
    drafted_fp = finding_fingerprint(path=path, body=drafted_body)
    missed_fp = finding_fingerprint(path="src/util.py", body=missed_body)
    drafted_row = {
        "fingerprint": drafted_fp,
        "path": path,
        "start_line": 12,
        "end_line": 12,
        "body": drafted_body,
    }
    missed_row = {
        "fingerprint": missed_fp,
        "path": "src/util.py",
        "start_line": 42,
        "end_line": 42,
        "body": missed_body,
    }
    ledger = FindingLedger()
    ledger.record(drafted_fp, "open", source=case_id, round_index=1)
    generated = [drafted_fp]
    findings = [drafted_row]
    if with_recall:
        ledger.record(
            missed_fp,
            "deferred",
            source=case_id,
            round_index=1,
            reason="path:src/util.py",
        )
        generated.append(missed_fp)
        findings.append(missed_row)
    return ConvergenceRound(
        round_index=1,
        ledger=ledger,
        findings=findings,
        generated_fingerprints=generated,
        diff_text=RECALL_CORPUS_DIFF,
    )


def recall_round_two(*, case_id: str, missed_body: str) -> ConvergenceRound:
    from mergecraft.evals.convergence import ConvergenceRound
    from mergecraft.findings.ledger import FindingLedger
    from mergecraft.review_taxonomy import finding_fingerprint

    missed_fp = finding_fingerprint(path="src/util.py", body=missed_body)
    ledger = FindingLedger()
    ledger.record(missed_fp, "open", source=case_id, round_index=2)
    return ConvergenceRound(
        round_index=2,
        ledger=ledger,
        findings=[
            {
                "fingerprint": missed_fp,
                "path": "src/util.py",
                "start_line": 42,
                "end_line": 42,
                "body": missed_body,
            }
        ],
        generated_fingerprints=[missed_fp],
        diff_text=RECALL_CORPUS_DIFF,
    )


__all__ = [
    "RECALL_CORPUS_DIFF",
    "recall_case_id",
    "recall_corpus_body",
    "recall_corpus_cases",
    "recall_round_one",
    "recall_round_two",
]
