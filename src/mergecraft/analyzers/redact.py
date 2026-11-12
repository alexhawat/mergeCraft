"""Secret redaction boundary for analyzer outputs (D8)."""

from __future__ import annotations

import hashlib
import json
import math
import re
from re import Pattern
from typing import TYPE_CHECKING, Any

from mergecraft.redaction_sentinel import REDACTION_SENTINEL
from mergecraft.redaction_structured import redact_structured_value

if TYPE_CHECKING:
    from collections.abc import Iterable

# The key may carry a prefix (``DB_PASSWORD``, ``GITHUB_TOKEN``,
# ``aws_secret_access_key``): the credential word only has to start a segment,
# so the lookbehind admits ``_`` and ``-`` where ``\b`` would not.
_ASSIGNMENT_SECRET_PATTERN: Pattern[str] = re.compile(
    r"(?<![A-Za-z0-9])"
    r"(?:api[_-]?key|access[_-]?key|private[_-]?key|secret[_-]?key|secret|token|password"
    r"|passwd|credential)\s*[:=]\s*"
    r"""(?:"(?:\\.|[^"\\]){8,}"|'(?:\\.|[^'\\]){8,}'|"""
    r"(?P<unquoted>[^\s'\"]{8,}))",
    re.I,
)
# A password is redacted whatever its length: ``password: hunter2`` falls under
# the 8-character floor the other credential words keep.
_PASSWORD_ASSIGNMENT_PATTERN: Pattern[str] = re.compile(
    r"(?<![A-Za-z0-9])(?:password|passwd|pwd)[ \t]*[:=][ \t]*"
    r"""(?:"(?:\\.|[^"\\\n])+"|'(?:\\.|[^'\\\n])+'|"""
    r"(?P<unquoted>[^\s'\"]+))",
    re.I,
)
_ASSIGNMENT_PATTERNS: frozenset[Pattern[str]] = frozenset(
    {_ASSIGNMENT_SECRET_PATTERN, _PASSWORD_ASSIGNMENT_PATTERN}
)

_SECRET_PATTERNS: tuple[Pattern[str], ...] = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    # Fine-grained GitHub PATs (``github_pat_<22>_<59>``) are not ``gh?_`` shaped.
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"),
    # PyPI API tokens are ``pypi-`` plus a base64url macaroon whose serialised
    # header always encodes to ``AgE``; anchoring on it keeps ``pypi-publish-…``
    # workflow slugs readable.
    re.compile(r"\bpypi-AgE[A-Za-z0-9_-]{20,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\b(?:xox[baprs]-)[A-Za-z0-9-]{10,}\b"),
    re.compile(r"\bnpm_[A-Za-z0-9]{36}\b"),
    # Slack incoming webhooks: the whole path after ``/services/`` is the credential.
    re.compile(r"https://hooks\.slack\.com/services/[A-Za-z0-9/_-]+"),
    _ASSIGNMENT_SECRET_PATTERN,
    _PASSWORD_ASSIGNMENT_PATTERN,
    re.compile(r"Basic [A-Za-z0-9+/=]{16,}"),
)

# ``Authorization: Bearer <token>`` -- the scheme word is kept so the operator
# still sees which auth shape failed; only the credential is replaced.
_BEARER_TOKEN_PATTERN: Pattern[str] = re.compile(
    r"(?P<scheme>\b[Bb]earer\s+)[A-Za-z0-9._~+/=-]{16,}"
)

_MIN_ENTROPY_LENGTH = 16
_ENTROPY_RATIO = 0.85
# Absolute per-character ceiling on the entropy threshold. The length-relative
# ``0.85 * log2(len)`` keeps growing with length while random base-62/base-64
# credentials plateau around 5.2-5.9 bits/char, so from ~64 chars random tokens
# increasingly fell *under* the threshold and, by ~120, all leaked (#1232). The
# ratio already reaches 4.5 bits at ~39 chars; capping there leaves short-token
# behaviour unchanged. Hex (<= 4 bits/char) stays below the ceiling.
_ENTROPY_ABSOLUTE_CEILING = 4.5
# The unique-symbol ratio only decides tokens shorter than this. Past it the
# capped entropy threshold carries detection (random base-62 at 64 chars sits
# well above 4.5 bits/char), while the ratio would also blank long repo paths
# and code lines that carry no secret.
_DENSE_TOKEN_MAX_LENGTH = 64
_ENTROPY_TOKEN_RE = re.compile(r"[A-Za-z0-9+/=_-]{16,}")
_REPO_PATH_TOKEN_RE = re.compile(r"^/?[\w.-]+(?:/[\w.-]+)+$")

