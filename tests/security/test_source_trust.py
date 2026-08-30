"""TS1 — CLI-supplied review source trust tier (`.ignorelocal/02-cli-sources-trust-wave-plan.md`).

Pins D2 (provenance-derived tier), D3 (explicit ``--trust`` override), convention 4
(fail closed on unknown provenance), and the wiring seams into ``decide_approval``,
analyzer trust gates, and ``MERGECRAFT_TRUST_TIER`` on the offline CLI path.

Authoring wave: **TS1.1** (RED). Implementation: **TS1.2**.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from mergecraft.agents.gates import decide_approval
from mergecraft.analyzers.finding import Finding
from mergecraft.analyzers.trust import derive_trust_tier, evaluate_manifest_for_tier
from mergecraft.config.settings import load_repo_settings
from tests.analyzers.support import SAME_REPO_PULL_REQUEST_EVENT, import_module


def _trust_mod() -> Any:
    return import_module("mergecraft.analyzers.trust")


def _offline_mod() -> Any:
    return import_module("mergecraft.offline_review")


def _derive_source_trust_tier() -> Any:
    name = "derive_source_trust_tier"
    fn = getattr(_trust_mod(), name, None)
    if fn is None:
        pytest.fail(f"{name} not defined in mergecraft.analyzers.trust")
    return fn


def _review_source(
    *,
    kind: str,
    path: Path,
    invocation_root: Path,
) -> Any:
    cls_name = "ReviewSource"
    review_source_cls = getattr(_trust_mod(), cls_name, None)
    if review_source_cls is None:
        pytest.fail(f"{cls_name} not defined in mergecraft.analyzers.trust")
    return review_source_cls(kind=kind, path=path, invocation_root=invocation_root)


def test_local_cwd_checkout_is_trusted(tmp_path: Path) -> None:
    """D2 — the operator's own checkout (cwd == invocation root) is trusted."""
    derive = _derive_source_trust_tier()
    root = tmp_path / "checkout"
    root.mkdir()
    source = _review_source(kind="local_cwd", path=root, invocation_root=root)
    assert derive(source) == "trusted"


def test_path_outside_invocation_root_is_untrusted(tmp_path: Path) -> None:
    """D2 — a review path outside the invocation root is untrusted."""
    derive = _derive_source_trust_tier()
    invocation_root = tmp_path / "operator"
    invocation_root.mkdir()
    outside = tmp_path / "foreign-checkout"
    outside.mkdir()
    source = _review_source(kind="local_path", path=outside, invocation_root=invocation_root)
    assert derive(source) == "untrusted"


def test_cloned_remote_is_untrusted(tmp_path: Path) -> None:
    """D2 — a tree acquired from a remote clone is untrusted regardless of path."""
    derive = _derive_source_trust_tier()
    root = tmp_path / "operator"
    root.mkdir()
    clone_dir = root / "cloned-repo"
    clone_dir.mkdir()
    source = _review_source(kind="cloned_remote", path=clone_dir, invocation_root=root)
    assert derive(source) == "untrusted"


def test_unknown_source_shape_is_untrusted() -> None:
    """Convention 4 — an unrecognised source shape fails closed to untrusted."""
    derive = _derive_source_trust_tier()
    assert derive(None) == "untrusted"
    assert derive({"kind": "mystery"}) == "untrusted"
    assert derive(object()) == "untrusted"


def test_explicit_override_is_honoured_and_logged(tmp_path: Path) -> None:
    """D3 — ``--trust trusted`` is honoured and logged at warning."""
    from loguru import logger

    derive = _derive_source_trust_tier()
    root = tmp_path / "foreign"
    root.mkdir()
    outside = tmp_path / "other"
    outside.mkdir()
    source = _review_source(kind="local_path", path=outside, invocation_root=root)

    records: list[str] = []
    sink_id = logger.add(lambda message: records.append(str(message)), level="WARNING")
    try:
        tier = derive(source, trust_override="trusted")
    finally:
        logger.remove(sink_id)

    assert tier == "trusted"
    assert any("trust" in record.lower() for record in records)


