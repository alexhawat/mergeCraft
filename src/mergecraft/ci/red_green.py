"""Fail-then-pass receipts that prove a fix pull request (#1056 part 5).

The Action never runs a consumer's tests (C-D1). A fix pull request proves
itself with a receipt its own CI uploads: a JSON document listing tests with
their result on the base commit and on the head commit. This module parses
that receipt under fixed bounds, computes its verdict, binds it to the run's
exact SHAs, and decides whether a pull request is a fix at all. It is pure:
no network, no filesystem, no subprocess; the ingest lives in
``mergecraft.ci.sarif_ingest``.

Module: mergecraft.ci.red_green
Depends: pydantic

Exports:
    Types:
        TestResult — One test's result on one commit.
        RedGreenVerdict — What a parsed receipt proves.
        RedGreenStatus — The evidence vocabulary recorded on ``ToolState``.
    Classes:
        RedGreenTest — One listed test (``id``, ``base``, ``head``).
        RedGreenReceipt — A parsed receipt (``base_sha``, ``head_sha``, ``tests``).
        RedGreenReceiptError — A refused receipt, with ``kind`` ``invalid`` or ``oversized``.
        RedGreenEvidence — What the run recorded about its receipt.
    Functions:
        undeclared_red_green_evidence — The ``not-declared`` evidence row.
        parse_red_green_receipt — Bounded, strict parse of the receipt document.
        red_green_verdict — ``proven`` / ``not-proven`` / ``no-tests``.
        receipt_matches — Full-length, case-insensitive SHA binding.
        is_fix_pull_request — Conventional ``fix`` type or a configured fix label.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

if TYPE_CHECKING:
    from collections.abc import Sequence

TestResult = Literal["passed", "failed", "error", "skipped"]
RedGreenVerdict = Literal["proven", "not-proven", "no-tests"]
RedGreenStatus = Literal[
    "proven",
    "not-proven",
    "no-tests",
    "no-receipt",
    "invalid",
    "mismatch",
    "not-declared",
]
RedGreenErrorKind = Literal["invalid", "oversized"]

RECEIPT_SCHEMA_ID: Final[str] = "mergecraft.red-green/1"
RECEIPT_MAX_BYTES: Final[int] = 1_000_000
RECEIPT_MAX_TESTS: Final[int] = 2_000
RECEIPT_MAX_ID_CHARS: Final[int] = 500
DEFAULT_FIX_LABELS: Final[tuple[str, ...]] = ("bug", "fix")

_SHA_MAX_CHARS: Final[int] = 128
_FULL_SHA = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
# A conventional ``fix`` type: ``fix:``, ``fix(scope):``, ``fix!:``, ``fix(scope)!:``.
_FIX_TYPE = re.compile(r"fix(?:\([^()\r\n]*\))?!?:", re.IGNORECASE)


class RedGreenReceiptError(ValueError):
    """A receipt that was refused; ``kind`` says whether it was malformed or too large."""

    def __init__(self, message: str = "", *, kind: RedGreenErrorKind) -> None:
        self.kind: RedGreenErrorKind = kind
        super().__init__(message or f"red-green receipt refused ({kind})")


class RedGreenTest(BaseModel):
    """One test the receipt lists, with its result on the base and on the head."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1, max_length=RECEIPT_MAX_ID_CHARS)
    base: TestResult
    head: TestResult