_BENIGN_HEX_40_RE = re.compile(r"^[a-f0-9]{40}$")
_BENIGN_HEX_64_RE = re.compile(r"^[a-f0-9]{64}$")
_BENIGN_PURE_HEX_RE = re.compile(r"^[a-f0-9]+$")
# Catalog identifiers only: snake_case, SCREAMING_SNAKE, and lowercase kebab.
# Mixed-case alphanumeric blobs (e.g. ``AbCdEfGh…``) are not identifiers and
# must fall through to the entropy pass. Plain lowercase/uppercase runs without
# ``_`` or ``-`` separators are not identifiers either. ``sk-…`` / ``ghp_…``
# still match ``_SECRET_PATTERNS`` first.
_BENIGN_IDENTIFIER_RE = re.compile(
    r"^(?:_[a-z][a-z0-9_]*|[a-z][a-z0-9]*_[a-z0-9_]+"
    r"|[a-z][a-z0-9]*(?:-[a-z0-9]+)+|[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+"
    r"|[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+)$"  # RUSTSEC-2024-0001
)
# camelCase SARIF keys (``ruleId``, ``physicalLocation``, ``partialFingerprints``,
# ``originalUriBaseIds``): a lowercase head word followed by capitalised words,
# each a capital plus lowercase letters, or a short acronym (``getHTTPResponse``,
# ``timeoutS``). The old ``[a-z][a-z0-9]*(?:[A-Z][a-z0-9]*)+`` shape admitted any
# alphanumeric blob that started lowercase and held a capital -- most random
# base-62 credentials (#1232).
_CAMEL_CASE_HUMP = r"(?:[A-Z][a-z]+|[A-Z]{2,4}(?=[A-Z][a-z])|[A-Z]{1,4}(?=[0-9]*$))"
_CAMEL_CASE_IDENTIFIER_RE = re.compile(rf"^[a-z]{{2,}}[0-9]*(?:{_CAMEL_CASE_HUMP}[0-9]*)+$")
_CAMEL_CASE_HUMP_RE = re.compile(_CAMEL_CASE_HUMP)
# Credential-length keys are made of real words: several characters per word,
# at most one digit run (``sha256Digest``) and one acronym run, and roughly
# English vowel density. Random letters that happen to fit the shape start a
# hump every ~3 characters, scatter digits and capital runs, and run ~23% vowels.
_CAMEL_CASE_MIN_CHARS_PER_WORD = 4
_CAMEL_CASE_MIN_VOWEL_SHARE = 0.25
_VOWELS = frozenset("aeiouy")
_DIGIT_RUN_RE = re.compile(r"[0-9]+")
_UPPER_RUN_RE = re.compile(r"[A-Z]{2,}")
_BENIGN_FILENAME_RE = re.compile(
    r"^[\w.-]+\.(?:txt|json|yaml|yml|sh|py|js|ts|md|toml|lock|html|proto)$"
)
# Any other lowercase extension (``.go``, ``.java``, ``.swift``, ``.hpp``) is a
# filename only when every stem part is a word: a random stem stays redactable.
_ANY_EXTENSION_FILENAME_RE = re.compile(r"^(?P<stem>[\w.-]+)\.[a-z][a-z0-9]{0,7}$")
_NAME_PART_SPLIT_RE = re.compile(r"[._-]+")
_WORD_PART_RE = re.compile(r"[a-z]+[0-9]*|[0-9]+|[A-Z]{1,6}[0-9]{1,6}")
# PascalCase type and file names (``UserProfileService``, ``HTTPServer``) held
# to the same wordiness rules as camelCase keys.
_PASCAL_CASE_IDENTIFIER_RE = re.compile(
    rf"^(?:[A-Z][a-z]+|[A-Z]{{2,4}}(?=[A-Z][a-z]))[0-9]*(?:{_CAMEL_CASE_HUMP}[0-9]*)*$"
)
# Migration-style names: a timestamp run, then snake_case words.
_TIMESTAMPED_SNAKE_RE = re.compile(r"^[0-9]{6,14}_[a-z][a-z0-9_]*$")
_BENIGN_ISO_TIMESTAMP_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|[+-]\d{2}:\d{2})?$"
)
# GitHub advisory ids use a fixed 4x3 alphabet without vowels or ambiguous digits.
_GHSA_ID_RE = re.compile(r"^GHSA(?:-[23456789cfghjmpqrvwx]{4}){3}$")
# Structural analyzer tokens (``python.lang.security.audit.eval-detected``,
# ``B101:assert_used``, ``tests/test_x.py::test_foo``, ``pkg:pypi/requests@2.31.0``):
# separator-joined parts that are each a word, a number or a short rule code.
_STRUCTURAL_SPLIT_RE = re.compile(r"[.:/@#]+")
_MAX_STRUCTURAL_TOKEN_CHARS = 512
# ``user:pass@host`` (no ``/`` between the ``:`` and the ``@``) is userinfo,
# never a structural id; ``pkg:pypi/requests@2.31.0`` has one.
_USERINFO_SHAPE_RE = re.compile(r"(?:^|//)[^/@\s]*:[^/@\s]*@")
# macOS per-user temp roots (``/private/var/folders/2p/<hash>/T``): the hash
# segment is random by construction, and ``$TMPDIR`` checkouts live under it.
_MACOS_TEMP_ROOT_RE = re.compile(
    r"(?:/private)?/var/folders/[A-Za-z0-9_+-]{2}/[A-Za-z0-9_+-]{1,64}/[A-Z](?=/|$|[^\w/.-])"
)
# Generic http(s) links, host and path only: the query and fragment never join
# the match and stay subject to the normal passes. Userinfo (``user:pw@``) and
# Slack webhooks never match: the host class has no ``@`` and the pattern pass
# blanks webhooks first.
_HTTP_LINK_RE = re.compile(
    r"(?<![\w.+/-])https?://"
    r"(?P<host>[A-Za-z0-9-]{1,63}(?:\.[A-Za-z0-9-]{1,63})+)(?::[0-9]{1,5})?(?![\w-])"
    r"(?P<path>(?:/[\w.~%+-]{0,200}(?![\w.~%+-])){0,32})"
)
# A filename suffix after a path token (the entropy alphabet excludes dots).
# Compiled once and matched *at* a position: slicing the remaining text per
# token made redaction quadratic in the input size.
_PATH_SUFFIX_RE = re.compile(r"\.[a-z][a-z0-9]{0,7}(?![\w.])")
_BENIGN_HTTP_URL_RE = re.compile(r"^https?://[\w.-]+(?::\d+)?(?:/[\w./#:?=&%+-]*)?$")
_LOWERCASE_SLUG_RE = re.compile(r"^[a-z]{12,24}$")
_SLUG_ENTROPY_SLACK = 0.12
# Analyzer metadata assignments (``catalog=unavailable``, ``status=skipped``) —
# exempt before the dense-token pass so glanceable catalog rows survive redaction.
_METADATA_ASSIGNMENT_RE = re.compile(r"^(?P<key>[a-z][a-z0-9_]*)=(?P<value>[a-z][a-z0-9_-]*)$")
_SIMPLE_METADATA_TOKEN_RE = re.compile(r"^[a-z][a-z0-9_-]*$")
# Numeric metadata assignments (``input_tokens=120``, ``output_tokens=4096``, #877).
# A usage count is a handful of digits under a snake_case key; both bounds matter.
# The value is capped at ten digits so a long numeric run (a card or account number)
# is never blanket-exempt, and a key that names a credential keeps the entropy
# pass: ``token`` / ``key`` / ``secret`` as a whole word, never the plural
# ``tokens`` that counts them.
_METADATA_NUMERIC_ASSIGNMENT_RE = re.compile(
    r"^(?P<key>[a-z][a-z0-9]*(?:_[a-z0-9]+)+)=(?P<value>[0-9]{1,10})$"
)
_CREDENTIAL_KEY_WORD_RE = re.compile(
    r"(?:^|_)(?:secret|passwd|password|passphrase|pwd|token|key|apikey|credential|auth|salt|otp"
    r"|pin|cvv|ssn|card)(?:$|_)"
)
# Exact operator-remedy literals that are known-safe and must survive the dense
# entropy pass so a fail-closed message stays actionable. R7-F4: the
# CDP-unavailable remedy names ``--remote-debugging-port``, which is otherwise
# redacted as a secret-shaped hyphenated run. This is an exact-match allowlist:
# no token shaping the pattern space is exempted, so secret redaction is
# unchanged for every value that is not literally one of these strings.
_KNOWN_SAFE_LITERALS: frozenset[str] = frozenset({"--remote-debugging-port"})

