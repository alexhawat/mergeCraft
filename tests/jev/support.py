"""Shared helpers and pinned symbols for the Jev suite.

Imports of ``mergecraft.jev`` stay inside helpers so collection stays clean
if a submodule is unused. CI makes zero live TypeSafe calls (D14).
"""

from __future__ import annotations

import importlib
import json
import subprocess
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Final

from mergecraft.analyzers.finding import Finding, make_finding
from mergecraft.review_taxonomy import FindingSource

PINNED_MODEL: Final[str] = "jev-1.13.0"
OFFLINE_DEMO_PATCH: Final[str] = (
    "diff --git a/demo.py b/demo.py\n--- a/demo.py\n+++ b/demo.py\n@@ -0,0 +1 @@\n+print(1)\n"
)
PACK_IDS: Final[tuple[str, ...]] = (
    "unit/v1",
    "evidence/v1",
    "claim/v1",
    "align/v1",
    "lens/v1",
)
UNIT_QUESTION_NAMES: Final[tuple[str, ...]] = (
    "triage",
    "severity",
    "security",
    "error_discard",
    "contract_break",
    "untrusted_input",
    "missing_tests",
    "style_nit",
)
EVIDENCE_QUESTION_NAMES: Final[tuple[str, ...]] = ("relation", "falsifiable", "located")
CLAIM_QUESTION_NAMES: Final[tuple[str, ...]] = (
    "backed_by_row",
    "blocking_language",
    "contradicts_verdict",
)
ALIGN_QUESTION_NAMES: Final[tuple[str, ...]] = ("same_defect", "is_withdrawn_reraise")
SKIP_REASONS: Final[frozenset[str]] = frozenset({"disabled", "credential_absent", "kill_switch"})
FORBIDDEN_COUNT_NAMES: Final[frozenset[str]] = frozenset(
    {"count", "how_many", "percentage", "crap", "mutation_score"}
)

JEV_ROOT = Path(__file__).resolve().parent
FIXTURES = JEV_ROOT / "fixtures"
TRANSPORT_DIR = FIXTURES / "transport"
DIFF_DIR = FIXTURES / "diffs"
REVIEW_DIR = FIXTURES / "reviews"
WITHDRAWN_DIR = FIXTURES / "withdrawn"
CORPUS_DIR = JEV_ROOT / "corpus"

TEST_API_KEY: Final[str] = "mc-test-jev-key"


def import_jev(module: str = "") -> Any:
    """Import ``mergecraft.jev`` or a submodule. Fails RED until J2."""
    name = "mergecraft.jev" if not module else f"mergecraft.jev.{module}"
    return importlib.import_module(name)


def load_transport_payload(name: str) -> dict[str, Any]:
    """Load a recorded TypeSafe envelope (http + body, never a live call)."""
    path = TRANSPORT_DIR / name
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        msg = f"transport fixture {name} must be a JSON object"
        raise TypeError(msg)
    return payload


def load_transport_body(name: str) -> dict[str, Any]:
    payload = load_transport_payload(name)
    body = payload.get("body", payload)
    if not isinstance(body, dict):
        msg = f"transport fixture {name} body must be a JSON object"
        raise TypeError(msg)
    return body


def load_diff(name: str) -> str:
    return (DIFF_DIR / name).read_text(encoding="utf-8")


def load_review(name: str) -> str:
    return (REVIEW_DIR / name).read_text(encoding="utf-8")


def load_withdrawn(name: str) -> str:
    return (WITHDRAWN_DIR / name).read_text(encoding="utf-8")


def load_corpus() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(CORPUS_DIR.glob("jev-*.json")):
        row = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(row, dict):
            rows.append(row)
    return rows


def make_agent_finding(
    *,
    message: str,
    path: str = "src/mergecraft/example.py",
    start_line: int = 10,
    severity: str = "Major",
    confidence: str = "likely",
    evidence: list[str] | None = None,
    source: FindingSource = "agent",
) -> Finding:
    """Build a taxonomy-valid finding for judge / align tests."""
    return make_finding(
        tool="reviewer",
        rule_id="jev-test",
        category="Security & Privacy",
        severity=severity,
        confidence=confidence,
        message=message,
        path=path,
        start_line=start_line,
        end_line=start_line,
        source=source,
        evidence=evidence or [],
    )


def shadow_packet(**overrides: Any) -> Any:
    """Minimal evidence packet so Jev can reuse ``record_shadow_prediction``."""
    from mergecraft.evidence.packet import (
        PACKET_SCHEMA_VERSION,
        AgentMetadata,
        MergeEvidencePacket,
    )

    base: dict[str, Any] = {
        "schema_version": PACKET_SCHEMA_VERSION,
        "change_id": "acme/demo#724",
        "agent": AgentMetadata(id="claude", version="0.0.0", model="claude-sonnet-4-5"),
        "files_changed": [],
        "findings": [],
        "deterministic_checks": [],
        "self_assessment": None,
        "decision": None,
        "blast_radius": None,
        "trajectory": None,
        "evals": None,
    }
    base.update(overrides)
    return MergeEvidencePacket(**base)


@contextmanager
def loguru_lines() -> Iterator[list[str]]:
    """Capture loguru INFO+ messages. pytest ``caplog`` does not see loguru."""
    from loguru import logger

    captured: list[str] = []
    sink_id = logger.add(lambda message: captured.append(str(message)), level="INFO")
    try:
        yield captured
    finally:
        logger.remove(sink_id)