class RedGreenReceipt(BaseModel):
    """A parsed receipt: the commits it was produced for and the tests it lists."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    base_sha: str = Field(max_length=_SHA_MAX_CHARS)
    head_sha: str = Field(max_length=_SHA_MAX_CHARS)
    tests: tuple[RedGreenTest, ...] = Field(max_length=RECEIPT_MAX_TESTS)


class _ReceiptDocument(BaseModel):
    """The wire document: :class:`RedGreenReceipt` plus its schema id; unknown keys refused."""

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=False)

    schema_id: Literal["mergecraft.red-green/1"] = Field(alias="schema")
    base_sha: str = Field(max_length=_SHA_MAX_CHARS)
    head_sha: str = Field(max_length=_SHA_MAX_CHARS)
    tests: tuple[RedGreenTest, ...] = Field(max_length=RECEIPT_MAX_TESTS)


@dataclass(frozen=True, slots=True)
class RedGreenEvidence:
    """What the run recorded about its fail-then-pass receipt (``ToolState.red_green``).

    ``status`` is the verdict of a matching receipt, or why there is none;
    ``artifact`` and ``run_url`` name where it came from when one was read;
    ``detail`` is a short operator-facing sentence.
    """

    status: RedGreenStatus
    test_count: int
    artifact: str | None
    run_url: str | None
    detail: str


def undeclared_red_green_evidence(unreadable: str | None = None) -> RedGreenEvidence:
    """The evidence for a pull request with no base-side ``ciEvidence.redGreen``.

    Args:
        unreadable (str | None): Why the base config could not be read, when that is
            the cause; ``None`` when the base was read and declares no receipt.

    Returns:
        RedGreenEvidence: Status ``not-declared``, no artifact and no run.
    """
    detail = (
        "the pull request base declares no ciEvidence.redGreen receipt"
        if unreadable is None
        else (
            "the pull request base config could not be read, so no ciEvidence.redGreen "
            f"receipt is in force ({unreadable})"
        )
    )
    return RedGreenEvidence(
        status="not-declared",
        test_count=0,
        artifact=None,
        run_url=None,
        detail=detail,
    )


def _encoded(raw: str | bytes, max_bytes: int) -> bytes:
    """``raw`` as UTF-8 bytes, refusing anything over ``max_bytes`` before decoding it."""
    if isinstance(raw, bytes):
        if len(raw) > max_bytes:
            raise RedGreenReceiptError(
                f"receipt is oversized: {len(raw)} bytes exceeds the {max_bytes}-byte cap",
                kind="oversized",
            )
        return raw
    # Every character is at least one UTF-8 byte, so a long string is refused unencoded.
    if len(raw) > max_bytes:
        raise RedGreenReceiptError(
            f"receipt is oversized: over the {max_bytes}-byte cap", kind="oversized"
        )
    try:
        data = raw.encode("utf-8")
    except UnicodeEncodeError as err:
        raise RedGreenReceiptError("receipt is not valid UTF-8 text", kind="invalid") from err
    if len(data) > max_bytes:
        raise RedGreenReceiptError(
            f"receipt is oversized: {len(data)} UTF-8 bytes exceeds the {max_bytes}-byte cap",
            kind="oversized",
        )
    return data


def _validation_summary(err: ValidationError) -> str:
    """A short, content-free account of the first validation error."""
    errors = err.errors(include_url=False, include_input=False)
    if not errors:
        return "receipt failed validation"
    first = errors[0]
    loc = ".".join(str(part) for part in first.get("loc", ())) or "<document>"
    more = f" (and {len(errors) - 1} more)" if len(errors) > 1 else ""
    return f"receipt failed validation at {loc}: {first.get('type', 'invalid')}{more}"


def parse_red_green_receipt(
    raw: str | bytes, *, max_bytes: int = RECEIPT_MAX_BYTES
) -> RedGreenReceipt:
    """Parse a receipt document under the size, count and shape bounds.

    The size check counts UTF-8 bytes and runs before anything is decoded, so an
    oversized ``bytes`` input is never read past its length. The document must
    be a JSON object with exactly ``schema`` (``mergecraft.red-green/1``),
    ``base_sha``, ``head_sha`` and ``tests``; each test has exactly ``id`` (at
    most 500 characters), ``base`` and ``head``; at most 2 000 tests.

    Args:
        raw (str | bytes): The receipt document as read from the artifact.
        max_bytes (int): The byte cap; defaults to 1 000 000.

    Returns:
        RedGreenReceipt: The receipt, its tests in document order.

    Raises:
        RedGreenReceiptError: ``kind="oversized"`` over the cap, ``kind="invalid"``
            for anything that is not a well-formed receipt.

    Examples:
        >>> doc = '{"schema": "mergecraft.red-green/1", "base_sha": "", "head_sha": "", "tests": []}'
        >>> parse_red_green_receipt(doc).tests
        ()
    """
    data = _encoded(raw, max_bytes)
    try:
        text = bytes(data).decode("utf-8")
    except UnicodeDecodeError as err:
        raise RedGreenReceiptError("receipt is not valid UTF-8 text", kind="invalid") from err
    try:
        document = _ReceiptDocument.model_validate_json(text, strict=True)
    except ValidationError as err:
        raise RedGreenReceiptError(_validation_summary(err), kind="invalid") from err
    return RedGreenReceipt(
        base_sha=document.base_sha, head_sha=document.head_sha, tests=document.tests
    )


def red_green_verdict(receipt: RedGreenReceipt) -> RedGreenVerdict:
    """What the receipt proves.

    ``proven`` needs at least one test ``failed`` or ``error`` on the base **and**
    every listed test ``passed`` on the head; an empty receipt is ``no-tests``;
    anything else is ``not-proven``.

    Args:
        receipt (RedGreenReceipt): A parsed receipt.

    Returns:
        RedGreenVerdict: The verdict.
    """
    if not receipt.tests:
        return "no-tests"
    red_on_base = any(test.base in {"failed", "error"} for test in receipt.tests)
    green_on_head = all(test.head == "passed" for test in receipt.tests)
    return "proven" if red_on_base and green_on_head else "not-proven"


def _full_sha(value: str) -> str | None:
    lowered = value.strip().lower()
    return lowered if _FULL_SHA.fullmatch(lowered) else None


def receipt_matches(receipt: RedGreenReceipt, *, base_sha: str, head_sha: str) -> bool:
    """Whether the receipt was produced for exactly this base and head.

    Both sides must be full-length hex SHAs (40 or 64 characters) and equal
    ignoring case: a short SHA never matches, even an equal one.

    Args:
        receipt (RedGreenReceipt): A parsed receipt.
        base_sha (str): The run's bound base SHA.
        head_sha (str): The run's bound head SHA.

    Returns:
        bool: ``True`` only for an exact full-length match on both SHAs.
    """
    pairs = ((receipt.base_sha, base_sha), (receipt.head_sha, head_sha))
    for theirs, ours in pairs:
        left, right = _full_sha(theirs), _full_sha(ours)
        if left is None or right is None or left != right:
            return False
    return True


def is_fix_pull_request(title: str, labels: Sequence[str], *, fix_labels: Sequence[str]) -> bool:
    """Whether a pull request is a fix and so needs a fail-then-pass receipt.

    A fix is a conventional ``fix`` type at the start of the title (``fix:``,
    ``fix(scope):``, ``fix!:``, ``fix(scope)!:``; case-insensitive, leading
    whitespace ignored) **or** any label named in ``fix_labels``
    (case-insensitive, exact). These author-written inputs can only add the
    requirement; nothing here satisfies it.

    Args:
        title (str): The pull request title.
        labels (Sequence[str]): The pull request's label names.
        fix_labels (Sequence[str]): The configured fix labels (``review.fixLabels``).

    Returns:
        bool: ``True`` when the pull request is a fix.

    Examples:
        >>> is_fix_pull_request("fix(ci): x", [], fix_labels=["bug"])
        True
        >>> is_fix_pull_request("fixture: x", ["Bug"], fix_labels=["bug"])
        True
        >>> is_fix_pull_request("feat: x", [], fix_labels=["bug"])
        False
    """
    if isinstance(title, str) and _FIX_TYPE.match(title.lstrip()):
        return True
    wanted = {label.strip().casefold() for label in fix_labels if isinstance(label, str)}
    wanted.discard("")
    return any(isinstance(label, str) and label.strip().casefold() in wanted for label in labels)


__all__ = [
    "DEFAULT_FIX_LABELS",
    "RECEIPT_MAX_BYTES",
    "RECEIPT_MAX_ID_CHARS",
    "RECEIPT_MAX_TESTS",
    "RECEIPT_SCHEMA_ID",
    "RedGreenErrorKind",
    "RedGreenEvidence",
    "RedGreenReceipt",
    "RedGreenReceiptError",
    "RedGreenStatus",
    "RedGreenTest",
    "RedGreenVerdict",
    "TestResult",
    "is_fix_pull_request",
    "parse_red_green_receipt",
    "receipt_matches",
    "red_green_verdict",
    "undeclared_red_green_evidence",
]