# GitHub permalinks (#1281). With an embedded 40/64-hex SHA or run id, a link
# scores ~4.5-4.6 bits/char once the entropy pass sees ``com/<owner>/<repo>/…``
# as one token, and every one of them rendered as ``<redacted>``. Only these
# exact shapes are exempt, and only when the owner, repo and every path segment
# would survive redaction on their own, so a token pasted into the path still
# blanks the link. Query strings and fragments are never part of the match:
# they stay subject to the normal passes.
_GITHUB_PERMALINK_RE = re.compile(
    r"(?<![\w.+/-])https://github\.com/"
    r"(?P<owner>[A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))/"
    r"(?P<repo>[\w.-]{1,100})/"
    r"(?:"
    r"(?:blob|tree|commit)/(?:[a-f0-9]{64}|[a-f0-9]{40})(?![\w-])"
    r"(?P<path>(?:/[\w.-]+)+)?"
    r"|actions/runs/[0-9]{1,20}(?:/job/[0-9]{1,20})?(?![\w-])"
    r"|(?:pull|issues)/[0-9]{1,10}(?![\w-])"
    r")"
)


def _shannon_entropy(value: str) -> float:
    if not value:
        return 0.0
    counts: dict[str, int] = {}
    for char in value:
        counts[char] = counts.get(char, 0) + 1
    length = len(value)
    entropy = 0.0
    for count in counts.values():
        probability = count / length
        entropy -= probability * math.log2(probability)
    return entropy


