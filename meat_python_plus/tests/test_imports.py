"""W2 contract: full import auto-removal (Go imports.go)."""

from __future__ import annotations

import pytest

from meat_python_plus.editplan import EditPlan, compile_edit_plan
from _parity_helpers import import_or_fail, require_attr

_MANDATORY_BY_LANGUAGE = [
    pytest.param(
        "Go import block",
        (
            "diff --git a/a.go b/a.go\n--- a/a.go\n+++ b/a.go\n@@\n"
            "+package a\n+\n+import (\n+\t\"fmt\"\n+\talias \"example.com/a\"\n+)\n+\n"
            "+func run() { fmt.Println(alias.Value) }\n"
        ),
        ["+package a", "+func run()"],
        ["import (", '"fmt"', '"example.com/a"', "+)"],
        id="go-import-block",
    ),
    pytest.param(
        "Python import and multiline from import",
        (
            "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@\n"
            "+from package.tools import (\n+ first,\n+ second as renamed,\n+)\n"
            "+import os, sys\n+\n+value = first(renamed, os.name, sys.version)\n"
        ),
        ["+value = first"],
        ["from package.tools import", "second as renamed", "import os, sys"],
        id="python-multiline-import",
    ),
    pytest.param(
        "JavaScript static import and multiline require",
        (
            "diff --git a/a.ts b/a.ts\n--- a/a.ts\n+++ b/a.ts\n@@\n"
            "+import {\n+ first,\n+ second,\n+} from \"./tools\";\n"
            "+const {\n+ third,\n+} = require(\"./more\");\n+\n"
            "+export const value = first(second, third);\n"
        ),
        ["+export const value"],
        ['import {', 'from "./tools"', "const {", 'require("./more")'],
        id="javascript-import-require",
    ),
    pytest.param(
        "Rust use declarations",
        (
            "diff --git a/a.rs b/a.rs\n--- a/a.rs\n+++ b/a.rs\n@@\n"
            "+use crate::{\n+ first,\n+ second,\n+};\n"
            "+pub(crate) use other::Third;\n+\n+fn run() { first(second(), Third); }\n"
        ),
        ["+fn run()"],
        ["use crate", "pub(crate) use", "+};"],
        id="rust-use",
    ),
]


@pytest.mark.parametrize(("name", "diff", "want", "unwanted"), _MANDATORY_BY_LANGUAGE)
def test_mandatory_imports_by_language(
    name: str, diff: str, want: list[str], unwanted: list[str]
) -> None:
    _ = name
    imports = import_or_fail("meat_python_plus.imports")
    mandatory_plan = require_attr(imports, "mandatory_import_removal_plan")
    lines_mod = import_or_fail("meat_python_plus.diffutil")
    split_source_lines = require_attr(lines_mod, "split_source_lines")
    analyze_diff = require_attr(lines_mod, "analyze_diff")

    lines = split_source_lines(diff)
    layout = analyze_diff(lines)
    first = mandatory_plan(lines, layout)
    second = mandatory_plan(lines, layout)
    assert first and first == second

    compiled = compile_edit_plan(diff, EditPlan())
    for snippet in want:
        assert snippet in compiled.smart_diff
    for snippet in unwanted:
        assert snippet not in compiled.smart_diff


def test_mandatory_imports_cover_both_diff_sides() -> None:
    raw = (
        "diff --git a/token.go b/token.go\n--- a/token.go\n+++ b/token.go\n@@\n"
        " package token\n import (\n \t\"fmt\"\n-\t\"math/rand\"\n+\t\"crypto/rand\"\n"
        "+\t\"encoding/hex\"\n )\n-old := fmt.Sprintf(\"%x\", value)\n"
        "+new := hex.EncodeToString(value)\n"
    )
    compiled = compile_edit_plan(raw, EditPlan())
    for unwanted in (
        "import (",
        '"fmt"',
        '"math/rand"',
        '"crypto/rand"',
        '"encoding/hex"',
        " )",
    ):
        assert unwanted not in compiled.smart_diff
    for want in ("-old := fmt.Sprintf", "+new := hex.EncodeToString"):
        assert want in compiled.smart_diff


def test_mandatory_embedded_source_imports() -> None:
    raw = (
        "diff --git a/test_plugin.py b/test_plugin.py\n--- a/test_plugin.py\n"
        "+++ b/test_plugin.py\n@@\n+def test_plugin(pytester):\n+ pytester.makeconftest(\n"
        "+\t\"\"\"\n+ from plugin import (\n+ hook,\n+ option,\n+ )\n"
        "+ import warnings\n+ import pytest\n+\n+ @pytest.hookimpl(tryfirst=True)\n"
        "+ def pytest_configure():\n+ warnings.warn(option, UserWarning)\n+ \"\"\"\n+ )\n"
        "+ result = pytester.runpytest()\n+ assert result.ret == 0\n"
    )
    compiled = compile_edit_plan(raw, EditPlan())
    for unwanted in (
        "from plugin import",
        "+ hook,",
        "+ option,",
        "import warnings",
        "import pytest",
    ):
        assert unwanted not in compiled.smart_diff
    for want in (
        "+ @pytest.hookimpl",
        "+ def pytest_configure",
        "+ warnings.warn",
        "+ result = pytester.runpytest",
    ):
        assert want in compiled.smart_diff


def test_mandatory_imports_avoid_false_positives() -> None:
    diff = (
        "diff --git a/a.js b/a.js\n--- a/a.js\n+++ b/a.js\n@@\n"
        "+require.NoError(t, err);\n+useFeature();\n+using(resource);\n"
        "+const middleware = wrap(require(\"morgan\"));\n+app.use(middleware);\n"
        "+const {\n+ value,\n+} = source;\n+consume(value);\n"
        "+const note = \"we import data from upstream\";\n"
    )
    compiled = compile_edit_plan(diff, EditPlan())
    for want in (
        "require.NoError",
        "useFeature",
        "using(resource)",
        "wrap(require",
        "app.use",
        "} = source",
        "consume(value)",
        "we import data from upstream",
    ):
        assert want in compiled.smart_diff


def test_mandatory_imports_remove_import_only_file() -> None:
    raw = (
        "diff --git a/a.py b/a.py\nindex 111..222 100644\n--- a/a.py\n+++ b/a.py\n@@\n"
        "-import old_package\n+import new_package\n"
    )
    compiled = compile_edit_plan(raw, EditPlan())
    assert compiled.smart_diff == ""


def test_fold_cannot_cross_mandatory_import_rows() -> None:
    raw = (
        "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@\n"
        "+from package import (\n+ first,\n+ second,\n+)\n+value = first(second)\n"
    )
    from meat_python_plus.editplan import LineFold

    with pytest.raises(ValueError, match="crosses automatically removed import rows"):
        compile_edit_plan(
            raw,
            EditPlan(fold=[LineFold(start_line=8, end_line=9)]),
        )
