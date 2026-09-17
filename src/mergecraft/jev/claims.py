"""Deterministic review-body → claims split (D12, G12).

Jev is not trained to generate text, so no model splits the prose. Sentence
and list-item boundaries run over the rendered Markdown. Fenced code blocks,
tables, and the findings table itself are held out as non-claims.

Exports:
    JevError: Structured failure (``invalid_body``).
    Claim: One extracted sentence or list item.
    extract_claims: Split a review body into claims.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict

from mergecraft.jev.types import JevError

ClaimKind = Literal["sentence", "list_item"]

_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_FENCE_OPEN_RE = re.compile(r"^(?P<indent>\s*)(?P<fence>`{3,}|~{3,})")
_TABLE_LINE_RE = re.compile(r"^\s*\|")
_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+\S")
_LIST_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
_HTML_TAG_RE = re.compile(r"</?[A-Za-z][^>]*>")
_HR_RE = re.compile(r"^\s*(?:[-*_]\s*){3,}$")
_ABBREVIATIONS = frozenset({"e.g", "i.e", "etc", "vs", "mr", "mrs", "dr", "prof"})
_CHROME_LABELS = frozenset({"technical details", "details", "summary"})


class Claim(BaseModel):
    """One prose claim held out from fences, tables, and the findings table."""

    model_config = ConfigDict(extra="forbid")

    text: str
    kind: ClaimKind


def extract_claims(body: str | None) -> list[Claim]:
    """Split rendered Markdown into sentence and list-item claims (D12).

    Args:
        body: Review body Markdown. ``None`` is ``invalid_body``.

    Returns:
        list[Claim]: Deterministic claims. Empty input yields no claims.

    Raises:
        JevError: When ``body`` is ``None`` or not a string.
    """
    if body is None or not isinstance(body, str):
        raise JevError("review body is required", code="invalid_body")
    if body == "":
        return []

    stripped = _HTML_COMMENT_RE.sub("\n", body)
    kept = _hold_out_fences_and_tables(stripped.splitlines())
    claims: list[Claim] = []
    paragraph: list[str] = []

    def flush_paragraph() -> None:
        if not paragraph:
            return
        block = " ".join(paragraph).strip()
        paragraph.clear()
        for sentence in _split_sentences(block):
            claims.append(Claim(text=sentence, kind="sentence"))

    for raw in kept:
        line = _HTML_TAG_RE.sub("", raw).strip()
        if not line or _HEADING_RE.match(raw) or _HR_RE.match(line):
            flush_paragraph()
            continue
        if line.casefold() in _CHROME_LABELS:
            flush_paragraph()
            continue
        if _LIST_RE.match(raw):
            flush_paragraph()
            item = _LIST_RE.sub("", raw).strip()
            item = _HTML_TAG_RE.sub("", item).strip()
            if item:
                claims.append(Claim(text=item, kind="list_item"))
            continue
        paragraph.append(line)
    flush_paragraph()
    return claims


def _hold_out_fences_and_tables(lines: list[str]) -> list[str]:
    """Drop fenced code, pipe tables, and the findings table (D12)."""
    kept: list[str] = []
    fence: str | None = None
    fence_len = 0
    for line in lines:
        if fence is not None:
            closer = _FENCE_OPEN_RE.match(line)
            if (
                closer is not None
                and closer.group("fence")[0] == fence
                and len(closer.group("fence")) >= fence_len
            ):
                fence = None
                fence_len = 0
            continue
        opener = _FENCE_OPEN_RE.match(line)
        if opener is not None:
            fence = opener.group("fence")[0]
            fence_len = len(opener.group("fence"))
            continue
        if _TABLE_LINE_RE.match(line) or _is_table_separator(line):
            continue
        kept.append(line)
    return kept


def _is_table_separator(line: str) -> bool:
    stripped = line.strip()
    if "|" not in stripped:
        return False
    body = stripped.strip("|").replace(":", "-")
    return bool(body) and all(part.strip("- ") == "" for part in body.split("|"))


def _split_sentences(text: str) -> list[str]:
    if not text:
        return []
    parts: list[str] = []
    buf: list[str] = []
    in_tick = False
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        if char == "`":
            in_tick = not in_tick
            buf.append(char)
            index += 1
            continue
        buf.append(char)
        if not in_tick and char in ".!?" and _is_sentence_boundary(buf, text[index + 1 :]):
            sentence = "".join(buf).strip()
            if sentence:
                parts.append(sentence)
            buf = []
            index += 1
            while index < length and text[index].isspace():
                index += 1
            continue
        index += 1
    tail = "".join(buf).strip()
    if tail:
        parts.append(tail)
    return parts


def _is_sentence_boundary(buf: list[str], rest: str) -> bool:
    nxt = rest.lstrip()
    if not nxt:
        return True
    if nxt[0].isdigit():
        return False
    token = _trailing_token(buf)
    if token.rstrip(".").casefold() in _ABBREVIATIONS:
        return False
    if nxt[0].islower():
        return False
    return nxt[0].isupper() or nxt[0] in {"`", "$", '"', "'", "("}


def _trailing_token(buf: list[str]) -> str:
    text = "".join(buf).rstrip(".!? ").rsplit(None, 1)
    if not text:
        return ""
    return text[-1]


__all__ = [
    "Claim",
    "JevError",
    "extract_claims",
]