def _entropy_threshold(length: int) -> float:
    """Length-relative threshold, capped at an absolute bits-per-character ceiling."""
    return min(_ENTROPY_RATIO * math.log2(length), _ENTROPY_ABSOLUTE_CEILING)


def _has_vowel(word: str) -> bool:
    return any(char in _VOWELS for char in word.lower())


def _is_benign_camel_case(token: str) -> bool:
    """Wordy camelCase keys only -- random mixed-case blobs do not qualify (#1232)."""
    if _CAMEL_CASE_IDENTIFIER_RE.match(token) is None:
        return False
    if len(token) < _MIN_ENTROPY_LENGTH:
        return True
    if len(_DIGIT_RUN_RE.findall(token)) > 1 or len(_UPPER_RUN_RE.findall(token)) > 1:
        return False
    humps = _CAMEL_CASE_HUMP_RE.findall(token)
    if len(token) < _CAMEL_CASE_MIN_CHARS_PER_WORD * (1 + len(humps)):
        return False
    # Two-letter words (``Id``, ``By``, ``To``, ``Of``) carry a vowel; ``Qp`` does not.
    if any(len(hump) == 2 and hump[1].islower() and not _has_vowel(hump) for hump in humps):
        return False
    letters = [char for char in token.lower() if char.isalpha()]
    vowels = sum(1 for char in letters if char in _VOWELS)
    return vowels >= _CAMEL_CASE_MIN_VOWEL_SHARE * len(letters)


def _is_benign_pascal_case(token: str) -> bool:
    """Wordy PascalCase type names; random mixed-case blobs do not qualify."""
    if _PASCAL_CASE_IDENTIFIER_RE.match(token) is None:
        return False
    if len(token) < _MIN_ENTROPY_LENGTH:
        return True
    if len(_DIGIT_RUN_RE.findall(token)) > 1 or len(_UPPER_RUN_RE.findall(token)) > 1:
        return False
    humps = _CAMEL_CASE_HUMP_RE.findall(token)
    if len(token) < _CAMEL_CASE_MIN_CHARS_PER_WORD * len(humps):
        return False
    if any(len(hump) == 2 and hump[1].islower() and not _has_vowel(hump) for hump in humps):
        return False
    letters = [char for char in token.lower() if char.isalpha()]
    vowels = sum(1 for char in letters if char in _VOWELS)
    return vowels >= _CAMEL_CASE_MIN_VOWEL_SHARE * len(letters)


def _is_benign_identifier(token: str) -> bool:
    """Catalog identifiers: snake/kebab/SCREAMING case and wordy camel/PascalCase names."""
    return (
        _BENIGN_IDENTIFIER_RE.match(token) is not None
        or _TIMESTAMPED_SNAKE_RE.match(token) is not None
        or _is_benign_camel_case(token)
        or _is_benign_pascal_case(token)
    )


def _is_word_part(part: str) -> bool:
    """One separator-free part of a name: a word, a number, a rule code or an identifier."""
    return _WORD_PART_RE.fullmatch(part) is not None or _is_benign_identifier(part)


def _is_benign_filename(token: str) -> bool:
    """Common repo-relative filenames that are not credential material."""
    if _BENIGN_FILENAME_RE.fullmatch(token) is not None:
        return True
    match = _ANY_EXTENSION_FILENAME_RE.fullmatch(token)
    if match is None:
        return False
    parts = [part for part in _NAME_PART_SPLIT_RE.split(match.group("stem")) if part]
    return bool(parts) and all(_is_word_part(part) for part in parts)


def _is_benign_structural_token(token: str) -> bool:
    """Rule ids, advisory ids, node ids and ``path:line`` values from analyzer reports."""
    if _GHSA_ID_RE.fullmatch(token) is not None:
        return True
    if len(token) > _MAX_STRUCTURAL_TOKEN_CHARS or _STRUCTURAL_SPLIT_RE.search(token) is None:
        return False
    if _USERINFO_SHAPE_RE.search(token) is not None:
        return False
    parts = [part for part in _STRUCTURAL_SPLIT_RE.split(token) if part]
    if len(parts) < 2:
        return False
    for part in parts:
        if _GHSA_ID_RE.fullmatch(part) is not None:
            continue
        words = [word for word in re.split(r"[_-]+", part) if word]
        if not words or not (
            _is_benign_identifier(part) or all(_is_word_part(word) for word in words)
        ):
            return False
    return True


