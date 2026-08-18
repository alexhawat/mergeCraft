"""DG3 context provenance — reproducible citations and inspect cost (G8 / convention 4).

Wave plan: ``.ignorelocal/waves/05-review-depth-governance-wave-plan.md`` (PR DG3).
Implementation: **DG3.2** — ``mergecraft.context.provenance``.
"""

from __future__ import annotations

import pytest

from tests.context.support import import_context_module


@pytest.mark.xfail(reason="green after DG3.2: context item provenance fields", strict=False)
def test_every_context_item_records_repo_sha_path_and_reason() -> None:
    """Convention 4 — every retrieved context item carries repo, SHA, path, and reason."""
    provenance_mod = import_context_module("provenance")
    item = provenance_mod.ContextItem(
        repo="acme/demo",
        sha="deadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
        path="src/demo/module.py",
        reason="symbol_index",
        text="def cached_symbol() -> None:\n    return None\n",
        token_cost=12,
    )

    assert item.repo == "acme/demo"
    assert item.sha == "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
    assert item.path == "src/demo/module.py"
    assert item.reason == "symbol_index"
    assert item.as_citation() == (
        "acme/demo@deadbeefdeadbeefdeadbeefdeadbeefdeadbeef:src/demo/module.py"
    )


@pytest.mark.xfail(reason="green after DG3.2: context inspect token accounting", strict=False)
def test_context_inspect_reports_token_cost_per_item() -> None:
    """Context inspect reports per-item token cost for budget visibility."""
    provenance_mod = import_context_module("provenance")
    items = [
        provenance_mod.ContextItem(
            repo="acme/demo",
            sha="abc123",
            path="src/a.py",
            reason="repo_map",
            text="package demo",
            token_cost=7,
        ),
        provenance_mod.ContextItem(
            repo="acme/demo",
            sha="abc123",
            path="src/b.py",
            reason="symbol_index",
            text="def b(): pass",
            token_cost=11,
        ),
    ]

    report = provenance_mod.inspect_context(items)

    assert report.total_tokens == 18
    assert [entry.token_cost for entry in report.items] == [7, 11]
    assert [entry.path for entry in report.items] == ["src/a.py", "src/b.py"]
