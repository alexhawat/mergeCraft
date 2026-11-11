"""``.test_durations`` stays committable and its coverage check is correct (#1364).

The full collection-based coverage check (at least 95% of unit-lane ids have a
timing) takes about 35 s, so it runs once in the static tier via
``make test-durations-check`` (part of ``make ci-static``) rather than here, where
every test shard would repeat it. These tests are cheap and stay in the unit lane.
"""

from __future__ import annotations

import importlib.util
import json
from typing import Any

from tests.ci.workflow_support import REPO_ROOT


def _script() -> Any:
    path = REPO_ROOT / "scripts" / "check_test_durations.py"
    spec = importlib.util.spec_from_file_location("check_test_durations", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_committed_durations_embed_no_security_scanner_suppression_marker() -> None:
    ids = sorted(json.loads((REPO_ROOT / ".test_durations").read_text(encoding="utf-8")))
    assert _script().unsafe_ids(ids) == []


def test_unsafe_ids_flags_scanner_markers() -> None:
    marker = "# " + "gitleaks" + ":allow"
    other = "# " + "trufflehog" + ":ignore"
    flagged = _script().unsafe_ids(
        [f"tests/a.py::test_x[x = 1  {marker}]", f"tests/a.py::t[{other}]", "tests/a.py::ok"]
    )
    assert len(flagged) == 2


def test_coverage_is_the_fraction_of_ids_with_a_duration() -> None:
    script = _script()
    assert script.coverage({"a", "b", "c", "d"}, {"a", "b", "c", "x"}) == 0.75
    assert script.coverage(set(), {"a"}) == 0.0
