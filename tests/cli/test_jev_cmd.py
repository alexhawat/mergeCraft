"""#786 — ``mergecraft jev enable|disable|status|set``."""

from __future__ import annotations

import base64
import json
from typing import TYPE_CHECKING

import pytest
import yaml
from typer.testing import CliRunner

from mergecraft.cli import jev_cmd
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


# --- MC-24045d: a commented config must never gain a second ``jev:`` key -------
#
# `append_config_mapping` appends a new top-level mapping. PyYAML keeps the
# last duplicate key, so appending silently discarded every Jev setting the
# consumer already had. These pin the in-place behaviour for both write paths.


_COMMENTED_CONFIG = """# repo config with a comment
model: sonnet

jev:
  # why this budget
  budgetTokens: 123456
  enabled: false

# trailing comment belongs to tracing
tracing:
  enabled: true
"""


def _write_commented_config(tmp_path: Path) -> Path:
    config = tmp_path / ".mergecraft" / "config.yaml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(_COMMENTED_CONFIG, encoding="utf-8")
    return config


def test_enable_on_commented_config_keeps_existing_jev_keys(tmp_path: Path) -> None:
    """A commented config with existing Jev keys must not lose them on enable."""
    config = _write_commented_config(tmp_path)

    result = runner.invoke(app, ["jev", "enable", "--cwd", str(tmp_path)])

    assert result.exit_code == 0, result.stdout
    raw = config.read_text(encoding="utf-8")
    assert raw.count("\njev:") + raw.startswith("jev:") == 1, f"duplicate jev key:\n{raw}"
    loaded = yaml.safe_load(raw)
    assert loaded["jev"]["enabled"] is True
    assert loaded["jev"]["budgetTokens"] == 123456, "existing Jev settings were discarded"
    assert loaded["model"] == "sonnet"
    assert loaded["tracing"] == {"enabled": True}


def test_enable_on_commented_config_preserves_comments(tmp_path: Path) -> None:
    """The in-block and trailing comments survive an enable."""
    config = _write_commented_config(tmp_path)

    runner.invoke(app, ["jev", "enable", "--cwd", str(tmp_path)])

    raw = config.read_text(encoding="utf-8")
    assert "# repo config with a comment" in raw
    assert "# why this budget" in raw
    assert "# trailing comment belongs to tracing" in raw


def test_set_on_commented_config_keeps_existing_jev_keys(tmp_path: Path) -> None:
    """``set`` rewrites the block in place rather than appending a second one."""
    config = _write_commented_config(tmp_path)

    result = runner.invoke(app, ["jev", "set", "budgetTokens", "999", "--cwd", str(tmp_path)])

    assert result.exit_code == 0, result.stdout
    raw = config.read_text(encoding="utf-8")
    assert raw.count("\njev:") + raw.startswith("jev:") == 1, f"duplicate jev key:\n{raw}"
    loaded = yaml.safe_load(raw)
    assert loaded["jev"]["budgetTokens"] == 999
    assert loaded["jev"]["enabled"] is False, "the untouched key was discarded"
    assert loaded["model"] == "sonnet"
    assert loaded["tracing"] == {"enabled": True}
    assert "# trailing comment belongs to tracing" in raw


def test_repeated_writes_never_accumulate_jev_keys(tmp_path: Path) -> None:
    """Enable, disable and set in sequence leave exactly one ``jev:`` mapping."""
    config = _write_commented_config(tmp_path)

    runner.invoke(app, ["jev", "enable", "--cwd", str(tmp_path)])
    runner.invoke(app, ["jev", "disable", "--cwd", str(tmp_path)])
    runner.invoke(app, ["jev", "set", "budgetTokens", "777", "--cwd", str(tmp_path)])
    runner.invoke(app, ["jev", "enable", "--cwd", str(tmp_path)])

    raw = config.read_text(encoding="utf-8")
    assert raw.count("\njev:") + raw.startswith("jev:") == 1, f"duplicate jev key:\n{raw}"
    loaded = yaml.safe_load(raw)
    assert loaded["jev"] == {"budgetTokens": 777, "enabled": True}


# --- MC-3b1980: every YAML boolean spelling must be replaced, not duplicated --
#
# patch_jev_enabled_yaml matched only unquoted lowercase true/false. A valid
# `enabled: True` fell through to the insert path, which added a second
# `enabled` key ahead of the original — and PyYAML keeps the last one, so
# `jev disable` printed success while Jev stayed enabled.


@pytest.mark.parametrize(
    "spelling",
    ["true", "True", "TRUE", "yes", "Yes", "on", '"true"', "'true'"],
)
def test_disable_turns_off_every_truthy_yaml_spelling(tmp_path: Path, spelling: str) -> None:
    """``disable`` must actually disable, whatever spelling the consumer used."""
    config = tmp_path / ".mergecraft" / "config.yaml"
    config.parent.mkdir(parents=True)
    config.write_text(f"# note\njev:\n  enabled: {spelling}\n", encoding="utf-8")

    result = runner.invoke(app, ["jev", "disable", "--cwd", str(tmp_path)])

    assert result.exit_code == 0, result.stdout
    raw = config.read_text(encoding="utf-8")
    assert raw.count("enabled:") == 1, f"duplicate enabled key for {spelling!r}:\n{raw}"
    loaded = yaml.safe_load(raw)
    assert loaded["jev"]["enabled"] is False, (
        f"disable reported success but {spelling!r} survived as {loaded['jev']['enabled']!r}"
    )


@pytest.mark.parametrize("spelling", ["false", "False", "FALSE", "no", "off", '"false"'])
def test_enable_turns_on_every_falsey_yaml_spelling(tmp_path: Path, spelling: str) -> None:
    """``enable`` is the mirror case and must not leave the old value last."""
    config = tmp_path / ".mergecraft" / "config.yaml"
    config.parent.mkdir(parents=True)
    config.write_text(f"# note\njev:\n  enabled: {spelling}\n", encoding="utf-8")

    result = runner.invoke(app, ["jev", "enable", "--cwd", str(tmp_path)])

    assert result.exit_code == 0, result.stdout
    raw = config.read_text(encoding="utf-8")
    assert raw.count("enabled:") == 1, f"duplicate enabled key for {spelling!r}:\n{raw}"
    assert yaml.safe_load(raw)["jev"]["enabled"] is True


def test_toggle_preserves_an_inline_comment_on_the_enabled_line(tmp_path: Path) -> None:
    """A trailing comment on the toggled line survives the rewrite."""
    config = tmp_path / ".mergecraft" / "config.yaml"
    config.parent.mkdir(parents=True)
    config.write_text("# note\njev:\n  enabled: True  # why\n", encoding="utf-8")

    runner.invoke(app, ["jev", "disable", "--cwd", str(tmp_path)])

    raw = config.read_text(encoding="utf-8")
    assert "# why" in raw
    assert yaml.safe_load(raw)["jev"]["enabled"] is False


def test_write_is_verified_and_falls_back_when_the_line_patch_misses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A patcher that silently no-ops must not be reported as success."""
    config = tmp_path / ".mergecraft" / "config.yaml"
    config.parent.mkdir(parents=True)
    config.write_text("# note\njev:\n  enabled: true\n", encoding="utf-8")

    monkeypatch.setattr(jev_cmd, "patch_jev_enabled_yaml", lambda text, *, enabled: text)

    result = runner.invoke(app, ["jev", "disable", "--cwd", str(tmp_path)])

    assert result.exit_code == 0, result.stdout
    assert yaml.safe_load(config.read_text(encoding="utf-8"))["jev"]["enabled"] is False, (
        "the post-write check did not catch a no-op patcher"
    )
