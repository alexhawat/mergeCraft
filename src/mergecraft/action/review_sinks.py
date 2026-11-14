"""Scan Action review artifacts for leaked credentials."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from mergecraft.security.review_integrity import scan_local_sinks_for_secrets

if TYPE_CHECKING:
    from collections.abc import Sequence

    from mergecraft.action.review_state import RunContext


_SINK_SCAN_ARTIFACT_SOURCES: tuple[str, ...] = (
    "packet-opencode-go.json",
    "packet-nous.json",
    "packet-codex.json",
    "packet-claude.json",
    "mergecraft/run-packet.json",
    "shadow-compare.jsonl",
)
"""Artifact sources the evidence/trace uploads are assembled from (SX-D10).

Every one lives under ``RUNNER_TEMP`` — the GitHub-provided per-job scratch
directory the workflow's ``actions/upload-artifact`` steps read. ``.json`` is
deliberately *not* a sink suffix, so the packet files are named explicitly and
scanned by path; the globs pick up the packet's real slug-prefixed spelling
and the shadow-compare JSONL wherever it lands beneath the runner temp dir.
"""


def _runner_temp_artifact_sources() -> list[Path]:
    """Resolve the in-scope artifact sources under ``RUNNER_TEMP``."""
    runner_temp = os.environ.get("RUNNER_TEMP", "").strip()
    if not runner_temp:
        return []
    base = Path(runner_temp)
    sources = [base / rel for rel in _SINK_SCAN_ARTIFACT_SOURCES]
    sources.extend(sorted(base.glob("packet-*.json")))
    # The emitted packet is ``<change-slug>-merge-evidence-packet.json`` in the
    # run-packet dir; the literal/glob spellings above predate it, so match the
    # real basename too — a packet that exists before the scan must not be
    # missed (a publication-time packet is caught by the post-emission scan).
    sources.extend(sorted((base / "mergecraft").glob("*-merge-evidence-packet.json")))
    sources.extend(sorted((base / "mergecraft").glob("*run-packet.json")))
    sources.extend(sorted((base / "mergecraft").glob("*-fix-brief.json")))
    sources.extend(sorted((base / "mergecraft").glob("*.jsonl")))
    return list(dict.fromkeys(sources))


def _run_sink_scan_secret_values(ctx: RunContext) -> list[str]:
    """Return the credential *values* the run holds, for the post-run sink scan.

    Covers every provider credential env name the registry can consume (D2's
    single authority, so a new provider cannot be missed) plus the SCM tokens
    and API/DB secrets carried on the run context. Values only — the scan
    compares them and never records them.
    """
    from mergecraft.config.runtime_provider_registry import provider_credential_env_names

    values: list[str] = []

    def _add(value: str | None) -> None:
        if isinstance(value, str) and value.strip():
            values.append(value.strip())

    for name in provider_credential_env_names(ctx.settings):
        _add(os.environ.get(name))
    token_ref = ctx.token_ref
    if token_ref is not None:
        _add(token_ref.git_token)
        _add(token_ref.mcp_token)
        _add(token_ref.read_token)
    _add(ctx.job_token)
    run_context = ctx.run_context
    if run_context is not None:
        _add(run_context.api_token)
        for secret in (run_context.db_secrets or {}).values():
            _add(secret)
    return list(dict.fromkeys(values))


def _scan_sinks_after_run(ctx: RunContext, *, extra_paths: Sequence[Path] = ()) -> str | None:
    """Scan the run tmpdir and the artifact sources, delete hits, return the reason.

    SX-D10: a credential that reached a local sink has already left the agent's
    process, so the honest response is to stop the run, name the sink path —
    **never** its contents — and delete the sink before the workflow's
    artifact-upload step reads it. ``extra_paths`` carries artifacts the run
    generates *after* the pre-publication scan (the emitted packet/run packet),
    so the same guarantee covers everything the run emits, not only what
    existed beforehand.

    Returns the failure reason (naming the paths and the rotate instruction) or
    ``None`` when nothing matched. The matched contents are never returned or
    logged.
    """
    secrets = _run_sink_scan_secret_values(ctx)
    if not secrets:
        return None
    hits = scan_local_sinks_for_secrets(
        Path(ctx.tmpdir) if ctx.tmpdir else None,
        secrets=secrets,
        explicit_paths=[*_runner_temp_artifact_sources(), *extra_paths],
    )
    if not hits:
        return None
    for path in hits:
        try:
            path.unlink()
        except OSError as exc:
            logger.warning("» could not remove exposed local sink {}: {}", path, exc)
        else:
            logger.warning("» removed local sink holding credential material: {}", path)
    return (
        "credential material found in local sink(s) after the run: "
        + ", ".join(str(path) for path in hits)
        + " — rotate the exposed credential(s)"
    )