def _is_benign_iso_timestamp(token: str) -> bool:
    """ISO-8601 UTC timestamps from analyzer reports (W6 #537 sweep)."""
    return _BENIGN_ISO_TIMESTAMP_RE.fullmatch(token) is not None


def _is_benign_http_url(token: str) -> bool:
    """Published http(s) links in analyzer output — not credential material."""
    return _BENIGN_HTTP_URL_RE.fullmatch(token) is not None


def _is_benign_lowercase_slug(token: str) -> bool:
    """Lowercase analyzer slugs without separators (W6 #537 sweep: ``psscriptanalyzer``)."""
    if _LOWERCASE_SLUG_RE.fullmatch(token) is None:
        return False
    threshold = _entropy_threshold(len(token)) + _SLUG_ENTROPY_SLACK
    return _shannon_entropy(token) <= threshold


def _is_benign_entropy_token(token: str) -> bool:
    if _BENIGN_PURE_HEX_RE.match(token):
        return _shannon_entropy(token) < _entropy_threshold(len(token))
    if _is_benign_identifier(token):
        return True
    if _is_benign_filename(token):
        return True
    if _is_benign_iso_timestamp(token):
        return True
    if _is_benign_http_url(token):
        return True
    return _is_benign_lowercase_slug(token)


def _is_simple_metadata_token(token: str) -> bool:
    """Low-entropy catalog/status tokens in ``key=value`` metadata assignments."""
    if _is_benign_identifier(token):
        return True
    if _SIMPLE_METADATA_TOKEN_RE.fullmatch(token) is None:
        return False
    if len(token) < _MIN_ENTROPY_LENGTH:
        return True
    if "_" in token or "-" in token:
        return True
    return _shannon_entropy(token) < _entropy_threshold(len(token))


def _is_numeric_metadata_assignment(token: str) -> bool:
    """``snake_case_key=<digits>`` where the key does not name a credential (#877)."""
    match = _METADATA_NUMERIC_ASSIGNMENT_RE.match(token)
    if match is None:
        return False
    return _CREDENTIAL_KEY_WORD_RE.search(match.group("key")) is None


def _is_benign_metadata_assignment(token: str) -> bool:
    """``key=value`` analyzer metadata where both sides are low-entropy identifiers."""
    if _is_numeric_metadata_assignment(token):
        return True
    match = _METADATA_ASSIGNMENT_RE.match(token)
    if match is None:
        return False
    key = match.group("key")
    value = match.group("value")
    return _is_simple_metadata_token(key) and _is_simple_metadata_token(value)


def _should_force_redact_dense_token(token: str) -> bool:
    unique = len(set(token))
    if unique < 8 or len(token) >= _DENSE_TOKEN_MAX_LENGTH:
        return False
    return unique / len(token) > 0.25


def _looks_like_repo_path_token(token: str) -> bool:
    """Repo-relative path prefixes are not secrets — preserve for CI blame paths."""
    if "/" not in token or _REPO_PATH_TOKEN_RE.match(token) is None:
        return False
    segments = [segment for segment in token.split("/") if segment]
    if not segments or not all(re.search(r"[A-Za-z]", segment) for segment in segments):
        return False
    last = segments[-1]
    return "." in last or _is_benign_filename(token)


def _is_benign_path_stem_segment(segment: str) -> bool:
    """Recognize bounded ordinary path segments before a filename suffix."""
    if re.fullmatch(r"[a-z_][a-z0-9_-]{0,14}", segment):
        return True
    if len(segment) > 32 or not _is_benign_identifier(segment):
        return False
    # SCREAMING_SNAKE, or an ordinary word/camelCase directory name (``mergeCraft``)
    # with only a few capitals; a mixed-case random blob has many (#1255).
    return segment == segment.upper() or sum(char.isupper() for char in segment) <= 3


def _is_ordinary_permalink_segment(segment: str) -> bool:
    """A permalink owner/repo/path segment that would survive redaction on its own."""
    if not segment or segment in {".", ".."}:
        return False
    return _entropy_redact(segment) == segment and (
        _maybe_redact_entire_string(segment, segment) == segment
    )


def _is_exempt_github_permalink(match: re.Match[str]) -> bool:
    segments = [match.group("owner"), match.group("repo")]
    path = match.group("path")
    if path:
        segments.extend(path.removeprefix("/").split("/"))
    return all(_is_ordinary_permalink_segment(segment) for segment in segments)


def _is_ordinary_link_segment(segment: str) -> bool:
    """A link host label or path segment made of words that survives redaction alone."""
    if _GHSA_ID_RE.fullmatch(segment) is not None:
        return True
    parts = [part for part in re.split(r"[._~%+-]+", segment) if part]
    return all(_is_word_part(part) for part in parts) and _is_ordinary_permalink_segment(segment)


