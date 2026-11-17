"""Pin the opt-in Discuss workflow's event, concurrency, and token boundaries."""

from __future__ import annotations

import yaml

from tests.ci.workflow_support import read_text


def test_discussion_workflow_is_separate_and_its_default_token_cannot_write() -> None:
    workflow = yaml.safe_load(read_text("examples/workflows/mergecraft-discuss.yml"))
    assert workflow[True] == {"pull_request_review_comment": {"types": ["created"]}}
    assert workflow["permissions"] == {}
    assert workflow["concurrency"] == {
        "group": "mergecraft-discuss-${{ github.event.comment.id }}",
        "cancel-in-progress": False,
    }
    assert set(workflow["jobs"]) == {"discuss"}
    app, discuss = workflow["jobs"]["discuss"]["steps"]
    assert app["with"]["permission-pull-requests"] == "write"
    assert discuss["with"]["discuss"] == "enabled"
    assert discuss["with"]["token"] == "${{ steps.reviewer.outputs.token }}"
    assert not {"prompt", "prompt_file", "status_checks"} & set(discuss["with"])
    assert discuss["uses"].endswith("@REPLACE_WITH_DISCUSS_CAPABLE_SHA")
    assert all("run" not in step and "checkout" not in step["uses"] for step in (app, discuss))


def test_standard_review_scaffold_does_not_trigger_or_enter_discuss() -> None:
    workflow = yaml.safe_load(read_text("examples/workflows/mergecraft.yml"))
    assert "pull_request_review_comment" not in workflow[True]
    assert all(
        "discuss" not in step.get("with", {}) for step in workflow["jobs"]["mergecraft"]["steps"]
    )
