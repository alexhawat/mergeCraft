"""The ``lite`` review driver: one capped HTTP call, the diff inlined, nothing else.

``mergecraft.agents.lite.run_lite_review`` is the only direct-LLM path in mergeCraft. It
makes exactly one ``POST {base_url}/chat/completions`` to an operator-registered
OpenAI-compatible provider — no checkout, no MCP server, no CLI harness, no streaming,
no tools — and returns a :class:`LiteOutcome`.

The cap is enforced **before** the call: an upper-bound prompt estimate
(``ceil(prompt_bytes / 3)``) plus ``maxOutputTokens`` must fit ``tokenCap``; otherwise
the outcome is ``downgraded`` (the run gets a full review) and the network is never
touched. A missing credential or an unregistered provider is ``downgraded`` the same
way. After the call the provider's ``usage.total_tokens`` (or an estimate, flagged) is
recorded, and usage over the cap is ``cap_hit``. A response that is not the strict
``{"findings": [...], "summary": ...}`` object is ``failed`` — never silently a full
review, never a success.

Tests drive the driver through an ``http_client_factory`` that returns an
``httpx.AsyncClient`` on an ``httpx.MockTransport``, so no request leaves the process.
"""

from __future__ import annotations

import asyncio
import json
import math
import re
import subprocess
import tempfile
from typing import TYPE_CHECKING, Any

import httpx
import pytest

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from mergecraft.config.settings import RepoSettings


_BASE_URL = "https://llm.example.com/v1"
_API_KEY = "sk-lite-test-key"
_ENV_KEY = "LLM_PROVIDER_7_API_KEY"
_MODEL = "tiny-1"
_CAP = 20_000
_MAX_OUT = 1_000


def _lite_api() -> Any:
    from importlib import import_module

    return import_module("mergecraft.agents.lite")


def _settings(
    *,
    cap: int = _CAP,
    max_out: int = _MAX_OUT,
    provider: str = "cheapo",
    url: str = _BASE_URL,
) -> RepoSettings:
    from mergecraft.config.settings import RepoSettings

    return RepoSettings.model_validate(
        {
            "providers": [{"label": "cheapo", "url": url, "harness": "opencode", "envIndex": 7}],
            "review": {
                "fastPath": {
                    "enabled": True,
                    "lite": {
                        "enabled": True,
                        "provider": provider,
                        "model": _MODEL,
                        "tokenCap": cap,
                        "maxOutputTokens": max_out,
                    },
                }
            },
        }
    )


def _decision(cap: int = _CAP) -> Any:
    from mergecraft.classify.triage import TriageDecision

    return TriageDecision(
        tier="lite",
        recognizer="whitespace",
        reason="whitespace matched but is not enabled in review.fastPath.skipLlm",
        token_cap=cap,
    )


def _diff(*added: str, path: str = "src/app.js") -> str:
    body = "".join(f"+{line}\n" for line in added)
    return (
        f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n"
        f"@@ -1,1 +1,{len(added) + 1} @@\n let keep = 1;\n{body}"
    )


_SMALL_DIFF = _diff("// LITE-MARKER-7f3a explain the retry loop")


def _finding(n: int = 1, severity: str = "Minor") -> dict[str, Any]:
    return {"path": "src/app.js", "line": n, "severity": severity, "message": f"note {n}"}


def _completion(content: object, *, usage: dict[str, int] | None = None) -> dict[str, Any]:
    text = content if isinstance(content, str) else json.dumps(content)
    body: dict[str, Any] = {
        "id": "chatcmpl-1",
        "object": "chat.completion",
        "model": _MODEL,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }
        ],
    }
    if usage is not None:
        body["usage"] = usage
    return body


_DEFAULT_USAGE = {"prompt_tokens": 900, "completion_tokens": 100, "total_tokens": 1_000}


