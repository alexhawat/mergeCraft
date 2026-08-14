"""C3 — action.yml/action.yaml description-expression guard (c498e82 incident).

``scripts/check_action_yml_hygiene.py`` had only a manual scratch-copy
verification (per its own PR description), not a committed regression test —
flagged on PR #189. `_scan_manifest`'s block/folded-scalar continuation
scanning (indent-boundary detection, `|`/`>` handling) is exactly the kind
of logic that regresses silently without a test exercising each YAML
scalar style directly.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

from tests.ci.workflow_support import REPO_ROOT


def _load_check_action_yml_hygiene() -> Any:
    path = REPO_ROOT / "scripts" / "check_action_yml_hygiene.py"
    assert path.is_file(), "scripts/check_action_yml_hygiene.py missing"
    spec = importlib.util.spec_from_file_location("check_action_yml_hygiene", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "action.yml"
    path.write_text(text, encoding="utf-8")
    return path


class TestScanManifest:
    """Direct coverage of `_scan_manifest` across each YAML scalar style."""

    def test_inline_scalar_with_expression_is_flagged(self, tmp_path: Path) -> None:
        module = _load_check_action_yml_hygiene()
        path = _write(
            tmp_path,
            "inputs:\n"
            "  token:\n"
            "    description: 'wire it as `${{ secrets.TOKEN }}`'\n"
            "    required: false\n",
        )
        offenses = module._scan_manifest(path)
        assert [o.line_no for o in offenses] == [3]

    def test_folded_block_with_expression_is_flagged(self, tmp_path: Path) -> None:
        module = _load_check_action_yml_hygiene()
        path = _write(
            tmp_path,
            "inputs:\n"
            "  token:\n"
            "    description: >-\n"
            "      Wire the secret via the workflow's env block, e.g.\n"
            "      `${{ secrets.TOKEN }}` in your consumer workflow.\n"
            "    required: false\n",
        )
        offenses = module._scan_manifest(path)
        assert [o.line_no for o in offenses] == [5]

    def test_literal_block_with_expression_is_flagged(self, tmp_path: Path) -> None:
        module = _load_check_action_yml_hygiene()
        path = _write(
            tmp_path,
            "inputs:\n"
            "  token:\n"
            "    description: |\n"
            "      Direct token, W8.5 / W7.7.\n"
            "      Wire as ``${{ secrets.TOKEN }}`` so it never appears\n"
            "      in the workflow file.\n"
            "    required: false\n",
        )
        offenses = module._scan_manifest(path)
        assert [o.line_no for o in offenses] == [5]

    def test_block_scan_stops_at_dedent(self, tmp_path: Path) -> None:
        """A `${{` after the block's indent ends (the next mapping key) must not be flagged."""
        module = _load_check_action_yml_hygiene()
        path = _write(
            tmp_path,
            "inputs:\n"
            "  token:\n"
            "    description: |\n"
            "      Direct token, no expression here.\n"
            "    required: false\n"
            "  other:\n"
            "    description: uses ${{ github.token }} but not inside a block\n",
        )
        offenses = module._scan_manifest(path)
        assert [o.line_no for o in offenses] == [7]

    def test_clean_manifest_has_no_offenses(self, tmp_path: Path) -> None:
        module = _load_check_action_yml_hygiene()
        path = _write(
            tmp_path,
            "inputs:\n"
            "  token:\n"
            "    description: >-\n"
            "      Wire the secret via the workflow's env block from a secret\n"
            "      named TOKEN (interpolated in your workflow YAML, not written\n"
            "      literally here).\n"
            "    required: false\n"
            "outputs:\n"
            "  result:\n"
            "    value: ${{ steps.run.outputs.result }}\n",
        )
        offenses = module._scan_manifest(path)
        assert offenses == []

    def test_commented_description_line_is_not_a_key(self, tmp_path: Path) -> None:
        module = _load_check_action_yml_hygiene()
        path = _write(
            tmp_path,
            "inputs:\n  token:\n    # description: ${{ secrets.TOKEN }}\n    required: false\n",
        )
        offenses = module._scan_manifest(path)
        assert offenses == []

    def test_offense_str_reports_repo_relative_path_and_line(self, tmp_path: Path) -> None:
        module = _load_check_action_yml_hygiene()
        path = _write(tmp_path, "inputs:\n  x:\n    description: '${{ secrets.X }}'\n")
        offenses = module._scan_manifest(path)
        assert len(offenses) == 1
        # Not repo-relative here (tmp_path is outside REPO) — assert it doesn't raise.
        assert str(offenses[0].line_no) in "3"


class TestFindActionManifests:
    """`_find_action_manifests` excludes vendored/cache/test-fixture trees."""

    def test_excludes_configured_directories(self, tmp_path: Path) -> None:
        module = _load_check_action_yml_hygiene()
        (tmp_path / "action.yml").write_text("inputs: {}\n", encoding="utf-8")
        excluded = tmp_path / ".venv" / "action.yml"
        excluded.parent.mkdir(parents=True)
        excluded.write_text("inputs: {}\n", encoding="utf-8")
        found = module._find_action_manifests(tmp_path)
        assert found == [tmp_path / "action.yml"]

    def test_finds_nested_manifests(self, tmp_path: Path) -> None:
        module = _load_check_action_yml_hygiene()
        nested = tmp_path / "get-installation-token" / "action.yml"
        nested.parent.mkdir(parents=True)
        nested.write_text("inputs: {}\n", encoding="utf-8")
        found = module._find_action_manifests(tmp_path)
        assert found == [nested]


class TestMain:
    def test_fails_when_offense_found(self, tmp_path: Path) -> None:
        module = _load_check_action_yml_hygiene()
        (tmp_path / "action.yml").write_text(
            "inputs:\n  x:\n    description: '${{ secrets.X }}'\n", encoding="utf-8"
        )
        module.REPO = tmp_path
        assert module.main() != 0

    def test_passes_on_clean_tree(self, tmp_path: Path) -> None:
        module = _load_check_action_yml_hygiene()
        (tmp_path / "action.yml").write_text(
            "inputs:\n  x:\n    description: fine, no expression\n", encoding="utf-8"
        )
        module.REPO = tmp_path
        assert module.main() == 0


__all__ = [
    "TestFindActionManifests",
    "TestMain",
    "TestScanManifest",
]