def _is_exempt_http_link(match: re.Match[str]) -> bool:
    """A documentation or advisory link (``https://avd.aquasec.com/nvd/cve-2024-35195``)."""
    labels = match.group("host").split(".")
    segments = [segment for segment in match.group("path").split("/") if segment]
    return all(_is_ordinary_link_segment(part) for part in [*labels, *segments])


def _exempt_spans(text: str) -> list[tuple[int, int]]:
    """Spans the entropy pass must not see: ordinary links and macOS temp roots.

    Each span is structural by construction (an exempt GitHub permalink, a link
    whose host and path are ordinary words, or a ``/var/folders/<hash>/T`` temp
    root) and is kept verbatim; everything around it is redacted as usual.
    """
    spans: list[tuple[int, int]] = []
    if "https://github.com/" in text:
        spans.extend(
            match.span()
            for match in _GITHUB_PERMALINK_RE.finditer(text)
            if _is_exempt_github_permalink(match)
        )
    if "/var/folders/" in text:
        spans.extend(match.span() for match in _MACOS_TEMP_ROOT_RE.finditer(text))
    if "://" in text:
        spans.extend(
            match.span()
            for match in _HTTP_LINK_RE.finditer(text)
            if match.group("path") and _is_exempt_http_link(match)
        )
    if len(spans) < 2:
        return spans
    merged: list[tuple[int, int]] = []
    for start, end in sorted(spans):
        if merged and start < merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return merged


def _strip_exempt_spans(text: str) -> str:
    spans = _exempt_spans(text)
    if not spans:
        return text
    parts: list[str] = []
    cursor = 0
    for start, end in spans:
        parts.append(text[cursor:start])
        cursor = end
    parts.append(text[cursor:])
    return "".join(parts)


def _entropy_redact_outside_exempt_spans(text: str) -> str:
    """Run the entropy pass on everything except exempt links and temp roots (#1281)."""
    spans = _exempt_spans(text)
    if not spans:
        return _entropy_redact(text)
    parts: list[str] = []
    cursor = 0
    for start, end in spans:
        parts.append(_entropy_redact(text[cursor:start]))
        parts.append(text[start:end])
        cursor = end
    parts.append(_entropy_redact(text[cursor:]))
    return "".join(parts)


def _entropy_redact(text: str) -> str:
    def replacer(match: re.Match[str]) -> str:
        token = match.group(0)
        if token in _KNOWN_SAFE_LITERALS:
            return token
        if "/" in token:
            # The entropy alphabet excludes dots, so inspect a bounded filename
            # suffix before classifying a normal path prefix as a dense token.
            # An absolute directory path needs no suffix. A leading "/" yields
            # one empty segment (#1255); every real segment must still be an
            # ordinary, bounded word.
            absolute = token.startswith("/") and token.count("/") >= 2
            if absolute or _PATH_SUFFIX_RE.match(text, match.end()) is not None:
                segments = token.removeprefix("/").split("/")
                if all(_is_benign_path_stem_segment(part) for part in segments):
                    return token
        if _looks_like_repo_path_token(token):
            return token
        if len(token) < _MIN_ENTROPY_LENGTH:
            return token
        if _BENIGN_HEX_40_RE.match(token) or _BENIGN_HEX_64_RE.match(token):
            return token
        if _is_benign_identifier(token):
            return token
        if _GHSA_ID_RE.fullmatch(token) is not None:
            return token
        if _is_benign_filename(token):
            return token
        if _is_benign_iso_timestamp(token):
            return token
        if _is_benign_http_url(token):
            return token
        if _is_benign_lowercase_slug(token):
            return token
        if _is_benign_metadata_assignment(token):
            return token
        if _should_force_redact_dense_token(token):
            return REDACTION_SENTINEL
        if _is_benign_entropy_token(token):
            return token
        if _shannon_entropy(token) >= _entropy_threshold(len(token)):
            return REDACTION_SENTINEL
        return token

    return _ENTROPY_TOKEN_RE.sub(replacer, text)


def _redact_assignment(match: re.Match[str]) -> str:
    """Preserve trailing delimiters after matching the complete assignment value."""
    value = match.group("unquoted") or ""
    suffix_start = len(value.rstrip("]})"))
    return REDACTION_SENTINEL + value[suffix_start:]


def _redact_bearer(match: re.Match[str]) -> str:
    return match.group("scheme") + REDACTION_SENTINEL


def _pattern_redact(text: str) -> str:
    redacted = text
    for pattern in _SECRET_PATTERNS:
        replacement = _redact_assignment if pattern in _ASSIGNMENT_PATTERNS else REDACTION_SENTINEL
        redacted = pattern.sub(replacement, redacted)
    return _BEARER_TOKEN_PATTERN.sub(_redact_bearer, redacted)


