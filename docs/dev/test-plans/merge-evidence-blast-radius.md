# Merge evidence & gating — Batch B (blast radius) test plan (WB-T RED)

Wave plan: `.ignorelocal/waves/issues-merge-evidence-gating-wave-plan.md`
Worktree: `mergecraft-evi-b-blast` @ `wave/evi-b-blast`
Tests: `tests/evidence/test_blast_radius.py`

This plan mirrors the structural shape of `docs/dev/test-plans/merge-evidence-gating.md`
(Batch A test plan) so the WB-T close-out is directly comparable to WA-T.

## Locked decisions exercised

| ID | Decision | Test(s) |
|----|----------|---------|
| **D4** | Batch B wires the `MergeEvidencePacket.blast_radius` field via a typed classifier — packet remains nullable until W5/W6 | all WB-T cases lazy-import `mergecraft.classify.blast_radius` |
| **D9** | Rule set is declarative and overridable per repo via `RepoSettings.blast_radius_override` (additive, default empty) | `test_rule_set_is_overridable_per_repo` |
| **D10** | Default rule set ships with mergeCraft and the consumer repo may extend it | `test_classifier_low_risk_examples`, `test_classifier_medium_risk_examples`, `test_classifier_high_risk_examples` |
| Convention 5 | Classifier is pure — no filesystem, no network, no `os.environ` | `test_classifier_is_pure` |

## Contract matrix

| Issue | Decision | Layer | Scenario | Primary test |
|-------|----------|-------|----------|--------------|
| **#48** | D10 | Unit | Docs/tests/small isolated changes classify as `low` | `test_classifier_low_risk_examples` |
| **#48** | D10 | Unit | Broad application changes classify as `medium` | `test_classifier_medium_risk_examples` |
| **#48** | D10 | Unit | Migrations / auth / security / payment / deployment / irreversible infra classify as `high` | `test_classifier_high_risk_examples` |
| **#48** | D10 | Unit | Each named category appears in `result.categories` | `test_classifier_detects_each_named_category` |
| **#42** | D9 | Unit | A `RepoSettings.blast_radius_override` changes the outcome without a code change | `test_rule_set_is_overridable_per_repo` |
| **#42** | D9 | Unit | Decision output carries `lane`, `reason`, `next_action` | `test_decision_output_names_lane_reason_and_next_action` |
| Convention 5 | D5 | Unit | Classifier performs no filesystem, network, or env access | `test_classifier_is_pure` |

## xfail schedule

| Wave | Test | Marker reason |
|------|------|---------------|
| **W6** | `tests/evidence/test_blast_radius.py::test_classifier_low_risk_examples` | `green after W5/W6` |
| **W6** | `tests/evidence/test_blast_radius.py::test_classifier_medium_risk_examples` | `green after W5/W6` |
| **W6** | `tests/evidence/test_blast_radius.py::test_classifier_high_risk_examples` | `green after W5/W6` |
| **W6** | `tests/evidence/test_blast_radius.py::test_classifier_detects_each_named_category` | `green after W5/W6` |
| **W6** | `tests/evidence/test_blast_radius.py::test_rule_set_is_overridable_per_repo` | `green after W5/W6` |
| **W5** | `tests/evidence/test_blast_radius.py::test_decision_output_names_lane_reason_and_next_action` | `green after W5/W6` |
| **W6** | `tests/evidence/test_blast_radius.py::test_classifier_is_pure` | `green after W5/W6` |

All cross-wave markers use `strict=False` so the W5/W6 green half flips
each case to PASS without breaking the suite under the project-wide
`xfail_strict=true` setting.

## Contract surface locked for W5 / W6

```python
from typing import Literal, TypedDict

from pydantic import BaseModel

Lane = Literal["low", "medium", "high"]
AutoMergeLane = Literal["eligible", "assisted", "human_review", "forbidden"]


class ChangeSet(TypedDict, total=False):
    """Side-effect-free change payload fed to the classifier."""

    changed_paths: list[str]
    diff_stats: dict[str, object]


class RuleSet(TypedDict, total=False):
    """Declarative override block read from RepoSettings.blast_radius_override."""

    migrations: dict[str, object]
    auth_security_payment: dict[str, object]
    secrets_config_deployment: dict[str, object]
    generated_files: dict[str, object]
    public_api_changes: dict[str, object]
    dependency_changes: dict[str, object]
    source_without_tests: dict[str, object]


class BlastRadiusClassification(BaseModel):
    """Decision output of `classify_blast_radius`."""

    lane: Lane
    auto_merge_lane: AutoMergeLane
    reason: str
    next_action: str
    categories: list[str]


def classify_blast_radius(
    change: ChangeSet, *, rule_set: RuleSet | None = None
) -> BlastRadiusClassification: ...
```

`RepoSettings` must grow an additive `blast_radius_override: RuleSet` field
(default empty) so the override test can vary classification without code
changes (D9).

## Implementation notes for impl waves

- **W5** — Land `BlastRadiusClassification`, the additive
  `RepoSettings.blast_radius_override`, the lane-policy mapping
  (`low → eligible`, `medium → assisted/human_review`, `high → forbidden`),
  and wire the result into `MergeEvidencePacket.blast_radius` while
  bumping `PACKET_SCHEMA_VERSION` (D7). Un-xfail
  `test_decision_output_names_lane_reason_and_next_action`.
- **W6** — Land the default rule set and the pure
  `classify_blast_radius` implementation in
  `src/mergecraft/classify/blast_radius.py`. Reuse existing catalog
  vocabulary where it exists (D10) and document the rules in
  `REVIEW-CHECKS.md`. Un-xfail
  `test_classifier_low_risk_examples`,
  `test_classifier_medium_risk_examples`,
  `test_classifier_high_risk_examples`,
  `test_classifier_detects_each_named_category`,
  `test_rule_set_is_overridable_per_repo`, and
  `test_classifier_is_pure`.
- **Style mirrors the analyzer test suite** — lazy import inside the
  fixture, `from __future__ import annotations` everywhere, no real
  credentials, no filesystem/network/env access in fixtures.
