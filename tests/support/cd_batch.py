"""Shared helpers for sweep 20c Batch CD RED pins (#361-#367)."""

from __future__ import annotations

import importlib.util
from typing import Any

import pytest

from tests.support.cc_batch import load_module, require_callable
from tests.support.dead_package_wiring import root_callback_source

WEBHOOK_MODULE = "mergecraft.scm.webhooks"
EGRESS_MODULE = "mergecraft.security.egress"
PUBLIC_COMMENT_MODULE = "mergecraft.security.public_comments"
ADVERSARIAL_CORPORA_MODULE = "mergecraft.evals.adversarial_corpora"
RECOVERY_MODULE = "mergecraft.reliability.recovery"
BUNDLE_MODULE = "mergecraft.reliability.diagnostic_bundle"

SUPPORTED_WEBHOOK_PROVIDERS = frozenset({"github", "gitlab"})
ADVERSARIAL_CORPUS_KINDS = frozenset(
    {
        "prompt_injection",
        "malicious_repository",
        "malicious_ticket_comment",
    }
)
ISSUE_140_GATE_METRICS = frozenset(
    {
        "decision_replay_pass_rate",
        "unsafe_approval_rate",
        "clean_block_rate",
        "recall",
        "corpus_confirmed_precision",
        "f1",
    }
)
CLEANUP_FAILURE_MODES = frozenset(
    {
        "timeout",
        "cancellation",
        "provider_crash",
        "analyzer_crash",
        "parent_process_termination",
    }
)


def module_exists(module_name: str) -> bool:
    try:
        return importlib.util.find_spec(module_name) is not None
    except ModuleNotFoundError:
        return False


def require_module(module_name: str) -> Any:
    if not module_exists(module_name):
        pytest.fail(f"expected module {module_name}")
    return load_module(module_name)


def d10_root_callback_owns_globals() -> str:
    """Return the ``_root`` body; D10 forbids folding new flags into it."""
    source = root_callback_source()
    assert "def _root(" in source
    assert '"--format"' in source
    assert '"--quiet"' in source
    assert '"--color"' in source
    return source.split("def _root(", 1)[1].split("\n@app.", 1)[0]


__all__ = [
    "ADVERSARIAL_CORPORA_MODULE",
    "ADVERSARIAL_CORPUS_KINDS",
    "BUNDLE_MODULE",
    "CLEANUP_FAILURE_MODES",
    "EGRESS_MODULE",
    "ISSUE_140_GATE_METRICS",
    "PUBLIC_COMMENT_MODULE",
    "RECOVERY_MODULE",
    "SUPPORTED_WEBHOOK_PROVIDERS",
    "WEBHOOK_MODULE",
    "d10_root_callback_owns_globals",
    "module_exists",
    "require_callable",
    "require_module",
]