def _maybe_redact_entire_string(text: str, redacted: str) -> str:
    """Redact credential-shaped single tokens that fall outside the ASCII entropy regex."""
    if redacted != text:
        return redacted
    if text in _KNOWN_SAFE_LITERALS:
        return redacted
    if len(text) < _MIN_ENTROPY_LENGTH or any(char.isspace() for char in text):
        return redacted
    residual = _strip_exempt_spans(text)
    if residual != text:
        # ``(https://github.com/o/r/pull/1).``: only what surrounds the exempt
        # span decides; the span itself already passed its own checks.
        if residual and _maybe_redact_entire_string(residual, residual) == REDACTION_SENTINEL:
            return REDACTION_SENTINEL
        return redacted
    if _BENIGN_HEX_40_RE.match(text) or _BENIGN_HEX_64_RE.match(text):
        return redacted
    if _looks_like_repo_path_token(text):
        return redacted
    if _is_benign_identifier(text):
        return redacted
    if _is_benign_filename(text):
        return redacted
    if _is_benign_iso_timestamp(text):
        return redacted
    if _is_benign_http_url(text):
        return redacted
    if _is_benign_lowercase_slug(text):
        return redacted
    if _is_benign_metadata_assignment(text):
        return redacted
    if _is_benign_structural_token(text.removeprefix("file://")):
        return redacted
    if _should_force_redact_dense_token(text):
        return REDACTION_SENTINEL
    if _is_benign_entropy_token(text):
        return redacted
    if len(set(text)) >= 8 and _shannon_entropy(text) >= _entropy_threshold(len(text)):
        return REDACTION_SENTINEL
    return redacted


def redact_known_secret_patterns(text: str) -> str:
    """Redact only the explicit secret shapes (``sk-…``, ``ghp_…``, ``AKIA…``, assignments).

    For values that are identifiers by construction — model slugs, hex run ids —
    where the entropy heuristic in :func:`redact_secrets` would mask the value
    itself (``deepseek-v4.1-flash`` reads as a dense token).
    """
    return _pattern_redact(text) if text else text


def redact_secrets(text: str) -> str:
    """Redact secret-like values from arbitrary text by pattern and entropy."""
    if not text:
        return text
    redacted = _entropy_redact_outside_exempt_spans(_pattern_redact(text))
    return _maybe_redact_entire_string(text, redacted)


def _redact_json_value(value: Any) -> Any:
    return redact_structured_value(value, redact_string=redact_secrets)


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


# Errors a JSON decode of untrusted output can raise: deep nesting overflows
# the decoder's recursion guard rather than failing as a ``JSONDecodeError``.
_JSON_DECODE_ERRORS = (json.JSONDecodeError, RecursionError, ValueError)
# Failed ``raw_decode`` attempts tolerated before the rest of the text is
# redacted as plain text. Each failed attempt can scan to the end of the input,
# so an unbounded loop over every brace was quadratic (``"[" * 32000``).
_MAX_FAILED_JSON_DECODES = 64


def _looks_like_jsonl(raw: str) -> bool:
    lines = [line for line in raw.splitlines() if line.strip()]
    if not lines:
        return False
    for line in lines:
        try:
            json.loads(line)
        except _JSON_DECODE_ERRORS:
            return False
    return True


def _redact_jsonl(raw: str) -> str:
    out_lines: list[str] = []
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            out_lines.append(line)
            continue
        try:
            payload = json.loads(line)
        except _JSON_DECODE_ERRORS:
            out_lines.append(redact_secrets(line))
        else:
            out_lines.append(_json_dumps(_redact_json_value(payload)))
    suffix = "\n" if raw.endswith("\n") else ""
    return "\n".join(out_lines) + suffix


def _redact_json_text(raw: str) -> str | None:
    stripped = raw.strip()
    if not stripped:
        return raw
    try:
        payload = json.loads(stripped)
    except _JSON_DECODE_ERRORS:
        pass
    else:
        if isinstance(payload, (dict, list)):
            prefix = raw[: len(raw) - len(raw.lstrip())]
            suffix = raw[len(raw.rstrip()) :]
            return prefix + _json_dumps(_redact_json_value(payload)) + suffix

    decoder = json.JSONDecoder()
    index = 0
    length = len(raw)
    parts: list[str] = []
    # Text between JSON documents is a secret carrier like any other. It used
    # to be copied through verbatim, so output that *began* with valid JSON --
    # which is what routes here at all -- returned its plaintext tail
    # unredacted: ``{"a":1} token=ghp_...`` leaked the token. Literal runs are
    # buffered and redacted as a unit rather than per slice, so a brace that
    # splits one run cannot split a secret out of the pattern's reach.
    literal: list[str] = []
    found_json = False
    failed_decodes = 0

    def _flush_literal() -> None:
        if literal:
            parts.append(redact_secrets("".join(literal)))
            literal.clear()

    while index < length:
        char = raw[index]
        if char not in "{[":
            next_json = index
            while next_json < length and raw[next_json] not in "{[":
                next_json += 1
            literal.append(raw[index:next_json])
            index = next_json
            continue
        if failed_decodes >= _MAX_FAILED_JSON_DECODES:
            literal.append(raw[index:])
            break
        try:
            payload, end = decoder.raw_decode(raw, index)
        except _JSON_DECODE_ERRORS:
            failed_decodes += 1
            literal.append(raw[index])
            index += 1
            continue
        found_json = True
        _flush_literal()
        parts.append(_json_dumps(_redact_json_value(payload)))
        index = end if end > index else index + 1
    _flush_literal()
    if not found_json:
        return None
    return "".join(parts)


