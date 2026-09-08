"""#616 — ``trust set-self-review --gh-apply`` updates default-branch config."""

from __future__ import annotations

import base64
import json
from typing import TYPE_CHECKING

from typer.testing import CliRunner

from mergecraft.cli.app import app
from mergecraft.cli.trust_cmd import apply_self_review_on_default_branch, patch_self_review_yaml

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch

runner = CliRunner()
_CONFIRM = "--i-understand-this-grants-approval-authority"


def test_patch_self_review_yaml_preserves_comments() -> None:
    original = (
        "# dogfood — do not strip\n"
        "trust:\n"
        "  selfReview: 'off'  # quote me\n"
        "  agentSandbox: 'dispatch'\n"
    )
    updated = patch_self_review_yaml(original, "full")
    assert "# dogfood — do not strip" in updated
    assert 'selfReview: "full"' in updated
    assert "agentSandbox: 'dispatch'" in updated


def test_gh_apply_full_still_requires_confirmation(tmp_path: Path) -> None:
    config = tmp_path / ".mergecraft" / "config.yaml"
    config.parent.mkdir(parents=True)
    config.write_text("trust:\n  selfReview: 'off'\n", encoding="utf-8")
    result = runner.invoke(
        app,
        ["trust", "set-self-review", "full", "--gh-apply", "--cwd", str(tmp_path)],
    )
    assert result.exit_code != 0
    assert "approval" in result.output.lower()
    assert "selfReview: 'off'" in config.read_text(encoding="utf-8")


def test_gh_apply_opens_default_branch_pr(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    config = tmp_path / ".mergecraft" / "config.yaml"
    config.parent.mkdir(parents=True)
    config.write_text(
        "# keep\ntrust:\n  selfReview: 'off'\n  agentSandbox: 'dispatch'\n",
        encoding="utf-8",
    )
    opened: list[str] = []

    def _fake_apply(level: str, *, runner: object | None = None) -> str:
        opened.append(level)
        return "https://github.com/acme/demo/pull/616"

    monkeypatch.setattr("mergecraft.cli.trust_cmd.apply_self_review_on_default_branch", _fake_apply)
    result = runner.invoke(
        app,
        [
            "trust",
            "set-self-review",
            "full",
            _CONFIRM,
            "--gh-apply",
            "--cwd",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 0, result.output
    assert opened == ["full"]
    assert 'selfReview: "full"' in config.read_text(encoding="utf-8")
    assert "# keep" in config.read_text(encoding="utf-8")
    assert "https://github.com/acme/demo/pull/616" in result.output


def test_apply_self_review_on_default_branch_uses_gh_api() -> None:
    current = "trust:\n  selfReview: 'off'\n"
    encoded = base64.b64encode(current.encode("utf-8")).decode("ascii")
    calls: list[list[str]] = []

    def _gh(args: list[str], *, input_text: str | None = None) -> str:
        calls.append(args)
        if args[:2] == ["repo", "view"]:
            return json.dumps(
                {
                    "nameWithOwner": "acme/demo",
                    "defaultBranchRef": {"name": "main"},
                }
            )
        if args[:2] == ["api", "repos/acme/demo/contents/.mergecraft/config.yaml?ref=main"]:
            return json.dumps({"content": encoded, "sha": "blobsha"})
        if args[:2] == ["api", "repos/acme/demo/git/ref/heads/main"]:
            return json.dumps({"object": {"sha": "aaa" * 13 + "a"}})
        if args[:3] == ["api", "-X", "POST"]:
            return json.dumps({"ref": "refs/heads/mergecraft/trust-self-review-full"})
        if args[:3] == ["api", "-X", "PUT"]:
            assert input_text is not None
            body = json.loads(input_text)
            assert body["branch"] == "mergecraft/trust-self-review-full"
            decoded = base64.b64decode(body["content"]).decode("utf-8")
            assert 'selfReview: "full"' in decoded
            return json.dumps({"content": {"sha": "new"}})
        if args[:2] == ["pr", "create"]:
            return "https://github.com/acme/demo/pull/616\n"
        raise AssertionError(args)

    url = apply_self_review_on_default_branch("full", runner=_gh)
    assert url == "https://github.com/acme/demo/pull/616"
    assert any(call[:2] == ["pr", "create"] for call in calls)
    assert "--base" in calls[-1]
    assert "main" in calls[-1]
