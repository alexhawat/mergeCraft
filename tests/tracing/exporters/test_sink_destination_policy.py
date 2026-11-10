"""Remote trace sink credentials and destinations taken from repository config.

``tokenRef`` resolves only tracing token names. On a non-trusted run, repository
``endpoint`` / ``tokenRef`` are ignored (operator-supplied endpoints are kept);
on a trusted run whose run-start tree is a PR head they are kept only when the PR
base declares the same values. Sinks are built through the production
:func:`sink_factory` and the untrusted-tier settings scrub.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from tests.enterprise.base_config_repo import make_pr_checkout, pull_request_event, write_event

from mergecraft.config.settings import (
    RepoSettings,
    TracingSettings,
    apply_trust_tier_to_repo_settings,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_REPO_ENDPOINT = "https://collector.example.invalid/v1/traces"
_OPERATOR_ENDPOINT = "https://operator-collector.example.invalid/v1/traces"


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    pytest.importorskip("opentelemetry")
    from mergecraft.enterprise.runtime import reset_enterprise_runtime
    from mergecraft.tracing.exporters import _reset_test_seam

    for key in (
        "MERGECRAFT_OTEL_ENDPOINT",
        "INPUT_OTEL_ENDPOINT",
        "MERGECRAFT_LOGFIRE_TOKEN",
        "LOGFIRE_TOKEN",
        "GITHUB_EVENT_PATH",
    ):
        monkeypatch.delenv(key, raising=False)
    reset_enterprise_runtime()
    _reset_test_seam()
    yield
    reset_enterprise_runtime()
    _reset_test_seam()


def _remote_children(tracing: TracingSettings) -> list[Any]:
    from mergecraft.tracing.exporters import OTLPSink
    from mergecraft.tracing.sinks import sink_factory

    sink = sink_factory(tracing)
    inner = getattr(sink, "inner", None)
    children = getattr(inner, "sinks", []) if inner is not None else []
    return [child for child in children if isinstance(child, OTLPSink)]


def _tracing(*entries: dict[str, Any]) -> TracingSettings:
    return TracingSettings.model_validate({"enabled": True, "sinks": list(entries)})


# --- tokenRef allow-list (every tier) ---------------------------------------


def test_token_ref_outside_tracing_names_builds_no_remote_sink(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("logfire")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "placeholder-value")
    monkeypatch.setenv("MERGECRAFT_LOGFIRE_TOKEN", "placeholder")

    children = _remote_children(_tracing({"type": "logfire", "tokenRef": "ANTHROPIC_API_KEY"}))

    assert children == []


def test_token_ref_resolver_refuses_non_tracing_names(monkeypatch: pytest.MonkeyPatch) -> None:
    from mergecraft.tracing.exporters import resolve_token_ref

    monkeypatch.setenv("GH_TOKEN", "placeholder-value")
    assert resolve_token_ref("GH_TOKEN") is None


@pytest.mark.parametrize(
    "name", ["MERGECRAFT_LOGFIRE_TOKEN", "LOGFIRE_TOKEN", "MERGECRAFT_TRACING_TOKEN_EU"]
)
def test_tracing_token_names_resolve(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    pytest.importorskip("logfire")
    from mergecraft.tracing.exporters import last_otel_headers

    monkeypatch.setenv(name, "placeholder")

    children = _remote_children(_tracing({"type": "logfire", "tokenRef": name}))

    assert len(children) == 1
    assert "authorization" in last_otel_headers()


def test_bare_token_family_prefix_is_not_a_name() -> None:
    from mergecraft.tracing.sink_trust import token_ref_allowed

    assert token_ref_allowed("MERGECRAFT_TRACING_TOKEN_") is False


# --- untrusted-tier settings scrub --------------------------------------------


def _repo_settings_with_remote_sinks() -> RepoSettings:
    return RepoSettings.model_validate(
        {
            "tracing": {
                "enabled": True,
                "sinks": [
                    {
                        "type": "logfire",
                        "tokenRef": "LOGFIRE_TOKEN",
                        "endpoint": _REPO_ENDPOINT,
                    },
                    {"type": "otel", "endpoint": _REPO_ENDPOINT, "region": "eu"},
                    {"type": "jsonl_file", "path": ".mergecraft/traces/"},
                ],
            }
        }
    )


def test_untrusted_scrub_drops_repo_endpoint_and_token_ref() -> None:
    scrubbed, _drops = apply_trust_tier_to_repo_settings(
        _repo_settings_with_remote_sinks(), "untrusted", source_label="test"
    )

    logfire, otel, local = scrubbed.tracing.sinks
    assert logfire.token_ref is None
    assert logfire.endpoint is None
    assert otel.endpoint is None
    assert "region" not in otel.model_fields_set
    assert local.path == ".mergecraft/traces/"


def test_trusted_scrub_keeps_repo_endpoint_and_token_ref() -> None:
    settings = _repo_settings_with_remote_sinks()
    kept, _drops = apply_trust_tier_to_repo_settings(settings, "trusted", source_label="test")

    assert kept.tracing.sinks[0].token_ref == "LOGFIRE_TOKEN"
    assert kept.tracing.sinks[1].endpoint == _REPO_ENDPOINT


def test_untrusted_scrub_keeps_operator_supplied_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MERGECRAFT_OTEL_ENDPOINT", _OPERATOR_ENDPOINT)
    settings = RepoSettings.model_validate(
        {"tracing": {"enabled": True, "sinks": [{"type": "otel", "endpoint": _OPERATOR_ENDPOINT}]}}
    )

    scrubbed, _drops = apply_trust_tier_to_repo_settings(settings, "untrusted", source_label="t")

    assert scrubbed.tracing.sinks[0].endpoint == _OPERATOR_ENDPOINT


# --- sink construction under a bound review context ---------------------------


def test_untrusted_context_ignores_repo_endpoint_at_sink_construction() -> None:
    from mergecraft.tracing.exporters import last_otel_endpoint
    from mergecraft.tracing.review_context import ReviewContext, bind_review_context

    context = ReviewContext(
        source="action", trigger="pull_request", raw_event_trust_floor="untrusted"
    )
    with bind_review_context(context):
        children = _remote_children(_tracing({"type": "otel", "endpoint": _REPO_ENDPOINT}))

    assert len(children) == 1
    assert children[0].endpoint != _REPO_ENDPOINT
    assert last_otel_endpoint() != _REPO_ENDPOINT


def test_untrusted_context_keeps_action_input_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    from mergecraft.tracing.review_context import ReviewContext, bind_review_context

    monkeypatch.setenv("INPUT_OTEL_ENDPOINT", _OPERATOR_ENDPOINT)
    context = ReviewContext(source="action", trigger="pull_request", trust_tier="untrusted")
    with bind_review_context(context):
        children = _remote_children(_tracing({"type": "otel", "endpoint": _OPERATOR_ENDPOINT}))

    assert [child.endpoint for child in children] == [_OPERATOR_ENDPOINT]


def _pr_head_context(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, base_config: str) -> Any:
    from mergecraft.tracing.review_context import ReviewContext

    root = tmp_path / "repo"
    base_sha = make_pr_checkout(root, base_config=base_config, head_config="tracing: {}\n")
    event_path = write_event(tmp_path / "event.json", pull_request_event(base_sha))
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))
    monkeypatch.chdir(root)
    return ReviewContext(source="action", trigger="pull_request", trust_tier="trusted")


def test_trusted_pr_head_keeps_endpoint_the_base_declares(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mergecraft.tracing.review_context import bind_review_context

    base = f"tracing:\n  sinks:\n    - type: otel\n      endpoint: {_REPO_ENDPOINT}\n"
    with bind_review_context(_pr_head_context(tmp_path, monkeypatch, base)):
        children = _remote_children(_tracing({"type": "otel", "endpoint": _REPO_ENDPOINT}))

    assert [child.endpoint for child in children] == [_REPO_ENDPOINT]


def test_trusted_pr_head_ignores_endpoint_the_base_does_not_declare(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mergecraft.tracing.review_context import bind_review_context

    base = f"tracing:\n  sinks:\n    - type: otel\n      endpoint: {_OPERATOR_ENDPOINT}\n"
    with bind_review_context(_pr_head_context(tmp_path, monkeypatch, base)):
        children = _remote_children(_tracing({"type": "otel", "endpoint": _REPO_ENDPOINT}))

    assert len(children) == 1
    assert children[0].endpoint != _REPO_ENDPOINT


def test_trusted_run_without_pr_keeps_repo_endpoint() -> None:
    from mergecraft.tracing.review_context import ReviewContext, bind_review_context

    context = ReviewContext(source="action", trigger="push", trust_tier="trusted")
    with bind_review_context(context):
        children = _remote_children(_tracing({"type": "otel", "endpoint": _REPO_ENDPOINT}))

    assert [child.endpoint for child in children] == [_REPO_ENDPOINT]
