"""W8 — blocking ``make lint`` must not select-and-ignore whole ruff families (#146).

W8 landed: ERA is enforced; 11 noisy families dropped from ``select``;
BLE/PTH/PERF/C901 run only via non-blocking ``make lint-ruff-advisory``.
"""

from __future__ import annotations

import re
import subprocess
import tomllib
from pathlib import Path

import pytest

from tests.ci.workflow_support import REPO_ROOT, load_workflow, read_text

# Families listed as "Advisory-only — not blocking lint" in pyproject.toml
# before W8. Drop from ``select`` is an allowed outcome.
_ADVISORY_FAMILIES = (
    "SLF",
    "BLE",
    "PTH",
    "C4",
    "PERF",
    "FURB",
    "TRY",
    "EM",
    "ARG",
    "N",
    "PL",
    "FBT",
    "ERA",
    "ISC",
    "ICN",
    "C901",
)

_SAMPLES: dict[str, str] = {
    "SLF": "class C:\n    def f(self) -> int:\n        return self._hidden\n",
    "BLE": "def f() -> None:\n    try:\n        int('x')\n    except Exception:\n        pass\n",
    "PTH": "def f() -> None:\n    open('x')\n",
    "C4": "def f(xs: list[int]) -> list[int]:\n    out = []\n    for x in xs:\n        out.append(x + 1)\n    return out\n",
    "PERF": "def f(xs: list[int]) -> bool:\n    return True if xs else False\n",
    "FURB": "def f() -> str:\n    return str('x')\n",
    "TRY": "def f() -> None:\n    try:\n        int('x')\n    except ValueError as exc:\n        raise RuntimeError('bad') from exc\n",
    "EM": "def f() -> None:\n    raise ValueError('bad')\n",
    "ARG": "def f(unused: int) -> int:\n    return 1\n",
    "N": "def FooBar() -> None:\n    return None\n",
    "PL": "def f() -> None:\n    x = 1\n    x = 1\n",
    "FBT": "def f(flag: bool) -> bool:\n    return flag\n",
    "ERA": "def f() -> int:\n    # return 1\n    return 2\n",
    "ISC": "def f() -> str:\n    return 'a' 'b'\n",
    "ICN": "import typing as t\n\ndef f() -> t.Any:\n    return 1\n",
    "C901": "def f(x: int) -> int:\n"
    + "\n".join(f"    if x == {i}:\n        return {i}" for i in range(20))
    + "\n    return 0\n",
}

_ADVISORY_DEFAULT = ("BLE", "PTH", "PERF", "C901")


def _ruff_lists() -> tuple[list[str], list[str]]:
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    lint = data["tool"]["ruff"]["lint"]
    return list(lint.get("select", [])), list(lint.get("ignore", []))


def test_no_ruff_family_in_both_select_and_ignore() -> None:
    """Blocking ``make lint`` config: a family is enforced or absent, never both."""
    select, ignore = _ruff_lists()
    overlap = sorted(set(select) & set(ignore) & set(_ADVISORY_FAMILIES))
    assert not overlap, f"advisory families still in both select and ignore: {overlap}"


def _ruff_reports(snippet: str, family: str, tmp_path: Path) -> bool:
    source = tmp_path / f"sample_{family}.py"
    source.write_text(snippet, encoding="utf-8")
    proc = subprocess.run(
        [
            "uv",
            "run",
            "--no-sync",
            "ruff",
            "check",
            str(source),
            "--select",
            family,
            "--output-format",
            "concise",
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    return proc.returncode != 0


@pytest.mark.parametrize("family", _ADVISORY_FAMILIES)
def test_remaining_selected_family_is_enforced(family: str, tmp_path: Path) -> None:
    """If a former advisory family stays in ``select``, a sample violation must fail ruff.

    Dropped families (absent from ``select``) are an allowed W8 outcome.
    """
    select, ignore = _ruff_lists()
    if family not in select:
        return
    assert family not in ignore, f"{family} is selected but still ignored (advisory-only lint)"
    snippet = _SAMPLES[family]
    assert _ruff_reports(snippet, family, tmp_path), (
        f"{family} is selected but the sample violation was not reported"
    )


def test_makefile_defines_lint_ruff_advisory_target() -> None:
    """Named deliverable: ``lint-ruff-advisory`` must exist and select advisory families."""
    makefile = read_text("Makefile")
    assert re.search(r"^lint-ruff-advisory:", makefile, re.MULTILINE), (
        "Make target lint-ruff-advisory missing"
    )
    assert "lint-ruff-advisory" in makefile
    recipe = re.search(
        r"^lint-ruff-advisory:.*\n(?:\t.*\n)*",
        makefile,
        re.MULTILINE,
    )
    assert recipe is not None, "lint-ruff-advisory recipe missing"
    assert "--select" in recipe.group(0)
    assert "$(RUFF_ADVISORY_FAMILIES)" in recipe.group(0)


def test_ruff_advisory_families_default_is_ble_pth_perf_c901() -> None:
    """Named deliverable: ``RUFF_ADVISORY_FAMILIES`` defaults to the W8 advisory set."""
    makefile = read_text("Makefile")
    match = re.search(
        r"^RUFF_ADVISORY_FAMILIES\s*\??=\s*(\S+)\s*$",
        makefile,
        re.MULTILINE,
    )
    assert match is not None, "RUFF_ADVISORY_FAMILIES assignment missing from Makefile"
    families = tuple(part.strip() for part in match.group(1).split(",") if part.strip())
    assert families == _ADVISORY_DEFAULT, (
        f"RUFF_ADVISORY_FAMILIES default {families!r} != {_ADVISORY_DEFAULT!r}"
    )


def test_integration_yml_runs_lint_ruff_advisory_non_blocking() -> None:
    """CI must invoke ``make lint-ruff-advisory`` with ``continue-on-error``."""
    doc = load_workflow("integration.yml")
    jobs = doc.get("jobs") or {}
    found = False
    for job in jobs.values():
        for step in job.get("steps") or []:
            run = str(step.get("run") or "")
            if "lint-ruff-advisory" not in run:
                continue
            found = True
            assert step.get("continue-on-error") is True, (
                "lint-ruff-advisory CI step must be continue-on-error: true"
            )
    assert found, "integration.yml never runs make lint-ruff-advisory"