def make_hunk_unit(
    *,
    path: str = "src/mergecraft/example.py",
    unit_id: str = "hunk:example",
    start_line: int = 1,
    content: str | None = None,
) -> Any:
    """Build a hunk unit for battery / dispatch tests."""
    types = import_jev("types")
    body = content if content is not None else f"@@ -{start_line} +{start_line} @@\n+{unit_id}\n"
    return types.HunkUnit(
        kind="hunk",
        path=path,
        content=body,
        context_lines=0,
        unit_id=unit_id,
        start_line=start_line,
        end_line=start_line,
    )


def skipping_jev_client(
    monkeypatch: Any,
    fixture_name: str = "unit_happy.json",
    **settings_kwargs: Any,
) -> tuple[Any, Any]:
    """Enabled client with no credential — ``call`` records ``credential_absent``."""
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    from mergecraft.config.settings import JevSettings

    module = import_jev("client")
    transport = module.RecordedTransport.from_fixture(TRANSPORT_DIR / fixture_name)
    settings = JevSettings(enabled=True, model=PINNED_MODEL, **settings_kwargs)
    client = module.AsyncJevClient(api_key=None, transport=transport, settings=settings)
    return client, transport


def watch_async_jev_client(monkeypatch: Any) -> list[Any]:
    """Record every ``AsyncJevClient`` construction across import sites."""
    seen: list[Any] = []
    client_mod = import_jev("client")
    original = client_mod.AsyncJevClient

    class WatchedAsyncJevClient(original):  # type: ignore[misc,valid-type]
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            seen.append(self)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(client_mod, "AsyncJevClient", WatchedAsyncJevClient)
    package = import_jev()
    monkeypatch.setattr(package, "AsyncJevClient", WatchedAsyncJevClient)
    import mergecraft.offline_review as offline_mod

    if getattr(offline_mod, "AsyncJevClient", None) is not None:
        monkeypatch.setattr(offline_mod, "AsyncJevClient", WatchedAsyncJevClient)
    return seen


class StateRecordingTransport:
    """Replay a recorded envelope while capturing each ``system_one`` state."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.states: list[dict[str, Any]] = []

    async def system_one(
        self,
        *,
        state: dict[str, Any],
        questions: dict[str, Any],
        model: str,
    ) -> Any:
        self.states.append(dict(state))
        return await self._inner.system_one(state=state, questions=questions, model=model)

    @property
    def calls(self) -> int:
        return int(self._inner.calls)

    @property
    def last_model(self) -> str | None:
        return self._inner.last_model


def inject_recorded_jev_client(monkeypatch: Any, fixture_name: str) -> StateRecordingTransport:
    """Force review-path ``AsyncJevClient`` construction onto a recorded transport (D14)."""
    client_mod = import_jev("client")
    original = client_mod.AsyncJevClient
    inner = client_mod.RecordedTransport.from_fixture(TRANSPORT_DIR / fixture_name)
    transport = StateRecordingTransport(inner)

    class InjectedAsyncJevClient(original):  # type: ignore[misc,valid-type]
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(client_mod, "AsyncJevClient", InjectedAsyncJevClient)
    package = import_jev()
    monkeypatch.setattr(package, "AsyncJevClient", InjectedAsyncJevClient)
    import mergecraft.offline_review as offline_mod

    monkeypatch.setattr(offline_mod, "AsyncJevClient", InjectedAsyncJevClient)
    return transport


def write_offline_jev_repo(
    tmp_path: Path,
    *,
    config_yaml: str,
    patch: str = OFFLINE_DEMO_PATCH,
) -> tuple[Path, Path]:
    """Create a tmp git repo with ``.mergecraft/config.yaml`` and a patch file."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    config_dir = repo / ".mergecraft"
    config_dir.mkdir()
    (config_dir / "config.yaml").write_text(config_yaml, encoding="utf-8")
    diff = tmp_path / "change.diff"
    diff.write_text(patch, encoding="utf-8")
    return repo, diff


def published_review_engine(published: Any) -> Any:
    """Materialize the diff, then return a canned successful review (no live agent)."""
    from mergecraft.review.engine import ReviewEngine

    class PublishedReviewEngine(ReviewEngine):  # type: ignore[type-arg]
        async def run(self, driver: Any, /, **kwargs: Any) -> Any:
            del kwargs
            self._ran.clear()
            await driver.materialize()
            return self.result(published)

    return PublishedReviewEngine()


def assert_honest_skip(
    result: object,
    logs: Sequence[str],
    *,
    reason: str = "credential_absent",
) -> None:
    """Pin an observable skip — result field or log line, never a silent assessment."""
    skipped = getattr(result, "skipped", False) is True
    result_reason = getattr(result, "reason", None)
    jev_skip = getattr(result, "jev_skip_reason", None) or getattr(result, "jev_reason", None)
    logged = any(reason in line for line in logs)
    if getattr(result, "choice", None) and not skipped and result_reason != reason:
        msg = "D4: a client skip must not become a unit assessment"
        raise AssertionError(msg)
    assert skipped or result_reason == reason or jev_skip == reason or result is None or logged
    assert reason in (result_reason, jev_skip) or logged or skipped