class _Gateway:
    """A scripted OpenAI-compatible endpoint behind ``httpx.MockTransport``."""

    def __init__(
        self,
        *,
        body: dict[str, Any] | None = None,
        status: int = 200,
        error: Exception | None = None,
        forbidden: bool = False,
    ) -> None:
        self.body = (
            body
            if body is not None
            else _completion(
                {"findings": [_finding()], "summary": "one note"}, usage=_DEFAULT_USAGE
            )
        )
        self.status = status
        self.error = error
        self.forbidden = forbidden
        self.requests: list[httpx.Request] = []

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.forbidden:
            msg = f"lite must not reach the network here: {request.method} {request.url}"
            raise AssertionError(msg)
        if self.error is not None:
            raise self.error
        return httpx.Response(self.status, json=self.body)

    def factory(self, *_args: Any, **_kwargs: Any) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self._handle))


@pytest.fixture
def credential(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv(_ENV_KEY, _API_KEY)
    return _API_KEY


async def _run(
    gateway: _Gateway,
    *,
    diff_text: str = _SMALL_DIFF,
    settings: RepoSettings | None = None,
    decision: Any = None,
) -> Any:
    run: Callable[..., Any] = _lite_api().run_lite_review
    return await run(
        decision=decision if decision is not None else _decision(),
        diff_text=diff_text,
        settings=settings if settings is not None else _settings(),
        http_client_factory=gateway.factory,
    )


def _request_json(request: httpx.Request) -> dict[str, Any]:
    payload = json.loads(request.content.decode("utf-8"))
    assert isinstance(payload, dict)
    return payload


def _message_text(payload: dict[str, Any]) -> str:
    parts: list[str] = []
    for message in payload.get("messages", []):
        content = message.get("content")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            parts.extend(str(part.get("text", "")) for part in content if isinstance(part, dict))
    return "\n".join(parts)


# ── happy path ────────────────────────────────────────────────────────────────


async def test_a_successful_call_is_reviewed_with_the_parsed_findings(credential: str) -> None:
    del credential
    findings = [_finding(3, "Major"), _finding(9, "Trivial")]
    gateway = _Gateway(
        body=_completion({"findings": findings, "summary": "two notes"}, usage=_DEFAULT_USAGE)
    )

    outcome = await _run(gateway)

    assert outcome.status == "reviewed"
    assert outcome.findings == findings
    assert outcome.summary == "two notes"
    assert outcome.tokens_used == 1_000
    assert outcome.usage_estimated is False
    assert outcome.cap_hit is False


async def test_the_outcome_records_the_versioned_prompt(credential: str) -> None:
    del credential
    api = _lite_api()

    outcome = await _run(_Gateway())

    assert isinstance(api.LITE_PROMPT_VERSION, str)
    assert api.LITE_PROMPT_VERSION.strip()
    assert outcome.prompt_version == api.LITE_PROMPT_VERSION


async def test_exactly_one_post_reaches_chat_completions(credential: str) -> None:
    gateway = _Gateway()

    await _run(gateway)

    assert len(gateway.requests) == 1
    request = gateway.requests[0]
    assert request.method == "POST"
    assert str(request.url) == f"{_BASE_URL}/chat/completions"
    assert request.headers["authorization"] == f"Bearer {credential}"


async def test_the_request_is_one_bounded_non_streaming_call_without_tools(
    credential: str,
) -> None:
    del credential
    gateway = _Gateway()

    await _run(gateway, settings=_settings(max_out=1_234))

    payload = _request_json(gateway.requests[0])
    assert payload["model"] == _MODEL
    assert payload["max_tokens"] == 1_234
    assert payload.get("stream", False) is False
    assert "tools" not in payload
    assert "functions" not in payload
    roles = [message.get("role") for message in payload["messages"]]
    assert "system" in roles


async def test_the_whole_diff_is_inlined_in_the_prompt_untruncated(credential: str) -> None:
    del credential
    gateway = _Gateway()
    diff = _diff(*(f"// line {n} of a medium comment block" for n in range(200)))

    outcome = await _run(gateway, diff_text=diff)

    assert outcome.status == "reviewed"
    text = _message_text(_request_json(gateway.requests[0]))
    assert diff.strip() in text


async def test_a_trailing_slash_on_the_registry_url_does_not_double_the_path(
    credential: str,
) -> None:
    del credential
    gateway = _Gateway()

    await _run(gateway, settings=_settings(url=f"{_BASE_URL}/"))

    assert str(gateway.requests[0].url) == f"{_BASE_URL}/chat/completions"


@pytest.mark.parametrize("severity", ["Critical", "Major", "Minor", "Trivial"])
async def test_every_finding_severity_is_accepted(credential: str, severity: str) -> None:
    del credential
    from mergecraft.review_taxonomy import FINDING_SEVERITIES

    gateway = _Gateway(
        body=_completion(
            {"findings": [_finding(1, severity)], "summary": "s"}, usage=_DEFAULT_USAGE
        )
    )

    outcome = await _run(gateway)

    assert severity in FINDING_SEVERITIES
    assert outcome.status == "reviewed"
    assert outcome.findings[0]["severity"] == severity


async def test_an_empty_findings_list_is_a_clean_review(credential: str) -> None:
    del credential
    gateway = _Gateway(
        body=_completion({"findings": [], "summary": "nothing"}, usage=_DEFAULT_USAGE)
    )

    outcome = await _run(gateway)

    assert outcome.status == "reviewed"
    assert outcome.findings == []
    assert outcome.summary == "nothing"


async def test_fifty_findings_is_the_inclusive_bound(credential: str) -> None:
    del credential
    findings = [_finding(n) for n in range(1, 51)]
    gateway = _Gateway(
        body=_completion({"findings": findings, "summary": "s"}, usage=_DEFAULT_USAGE)
    )

    outcome = await _run(gateway)

    assert outcome.status == "reviewed"
    assert len(outcome.findings) == 50


# ── the cap is enforced before the call ───────────────────────────────────────


async def test_a_diff_over_the_cap_is_downgraded_before_any_request(credential: str) -> None:
    del credential
    gateway = _Gateway(forbidden=True)
    big = _diff(*("// " + "x" * 120 for _ in range(600)))  # ~74 KB -> ~25k tokens

    outcome = await _run(gateway, diff_text=big)

    assert gateway.requests == []
    assert outcome.status == "downgraded"
    assert "exceeds the lite token cap" in outcome.reason
    assert outcome.tokens_used is None
    assert outcome.findings == []


async def test_the_downgrade_reason_states_the_estimate_and_the_cap(credential: str) -> None:
    del credential
    gateway = _Gateway(forbidden=True)
    big = _diff(*("// " + "y" * 120 for _ in range(600)))

    outcome = await _run(gateway, diff_text=big)

    match = re.search(r"estimated (\d+) > cap (\d+)", outcome.reason)
    assert match is not None, outcome.reason
    estimated, cap = int(match.group(1)), int(match.group(2))
    assert cap == _CAP
    assert estimated > cap
    assert estimated >= math.ceil(len(big.encode("utf-8")) / 3)
    assert gateway.requests == []


async def test_the_estimate_counts_bytes_not_characters(credential: str) -> None:
    """``€`` is three UTF-8 bytes: counted by character this diff would fit the cap."""
    del credential
    gateway = _Gateway(forbidden=True)
    diff = _diff(*("// " + "€" * 100 for _ in range(300)))  # 30k chars, ~90 KB

    assert math.ceil(len(diff) / 3) + _MAX_OUT < _CAP, "premise: fits when counted by char"
    outcome = await _run(gateway, diff_text=diff)

    assert outcome.status == "downgraded"
    assert "exceeds the lite token cap" in outcome.reason
    assert gateway.requests == []


async def test_max_output_tokens_counts_toward_the_cap(credential: str) -> None:
    del credential
    roomy = _Gateway()
    tight = _Gateway(forbidden=True)

    fits = await _run(roomy, settings=_settings(cap=_CAP, max_out=_MAX_OUT))
    reserved = await _run(tight, settings=_settings(cap=4_000, max_out=3_990))

    assert fits.status == "reviewed"
    assert len(roomy.requests) == 1
    assert reserved.status == "downgraded"
    assert "exceeds the lite token cap" in reserved.reason
    assert tight.requests == []


# ── credentials and provider resolution ───────────────────────────────────────


async def test_a_missing_credential_downgrades_before_any_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(_ENV_KEY, raising=False)
    gateway = _Gateway(forbidden=True)

    outcome = await _run(gateway)

    assert gateway.requests == []
    assert outcome.status == "downgraded"
    assert "cheapo" in outcome.reason


async def test_an_unregistered_provider_downgrades_before_any_request(credential: str) -> None:
    del credential
    gateway = _Gateway(forbidden=True)

    outcome = await _run(gateway, settings=_settings(provider="nobody"))

    assert gateway.requests == []
    assert outcome.status == "downgraded"
    assert "nobody" in outcome.reason


async def test_the_credential_never_appears_in_the_outcome(credential: str) -> None:
    gateway = _Gateway(status=401, body={"error": {"message": f"bad key {credential}"}})

    outcome = await _run(gateway)

    assert outcome.status == "failed"
    assert credential not in outcome.reason
    assert credential not in repr(outcome)


# ── usage accounting ──────────────────────────────────────────────────────────


async def test_a_response_without_usage_is_estimated_and_flagged(credential: str) -> None:
    del credential
    gateway = _Gateway(body=_completion({"findings": [], "summary": "s"}, usage=None))

    outcome = await _run(gateway)

    assert outcome.status == "reviewed"
    assert outcome.usage_estimated is True
    assert isinstance(outcome.tokens_used, int)
    assert outcome.tokens_used >= math.ceil(len(_SMALL_DIFF.encode("utf-8")) / 3)


async def test_usage_over_the_cap_is_a_cap_hit(credential: str) -> None:
    del credential
    usage = {"prompt_tokens": _CAP, "completion_tokens": 1, "total_tokens": _CAP + 1}
    gateway = _Gateway(body=_completion({"findings": [], "summary": "s"}, usage=usage))

    outcome = await _run(gateway)

    assert outcome.tokens_used == _CAP + 1
    assert outcome.cap_hit is True
    assert outcome.usage_estimated is False
    assert len(gateway.requests) == 1


async def test_usage_exactly_at_the_cap_is_not_a_cap_hit(credential: str) -> None:
    del credential
    usage = {"prompt_tokens": _CAP - 1, "completion_tokens": 1, "total_tokens": _CAP}
    gateway = _Gateway(body=_completion({"findings": [], "summary": "s"}, usage=usage))

    outcome = await _run(gateway)

    assert outcome.tokens_used == _CAP
    assert outcome.cap_hit is False
    assert outcome.status == "reviewed"


# ── malformed output is a failed run, never a success ─────────────────────────


@pytest.mark.parametrize(
    "content",
    [
        "this is not json",
        "[]",
        json.dumps(["findings"]),
        json.dumps({"summary": "no findings key"}),
        json.dumps({"findings": "none", "summary": "s"}),
        json.dumps(
            {"findings": [{"path": "a.js", "line": 1, "severity": "Minor"}], "summary": "s"}
        ),
        json.dumps(
            {"findings": [{"line": 1, "severity": "Minor", "message": "m"}], "summary": "s"}
        ),
        json.dumps({"findings": [_finding(1, "Blocker")], "summary": "s"}),
        json.dumps({"findings": [_finding(1, "major")], "summary": "s"}),
        json.dumps({"findings": ["not an object"], "summary": "s"}),
    ],
    ids=[
        "prose",
        "empty-array",
        "array",
        "no-findings",
        "findings-not-a-list",
        "finding-without-message",
        "finding-without-path",
        "unknown-severity",
        "lowercase-severity",
        "finding-not-an-object",
    ],
)
async def test_a_malformed_response_is_a_failed_lite_run(credential: str, content: str) -> None:
    del credential
    gateway = _Gateway(body=_completion(content, usage=_DEFAULT_USAGE))

    outcome = await _run(gateway)

    assert outcome.status == "failed"
    assert outcome.findings == []
    assert outcome.reason.strip()
    assert len(gateway.requests) == 1


async def test_more_than_fifty_findings_is_a_failed_lite_run(credential: str) -> None:
    del credential
    findings = [_finding(n) for n in range(1, 52)]
    gateway = _Gateway(
        body=_completion({"findings": findings, "summary": "s"}, usage=_DEFAULT_USAGE)
    )

    outcome = await _run(gateway)

    assert outcome.status == "failed"
    assert outcome.findings == []


async def test_a_body_without_choices_is_a_failed_lite_run(credential: str) -> None:
    del credential
    gateway = _Gateway(body={"object": "error", "message": "upstream unavailable"})

    outcome = await _run(gateway)

    assert outcome.status == "failed"
    assert outcome.findings == []


@pytest.mark.parametrize("status", [400, 429, 500, 503])
async def test_an_http_error_status_is_a_failed_lite_run(credential: str, status: int) -> None:
    del credential
    gateway = _Gateway(status=status, body={"error": {"message": "nope"}})

    outcome = await _run(gateway)

    assert outcome.status == "failed"
    assert str(status) in outcome.reason
    assert len(gateway.requests) == 1


async def test_a_transport_error_is_a_failed_lite_run_not_an_exception(credential: str) -> None:
    del credential
    gateway = _Gateway(error=httpx.ConnectError("connection refused"))

    outcome = await _run(gateway)

    assert outcome.status == "failed"
    assert outcome.findings == []
    assert len(gateway.requests) == 1


# ── no harness, no MCP, no files ──────────────────────────────────────────────


async def test_no_subprocess_is_spawned_and_no_file_is_written(
    credential: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    del credential
    run_tmp = tmp_path / "run-tmp"
    cwd = tmp_path / "cwd"
    run_tmp.mkdir()
    cwd.mkdir()
    spawned: list[str] = []

    def _no_spawn(*args: Any, **_kwargs: Any) -> Any:
        spawned.append(repr(args[:1]))
        msg = "lite must not spawn a process"
        raise AssertionError(msg)

    async def _no_async_spawn(*args: Any, **kwargs: Any) -> Any:
        return _no_spawn(*args, **kwargs)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _no_async_spawn)
    monkeypatch.setattr(asyncio, "create_subprocess_shell", _no_async_spawn)
    monkeypatch.setattr(subprocess, "Popen", _no_spawn)
    monkeypatch.setattr(tempfile, "tempdir", str(run_tmp))
    monkeypatch.setenv("TMPDIR", str(run_tmp))
    monkeypatch.setenv("RUNNER_TEMP", str(run_tmp))
    monkeypatch.chdir(cwd)

    outcome = await _run(_Gateway())

    assert outcome.status == "reviewed"
    assert spawned == []
    assert sorted(p.name for p in run_tmp.rglob("*")) == []
    assert sorted(p.name for p in cwd.rglob("*")) == []


def test_the_outcome_type_carries_the_contract_fields() -> None:
    api = _lite_api()

    outcome = api.LiteOutcome(
        status="downgraded",
        reason="diff exceeds the lite token cap (estimated 30000 > cap 20000)",
        tokens_used=None,
        usage_estimated=False,
        cap_hit=False,
        findings=[],
        summary=None,
        prompt_version=api.LITE_PROMPT_VERSION,
    )

    assert outcome.status == "downgraded"
    assert outcome.prompt_version == api.LITE_PROMPT_VERSION
    assert outcome.tokens_used is None
