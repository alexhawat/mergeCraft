"""Strict preparation models for the first human golden-case batch (#780).

This module prepares inspectable evidence and a review sheet. It never applies
decisions to corpus files and never manufactures an adjudication record.
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime  # noqa: TC003 - Pydantic resolves this field at runtime.
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from mergecraft.evals.corpora import CorpusCase

GOLDEN_BATCH_001_CASE_IDS: tuple[str, ...] = (
    "golden-go-chi-api-breakage-001",
    "golden-java-spring-performance-001",
    "golden-javascript-npm-dependency-001",
    "golden-python-django-migration-001",
    "golden-python-fastapi-correctness-001",
    "golden-python-requirements-001",
    "golden-ruby-rails-clean-001",
    "golden-rust-tokio-concurrency-001",
    "golden-typescript-express-security-001",
)

EvidenceStatus = Literal["recovered", "missing"]
HumanDecision = Literal["pending", "confirm", "correct", "abstain"]
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_COMMIT_SHA_RE = re.compile(r"[0-9a-f]{40}\Z", re.IGNORECASE)


class CorrectedCorpusFields(BaseModel):
    """Operator-supplied corrections allowed on a golden corpus object."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    language: str | None = None
    framework: str | None = None
    category: str | None = None
    kind: str | None = None
    path: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def _has_a_correction(self) -> CorrectedCorpusFields:
        if not self.model_dump(exclude_none=True):
            raise ValueError("a correct decision must provide at least one corrected corpus field")
        return self


