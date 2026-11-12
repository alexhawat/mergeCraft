"""Coverage and mutation ingest name the skip when changed code has no resolver (#1323).

Changed-function attribution is Python-only. A JS/TS (Stryker, lcov) report
for a non-Python diff must say so with a named skip reason, not return an
empty, reason-less result.
"""

from __future__ import annotations

import json

from mergecraft.ci.changed_functions import SKIP_CHANGED_LANGUAGE_UNSUPPORTED
from mergecraft.ci.coverage import coverage_findings, parse_coverage_artifact
from mergecraft.ci.mutation import (
    SKIP_MUTATION_SYMBOLS_UNRESOLVED,
    mutation_findings,
    parse_mutation_artifact,
)

_JS_SOURCE = "function add(a, b) {\n  return a + b;\n}\n"
_JS_DIFF = (
    "diff --git a/src/math.js b/src/math.js\n"
    "--- a/src/math.js\n"
    "+++ b/src/math.js\n"
    "@@ -1,3 +1,3 @@\n"
    " function add(a, b) {\n"
    "-  return a - b;\n"
    "+  return a + b;\n"
    " }\n"
)
_PY_SOURCE = "X = 1\nY = 2\n"
_PY_MODULE_DIFF = (
    "diff --git a/src/consts.py b/src/consts.py\n"
    "--- a/src/consts.py\n"
    "+++ b/src/consts.py\n"
    "@@ -1,2 +1,2 @@\n"
    " X = 1\n"
    "-Y = 3\n"
    "+Y = 2\n"
)
_STRYKER = json.dumps(
    {
        "schemaVersion": "2.0",
        "files": {
            "src/math.js": {
                "language": "javascript",
                "source": _JS_SOURCE,
                "mutants": [
                    {
                        "id": "0",
                        "mutatorName": "ArithmeticOperator",
                        "replacement": "a - b",
                        "status": "Survived",
                        "function": "add",
                        "location": {
                            "start": {"line": 2, "column": 10},
                            "end": {"line": 2, "column": 15},
                        },
                    }
                ],
            }
        },
    }
)
_LCOV = "SF:src/math.js\nFN:1,add\nFNDA:0,add\nDA:1,0\nDA:2,0\nDA:3,0\nend_of_record\n"


def test_stryker_report_for_a_js_diff_names_the_language_skip() -> None:
    parsed = parse_mutation_artifact(_STRYKER, "mutation.json")
    assert parsed.survivors, "precondition: the Stryker survivor parses"
    result = mutation_findings(
        parsed, [], mode="enforce", diff=_JS_DIFF, source_tree={"src/math.js": _JS_SOURCE}
    )
    assert result.findings == []
    assert result.skip_reason == SKIP_CHANGED_LANGUAGE_UNSUPPORTED


def test_lcov_report_for_a_js_diff_names_the_language_skip() -> None:
    parsed = parse_coverage_artifact(_LCOV, "lcov.info")
    assert parsed.skip_reason is None, "precondition: the lcov report parses"
    result = coverage_findings(
        parsed, diff=_JS_DIFF, source_tree={"src/math.js": _JS_SOURCE}, mode="enforce"
    )
    assert result.findings == []
    assert result.skip_reason == SKIP_CHANGED_LANGUAGE_UNSUPPORTED


def test_mutation_python_diff_outside_any_function_names_the_unresolved_skip() -> None:
    parsed = parse_mutation_artifact(_STRYKER, "mutation.json")
    result = mutation_findings(
        parsed,
        [],
        mode="enforce",
        diff=_PY_MODULE_DIFF,
        source_tree={"src/consts.py": _PY_SOURCE},
    )
    assert result.findings == []
    assert result.skip_reason == SKIP_MUTATION_SYMBOLS_UNRESOLVED
