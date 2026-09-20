"""#786 — ``mergecraft jev enable|disable|status|set``."""

from __future__ import annotations

import base64
import json
from typing import TYPE_CHECKING

import yaml
from typer.testing import CliRunner

from mergecraft.cli.app import app
from mergecraft.cli.jev_cmd import apply_jev_enabled_on_default_branch, patch_jev_enabled_yaml

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()


def _write_config(tmp_path: Path, body: str) -> Path:
    cfg_dir = tmp_path / ".mergecraft"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    path = cfg_dir / "config.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def test_enable_writes_only_the_enabled_key(tmp_path: Path) -> None:
    """Defaults must keep coming from JevSettings, never get frozen into the file."""
    config = _write_config(tmp_path, "models:\n  - anthropic/claude-sonnet\n")

    result = runner.invoke(app, ["jev", "enable", "--cwd", str(tmp_path)])

    assert result.exit_code == 0, result.output
    loaded = yaml.safe_load(config.read_text(encoding="utf-8"))
    assert loaded["jev"] == {"enabled": True}
    # None of the default block's other keys (model, budgetTokens, packs,
    # thresholds) were serialised into the consumer's config.
    assert "model" not in loaded["jev"]
    assert "budgetTokens" not in loaded["jev"]
    assert "packs" not in loaded["jev"]
    assert "thresholds" not in loaded["jev"]


def test_enable_preserves_other_already_present_jev_keys(tmp_path: Path) -> None:
    config = _write_config(
        tmp_path,
        "jev:\n  enabled: false\n  budgetTokens: 100000\n",
    )

    result = runner.invoke(app, ["jev", "enable", "--cwd", str(tmp_path)])

    assert result.exit_code == 0, result.output
    loaded = yaml.safe_load(config.read_text(encoding="utf-8"))
    assert loaded["jev"]["enabled"] is True
    assert loaded["jev"]["budgetTokens"] == 100000


def test_disable_writes_only_the_enabled_key(tmp_path: Path) -> None:
    config = _write_config(tmp_path, "jev:\n  enabled: true\n")

    result = runner.invoke(app, ["jev", "disable", "--cwd", str(tmp_path)])

    assert result.exit_code == 0, result.output
    loaded = yaml.safe_load(config.read_text(encoding="utf-8"))
    assert loaded["jev"]["enabled"] is False


def test_enable_preserves_yaml_comments(tmp_path: Path) -> None:
    config = _write_config(
        tmp_path,
        "# do not strip this\nmodels:\n  - anthropic/claude-sonnet\n",
    )

    result = runner.invoke(app, ["jev", "enable", "--cwd", str(tmp_path)])

    assert result.exit_code == 0, result.output
    text = config.read_text(encoding="utf-8")
    assert "# do not strip this" in text
    assert "enabled: true" in text


def test_set_rejects_a_floating_model_alias_before_writing(tmp_path: Path) -> None:
    config = _write_config(tmp_path, "jev:\n  enabled: true\n")
    before = config.read_text(encoding="utf-8")

    result = runner.invoke(app, ["jev", "set", "model", "jev-latest", "--cwd", str(tmp_path)])

    assert result.exit_code != 0
    collapsed = " ".join(result.output.split())
    assert "floating alias" in collapsed or "pinned" in collapsed
    # Refused before writing — the file is untouched.
    assert config.read_text(encoding="utf-8") == before


def test_set_rejects_a_non_positive_budget_before_writing(tmp_path: Path) -> None:
    config = _write_config(tmp_path, "jev:\n  enabled: true\n")
    before = config.read_text(encoding="utf-8")

    result = runner.invoke(app, ["jev", "set", "budgetTokens", "0", "--cwd", str(tmp_path)])

    assert result.exit_code != 0
    assert config.read_text(encoding="utf-8") == before


def test_set_writes_a_valid_nested_pack_value(tmp_path: Path) -> None:
    config = _write_config(tmp_path, "jev:\n  enabled: true\n")

    result = runner.invoke(app, ["jev", "set", "packs.unit/v1", "false", "--cwd", str(tmp_path)])

    assert result.exit_code == 0, result.output
    loaded = yaml.safe_load(config.read_text(encoding="utf-8"))
    assert loaded["jev"]["packs"]["unit/v1"] is False
    assert loaded["jev"]["enabled"] is True


def test_status_reports_effective_values_and_advisory_note(tmp_path: Path) -> None:
    _write_config(tmp_path, "jev:\n  enabled: true\n")

    result = runner.invoke(app, ["jev", "status", "--cwd", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert "enabled: True" in result.output
    assert "advisory" in result.output.lower()
    assert "never skips the reviewer" in result.output.lower()


def test_patch_jev_enabled_yaml_preserves_comments() -> None:
    original = "# dogfood — do not strip\nother:\n  x: 1\njev:\n  enabled: false  # note\n"
    updated = patch_jev_enabled_yaml(original, enabled=True)
    assert "# dogfood — do not strip" in updated
    assert "other:\n  x: 1" in updated
    assert "enabled: true" in updated


def test_gh_apply_opens_default_branch_pr_for_enable() -> None:
    current = "jev:\n  enabled: false\n"
    encoded = base64.b64encode(current.encode("utf-8")).decode("ascii")
    calls: list[list[str]] = []

    def _gh(args: list[str], *, input_text: str | None = None) -> str:
        calls.append(args)
        if args[:2] == ["repo", "view"]:
            return json.dumps({"nameWithOwner": "acme/demo", "defaultBranchRef": {"name": "main"}})
        if args[:2] == ["api", "repos/acme/demo/contents/.mergecraft/config.yaml?ref=main"]:
            return json.dumps({"content": encoded, "sha": "blobsha"})
        if args[:2] == ["api", "repos/acme/demo/git/ref/heads/mergecraft/jev-enable"]:
            return json.dumps({"message": "Not Found"})
        if args[:2] == ["api", "repos/acme/demo/git/ref/heads/main"]:
            return json.dumps({"object": {"sha": "a" * 40}})
        if args[:3] == ["api", "-X", "POST"]:
            return json.dumps({"ref": "refs/heads/mergecraft/jev-enable"})
        if args[:3] == ["api", "-X", "PUT"]:
            assert input_text is not None
            body = json.loads(input_text)
            assert body["branch"] == "mergecraft/jev-enable"
            decoded = base64.b64decode(body["content"]).decode("utf-8")
            assert "enabled: true" in decoded
            return json.dumps({"content": {"sha": "new"}})
        if args[:2] == ["pr", "list"]:
            return "[]"
        if args[:2] == ["pr", "create"]:
            assert "${{" not in (args[-1] or "")
            return "https://github.com/acme/demo/pull/786\n"
        raise AssertionError(args)

    url = apply_jev_enabled_on_default_branch(enabled=True, runner=_gh)

    assert url == "https://github.com/acme/demo/pull/786"
    assert any(call[:2] == ["pr", "create"] for call in calls)