class HumanBatchCase(BaseModel):
    """Evidence and pending or human-supplied decision for one golden case."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    evidence_status: EvidenceStatus
    source_url: str | None = None
    fixture_path: str | None = None
    fixture_sha256: str | None = None
    decision: HumanDecision = "pending"
    decided_at: datetime | None = None
    decided_by: str | None = None
    corrected_fields: CorrectedCorpusFields | None = None

    @field_validator("source_url")
    @classmethod
    def _source_url_is_immutable(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = urlsplit(value)
        if parsed.scheme != "https" or parsed.netloc.casefold() not in {
            "github.com",
            "www.github.com",
        }:
            raise ValueError("source_url must be an HTTPS github.com URL")
        parts = [part for part in parsed.path.split("/") if part]
        pinned_blob_or_commit = (
            len(parts) >= 4
            and parts[2] in {"blob", "commit"}
            and _COMMIT_SHA_RE.fullmatch(parts[3]) is not None
        )
        pinned_pull_commit = (
            len(parts) >= 6
            and parts[2] == "pull"
            and parts[3].isdigit()
            and parts[4] == "commits"
            and _COMMIT_SHA_RE.fullmatch(parts[5]) is not None
        )
        if not pinned_blob_or_commit and not pinned_pull_commit:
            raise ValueError(
                "source_url must pin a GitHub blob or commit path to a full commit SHA"
            )
        return value

    @field_validator("fixture_sha256")
    @classmethod
    def _fixture_hash_is_sha256(cls, value: str | None) -> str | None:
        if value is not None and _SHA256_RE.fullmatch(value) is None:
            raise ValueError("fixture_sha256 must be 64 lowercase hexadecimal characters")
        return value

    @model_validator(mode="after")
    def _evidence_and_decision_are_consistent(self) -> HumanBatchCase:
        has_fixture_path = self.fixture_path is not None
        has_fixture_hash = self.fixture_sha256 is not None
        if has_fixture_path != has_fixture_hash:
            raise ValueError("fixture_path and fixture_sha256 must be provided together")
        if self.fixture_path is not None:
            relative = PurePosixPath(self.fixture_path)
            expected = PurePosixPath("evals", "fixtures", "golden", self.case_id)
            if (
                relative.is_absolute()
                or ".." in relative.parts
                or not relative.is_relative_to(expected)
            ):
                raise ValueError(
                    "fixture_path must stay inside the case's golden fixture directory"
                )

        has_evidence = self.source_url is not None or has_fixture_path
        if self.evidence_status == "missing" and has_evidence:
            raise ValueError("missing evidence rows must leave source and fixture fields null")
        if self.evidence_status == "recovered" and not has_evidence:
            raise ValueError("recovered evidence requires an immutable source URL or fixture")

        if self.decision in {"confirm", "correct"} and self.evidence_status != "recovered":
            raise ValueError("confirm and correct decisions require recovered evidence")
        if self.decision == "correct" and self.corrected_fields is None:
            raise ValueError("a correct decision requires corrected_fields")
        if self.decision != "correct" and self.corrected_fields is not None:
            raise ValueError("corrected_fields are valid only for a correct decision")
        if self.decision == "pending" and (
            self.decided_at is not None or self.decided_by is not None
        ):
            raise ValueError("pending decisions must leave decided_at and decided_by null")
        if self.decision != "pending" and (self.decided_at is None or self.decided_by is None):
            raise ValueError("non-pending decisions require decided_at and decided_by")
        return self


class HumanBatchManifest(BaseModel):
    """The frozen nine-case #780 review manifest."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0.0"]
    batch_id: Literal["golden-batch-001"]
    adjudicator_login: str
    cases: list[HumanBatchCase]

    @model_validator(mode="after")
    def _batch_is_complete_and_identity_matches(self) -> HumanBatchManifest:
        case_ids = [row.case_id for row in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("human batch case IDs must be unique")
        if set(case_ids) != set(GOLDEN_BATCH_001_CASE_IDS):
            raise ValueError("human batch must contain exactly the nine #780 golden case IDs")
        if not self.adjudicator_login.strip():
            raise ValueError("adjudicator_login must not be empty")
        for row in self.cases:
            if row.decided_by is not None and row.decided_by != self.adjudicator_login:
                raise ValueError("decided_by must match the manifest adjudicator_login")
        return self


def verify_fixture_evidence(manifest: HumanBatchManifest, *, repo_root: Path) -> None:
    """Verify every local evidence fixture is confined, regular, and hash-matched."""
    if repo_root.is_symlink():
        raise ValueError(f"repository root must not be a symlink: {repo_root}")
    resolved_root = repo_root.resolve()
    for row in manifest.cases:
        if row.fixture_path is None:
            continue
        candidate = repo_root / row.fixture_path
        current = candidate
        while current != repo_root and current != current.parent:
            if current.is_symlink():
                raise ValueError(f"fixture must not be a symlink: {row.fixture_path}")
            current = current.parent
        resolved = candidate.resolve()
        if not resolved.is_relative_to(resolved_root) or not resolved.is_file():
            raise ValueError(f"fixture is missing or escapes the repository: {row.fixture_path}")
        actual = sha256(resolved.read_bytes()).hexdigest()
        if actual != row.fixture_sha256:
            raise ValueError(f"fixture hash mismatch for {row.fixture_path}")


def verify_corrected_cases(manifest: HumanBatchManifest, *, repo_root: Path) -> None:
    """Apply corrections in memory and validate the final strict ``CorpusCase`` shape."""
    for row in manifest.cases:
        if row.corrected_fields is None:
            continue
        case_path = repo_root / "evals" / "cases" / "golden" / f"{row.case_id}.json"
        case = CorpusCase.model_validate_json(case_path.read_text(encoding="utf-8"))
        candidate = case.model_dump(mode="python")
        candidate.update(row.corrected_fields.model_dump(exclude_none=True))
        CorpusCase.model_validate(candidate)


def load_human_batch(path: Path, *, repo_root: Path) -> HumanBatchManifest:
    """Load a strict manifest and verify all referenced local evidence."""
    manifest = HumanBatchManifest.model_validate_json(path.read_text(encoding="utf-8"))
    verify_fixture_evidence(manifest, repo_root=repo_root)
    verify_corrected_cases(manifest, repo_root=repo_root)
    return manifest


def render_review_sheet(manifest: HumanBatchManifest, *, repo_root: Path) -> str:
    """Render one ordered review sheet without applying any human decision."""
    verify_fixture_evidence(manifest, repo_root=repo_root)
    verify_corrected_cases(manifest, repo_root=repo_root)
    rows: list[str] = []
    for entry in sorted(manifest.cases, key=lambda row: row.case_id):
        case_path = repo_root / "evals" / "cases" / "golden" / f"{entry.case_id}.json"
        case = CorpusCase.model_validate_json(case_path.read_text(encoding="utf-8"))
        evidence = "missing"
        if entry.source_url is not None:
            evidence = entry.source_url
        elif entry.fixture_path is not None:
            evidence = f"{entry.fixture_path} (sha256:{entry.fixture_sha256})"
        decision = (
            "UNANSWERED"
            if entry.decision == "pending"
            else f"{entry.decision} by {entry.decided_by or 'identity not recorded'}"
        )
        claimed = f"{case.path}:{case.start_line}-{case.end_line}"
        values = (
            entry.case_id,
            case.title,
            claimed,
            case.category,
            evidence,
            decision,
        )
        rows.append("| " + " | ".join(value.replace("|", "\\|") for value in values) + " |")

    header = [
        f"# Human adjudication review sheet: {manifest.batch_id}",
        "",
        f"Adjudicator: `{manifest.adjudicator_login}`",
        "",
        "This sheet records no severity because `CorpusCase` has no severity field.",
        "Every UNANSWERED row requires an explicit `confirm`, `correct`, or `abstain` response.",
        "",
        "| Case ID | Claimed title | Claimed path/range | Category | Evidence | Decision |",
        "|---|---|---|---|---|---|",
    ]
    return "\n".join([*header, *rows, ""])


def main(argv: list[str] | None = None) -> int:
    """Render the committed batch manifest as a Markdown review sheet."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("evals/adjudication/golden-batch-001.json"),
    )
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    manifest = load_human_batch(args.manifest, repo_root=args.repo_root)
    sys.stdout.write(render_review_sheet(manifest, repo_root=args.repo_root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "GOLDEN_BATCH_001_CASE_IDS",
    "CorrectedCorpusFields",
    "EvidenceStatus",
    "HumanBatchCase",
    "HumanBatchManifest",
    "HumanDecision",
    "load_human_batch",
    "render_review_sheet",
    "verify_corrected_cases",
    "verify_fixture_evidence",
]
