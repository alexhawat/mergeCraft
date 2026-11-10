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

_ASSIGNMENT_SECRET_PATTERN: Pattern[str] = re.compile(
    r"\b(?:api[_-]?key|secret|token|password)\s*[:=]\s*"
    r"""(?:"(?:\\.|[^"\\]){8,}"|'(?:\\.|[^'\\]){8,}'|"""
    r"(?P<unquoted>[^\s'\"]{8,}))",
    re.I,
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
    _ASSIGNMENT_SECRET_PATTERN,
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
_BENIGN_ISO_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z?$")
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


def _is_benign_identifier(token: str) -> bool:
    """Catalog identifiers: snake/kebab/SCREAMING case and wordy camelCase keys."""
    return _BENIGN_IDENTIFIER_RE.match(token) is not None or _is_benign_camel_case(token)


def _is_benign_filename(token: str) -> bool:
    """Common repo-relative filenames that are not credential material."""
    return _BENIGN_FILENAME_RE.fullmatch(token) is not None


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


def _strip_exempt_github_permalinks(text: str) -> str:
    if "https://github.com/" not in text:
        return text
    return _GITHUB_PERMALINK_RE.sub(
        lambda match: "" if _is_exempt_github_permalink(match) else match.group(0), text
    )


def _entropy_redact_outside_permalinks(text: str) -> str:
    """Run the entropy pass on everything except exempt GitHub permalinks (#1281)."""
    if "https://github.com/" not in text:
        return _entropy_redact(text)
    parts: list[str] = []
    cursor = 0
    for match in _GITHUB_PERMALINK_RE.finditer(text):
        if not _is_exempt_github_permalink(match):
            continue
        parts.append(_entropy_redact(text[cursor : match.start()]))
        parts.append(match.group(0))
        cursor = match.end()
    parts.append(_entropy_redact(text[cursor:]))
    return "".join(parts)


def _entropy_redact(text: str) -> str:
    def replacer(match: re.Match[str]) -> str:
        token = match.group(0)
        if token in _KNOWN_SAFE_LITERALS:
            return token
        # The entropy alphabet excludes dots, so inspect a bounded filename
        # suffix before classifying a normal path prefix as a dense token.
        suffix = re.match(
            r"\.(?:py|js|ts|md|json|yaml|yml|toml|sh|txt)(?![\w.])", text[match.end() :]
        )
        if suffix and "/" in token:
            # An absolute path's leading "/" yields one empty segment (#1255);
            # every real segment must still be an ordinary, bounded word.
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
        replacement = (
            _redact_assignment if pattern is _ASSIGNMENT_SECRET_PATTERN else REDACTION_SENTINEL
        )
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
    residual = _strip_exempt_github_permalinks(text)
    if residual != text:
        # ``(https://github.com/o/r/pull/1).``: only what surrounds the exempt
        # permalink decides; the link itself already passed its segment checks.
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
    redacted = _entropy_redact_outside_permalinks(_pattern_redact(text))
    return _maybe_redact_entire_string(text, redacted)


def _redact_json_value(value: Any) -> Any:
    return redact_structured_value(value, redact_string=redact_secrets)


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _looks_like_jsonl(raw: str) -> bool:
    lines = [line for line in raw.splitlines() if line.strip()]
    if not lines:
        return False
    for line in lines:
        try:
            json.loads(line)
        except json.JSONDecodeError:
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
        except json.JSONDecodeError:
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
    except json.JSONDecodeError:
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
        try:
            payload, end = decoder.raw_decode(raw, index)
        except json.JSONDecodeError:
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
    """Redact analyzer stdout/stderr before any downstream consumer."""
    _ = tool_id
    if not raw:
        return raw
    stripped = raw.lstrip()
    if not stripped.startswith(("{", "[")):
        return redact_secrets(raw)
    if _looks_like_jsonl(raw):
        return _redact_jsonl(raw)
    redacted = _redact_json_text(raw)
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