def test_override_cannot_be_set_from_repo_config(tmp_path: Path) -> None:
    """D3 — a cloned repo cannot declare itself trusted via config YAML."""
    derive = _derive_source_trust_tier()
    repo = tmp_path / "hostile"
    repo.mkdir()
    config_dir = repo / ".mergecraft"
    config_dir.mkdir()
    (config_dir / "config.yaml").write_text("trust: trusted\n", encoding="utf-8")

    with pytest.raises(ValidationError):
        load_repo_settings(root=repo)

    from mergecraft.config.settings import RepoSettings

    assert "trust" in RepoSettings.model_fields

    source = _review_source(kind="cloned_remote", path=repo, invocation_root=tmp_path)
    assert derive(source) == "untrusted"


def test_tier_reaches_decide_approval(tmp_path: Path) -> None:
    """An untrusted CLI review can never return ``success`` from ``decide_approval``."""
    resolve_name = "resolve_offline_review_trust_tier"
    resolve = getattr(_offline_mod(), resolve_name, None)
    if resolve is None:
        pytest.fail(f"{resolve_name} not defined in mergecraft.offline_review")

    outside = tmp_path / "outside"
    outside.mkdir()
    tier = resolve(
        cwd=outside,
        invocation_root=tmp_path / "operator",
        trust_override=None,
        cloned=False,
    )
    assert tier == "untrusted"

    minor_finding = Finding.model_validate(
        {
            "tool": "ts1-fixture",
            "rule_id": "TS1-MINOR",
            "category": "Maintainability & Code Quality",
            "severity": "Minor",
            "confidence": "certain",
            "message": "nit",
            "path": "a.py",
            "start_line": 1,
            "end_line": 1,
            "fingerprint": "ts1-minor",
            "evidence": ["line 1"],
            "remediation": None,
            "autofix": None,
            "introduced_by_pr": "true",
            "source": "agent",
            "cluster_id": None,
        }
    )
    conclusion = decide_approval([minor_finding], run_succeeded=True, tier=tier)
    assert conclusion != "success"
    assert conclusion == "neutral"


def test_tier_reaches_analyzer_trust_gate(tmp_path: Path) -> None:
    """Untrusted tier withholds trusted-only analyzer manifests."""
    manifest_mod = import_module("mergecraft.analyzers.manifest")
    raw = Path("tests/analyzers/fixtures/manifests/valid-actionlint.yaml").read_text(
        encoding="utf-8"
    )
    trusted_only = manifest_mod.load_manifest_yaml(
        raw.replace("trust: untrusted", "trust: trusted")
    )

    resolve_name = "resolve_offline_review_trust_tier"
    resolve = getattr(_offline_mod(), resolve_name, None)
    if resolve is None:
        derive = _derive_source_trust_tier()
        outside = tmp_path / "outside"
        outside.mkdir()
        source = _review_source(
            kind="local_path",
            path=outside,
            invocation_root=tmp_path / "operator",
        )
        tier = derive(source)
    else:
        outside = tmp_path / "outside"
        outside.mkdir()
        tier = resolve(
            cwd=outside,
            invocation_root=tmp_path / "operator",
            trust_override=None,
            cloned=False,
        )

    decision = evaluate_manifest_for_tier(manifest=trusted_only, tier=tier)
    assert decision.skipped is True
    assert decision.reason is not None


def test_tier_reaches_the_trace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``MERGECRAFT_TRUST_TIER`` is set on the offline CLI path."""
    fn_name = "apply_cli_trust_tier_env"
    apply_env = getattr(_offline_mod(), fn_name, None)
    if apply_env is None:
        pytest.fail(f"{fn_name} not defined in mergecraft.offline_review")

    monkeypatch.delenv("MERGECRAFT_TRUST_TIER", raising=False)
    previous = apply_env("untrusted")
    try:
        assert os.environ.get("MERGECRAFT_TRUST_TIER") == "untrusted"
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_github_action_path_tier_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression pin — ``derive_trust_tier`` event logic is untouched."""
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    tier = derive_trust_tier(event=SAME_REPO_PULL_REQUEST_EVENT)
    assert tier == "trusted"

    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request_target")
    tier = derive_trust_tier(event={"pull_request": {"head": {"repo": {"fork": False}}}})
    assert tier == "untrusted"
