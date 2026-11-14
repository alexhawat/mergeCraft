"""Exercise the separate fix handoff through the example renderer."""

from __future__ import annotations

import re

import yaml
from scripts.render_example_workflows import render_all

from tests.ci.workflow_support import read_text, workflow_on, workflow_run_scripts


def test_fix_workflow_is_rendered_separately_with_read_only_permissions() -> None:
    rendered = render_all()
    fix = rendered["fix"]
    assert fix == read_text("examples/workflows/mergecraft-fix.yml")
    assert "fix-brief" not in rendered["minimal"]
    assert "fix-brief" not in rendered["hardened"]

    doc = yaml.safe_load(fix)
    dispatch = workflow_on(doc)
    assert set(dispatch) == {"workflow_dispatch"}
    assert set(dispatch["workflow_dispatch"]["inputs"]) == {"pr-number", "fix-brief"}
    assert doc["permissions"] == {"pull-requests": "read"}
    workflow_job = doc["jobs"]["prepare-brief"]
    assert "permissions" not in workflow_job
    assert "github.event.repository.default_branch" in workflow_job["if"]
    assert "github.ref_type == 'branch'" in workflow_job["if"]
    assert "secrets." not in fix
    assert "actions/checkout" not in fix
    assert all("${{" not in run for run in workflow_run_scripts(doc))

    (upload,) = [step for step in workflow_job["steps"] if "uses" in step]
    assert re.fullmatch(r"actions/upload-artifact@[0-9a-f]{40}", upload["uses"])
    assert upload["with"]["name"] == "mergecraft-fix-brief"
    assert upload["with"]["path"] == "${{ runner.temp }}/fix-brief.json"


def test_fix_workflow_validates_the_brief_for_the_open_pull_request() -> None:
    doc = yaml.safe_load(render_all()["fix"])
    install, validate, _upload = doc["jobs"]["prepare-brief"]["steps"]
    assert "GH_TOKEN" not in install["env"]
    assert "^[0-9a-f]{40}$" in install["run"]
    assert "git+https://github.com/" in install["run"]

    assert validate["env"] == {
        "GH_TOKEN": "${{ github.token }}",
        "GH_REPO": "${{ github.repository }}",
    }
    script = validate["run"]
    assert '"$GITHUB_EVENT_PATH"' in script
    assert 'select(.state == "open") | .head.sha' in script
    assert script.index("unset GH_TOKEN") < script.index("findings brief")
    assert '--expect-change-id "$GH_REPO#$pr_number" --expect-head "$head_sha"' in script
    assert '> "$RUNNER_TEMP/fix-brief.json"' in script