def redact_analyzer_output(raw: str, *, tool_id: str) -> str:
    """Redact analyzer stdout/stderr before any downstream consumer. Never raises.

    Output that nests too deeply to walk structurally is redacted as plain text.
    """
    _ = tool_id
    if not raw:
        return raw
    stripped = raw.lstrip()
    if not stripped.startswith(("{", "[")):
        return redact_secrets(raw)
    try:
        if _looks_like_jsonl(raw):
            return _redact_jsonl(raw)
        redacted = _redact_json_text(raw)
    except RecursionError:
        return redact_secrets(raw)
    if redacted is not None:
        return redacted
    return redact_secrets(raw)


def redact_for_fingerprint(body: str, *, tool_id: str) -> str:
    """Redact text that feeds finding fingerprint inputs."""
    _ = tool_id
    return redact_secrets(body)


def cache_key_fragment(material: str, *, tool_id: str) -> str:
    """Return a cache-key fragment with secrets removed."""
    _ = tool_id
    return hashlib.sha256(redact_secrets(material).encode()).hexdigest()


def redact_log_message(message: str) -> str:
    """Filter hook for loguru sinks."""
    if isinstance(message, str):
        return redact_secrets(message)
    return str(message)


def install_loguru_redaction_filter() -> None:
    """Register the message redactor on the composed loguru patcher.

    Fills ``utils.log``'s redactor slot with :func:`redact_log_message` and
    reinstalls the same composed patcher there, so every installed patcher both
    carries bound run context and strips secret values from ``record["message"]``
    — in either install order. ``utils.log`` never imports this module (CR-D3).
    """
    from mergecraft.utils.log import set_message_redactor

    set_message_redactor(redact_log_message)


def _looks_like_secret_shape(token: str) -> bool:
    """True when ``token`` matches a known credential prefix or dense secret shape."""
    for pattern in _SECRET_PATTERNS:
        if pattern.search(token):
            return True
    if len(token) < _MIN_ENTROPY_LENGTH:
        return False
    if _looks_like_repo_path_token(token) or _is_benign_filename(token):
        return False
    if (
        _is_benign_identifier(token)
        or _is_benign_lowercase_slug(token)
        or _is_benign_iso_timestamp(token)
        or _is_benign_http_url(token)
    ):
        return False
    if _BENIGN_HEX_40_RE.match(token) or _BENIGN_HEX_64_RE.match(token):
        return False
    if _is_benign_metadata_assignment(token):
        return False
    unique = len(set(token))
    if unique >= 8 and _shannon_entropy(token) >= _entropy_threshold(len(token)):
        return True
    return _should_force_redact_dense_token(token)


def _looks_like_benign_harmful_shape(token: str) -> bool:
    """True for analyzer-output tokens the W6 sweep proved lose operator signal when redacted."""
    if _looks_like_secret_shape(token):
        return False
    return (
        _is_benign_identifier(token)
        or _looks_like_repo_path_token(token)
        or _is_benign_filename(token)
        or _is_benign_iso_timestamp(token)
        or _is_benign_http_url(token)
        or _is_benign_lowercase_slug(token)
    )


def classify_entropy_redaction_hits(hits: Iterable[Any]) -> dict[str, list[dict[str, str]]]:
    """Classify entropy-sweep hits for operator review (wave 15 W6 / D13)."""
    secret_confirmed: list[dict[str, str]] = []
    benign_candidates: list[dict[str, str]] = []
    for hit in hits:
        token = str(getattr(hit, "token", ""))
        record = {
            "analyzer_id": str(getattr(hit, "analyzer_id", "")),
            "token": token,
            "context": str(getattr(hit, "context", "")),
        }
        if _looks_like_secret_shape(token):
            secret_confirmed.append(record)
        elif _looks_like_benign_harmful_shape(token):
            benign_candidates.append({**record, "classification": "benign_harmful_to_redact"})
    return {
        "benign_candidates": benign_candidates,
        "secret_confirmed": secret_confirmed,
    }


__all__ = [
    "cache_key_fragment",
    "classify_entropy_redaction_hits",
    "install_loguru_redaction_filter",
    "redact_analyzer_output",
    "redact_for_fingerprint",
    "redact_known_secret_patterns",
    "redact_log_message",
    "redact_secrets",
]
