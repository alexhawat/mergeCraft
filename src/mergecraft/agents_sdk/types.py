"""Structured finding types for Agents SDK review output."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from mergecraft.review_taxonomy import FINDING_SEVERITIES

ReviewSeverity = Literal["Critical", "Major", "Minor", "Trivial"]


class ReviewFinding(BaseModel):
    """One review finding returned by the Agents SDK review agent."""

    model_config = ConfigDict(extra="forbid")

    severity: ReviewSeverity
    file: str = Field(description="Repo-relative path under review.")
    line: int | None = Field(default=None, ge=1)
    message: str
    suggested_fix: str | None = None

    @classmethod
    def severity_values(cls) -> frozenset[str]:
        return frozenset(FINDING_SEVERITIES)


class ReviewFindingsReport(BaseModel):
    """Final structured output from ``review_agent``."""

    model_config = ConfigDict(extra="forbid")

    findings: list[ReviewFinding] = Field(default_factory=list)
    summary: str = ""

    def blocking_findings(self) -> list[ReviewFinding]:
        """Findings at Major severity or above (mergeCraft gate convention)."""
        blocking = {"Critical", "Major"}
        return [row for row in self.findings if row.severity in blocking]


__all__ = ["ReviewFinding", "ReviewFindingsReport", "ReviewSeverity"]
