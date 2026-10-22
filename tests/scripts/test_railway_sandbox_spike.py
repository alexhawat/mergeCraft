"""The Railway spike script plans without spending anything (#896).

The paid run is the operator's. These tests pin the properties that make the kit safe
to ship: ``--dry-run`` prints the whole create -> checkout -> test/review -> summary ->
destroy plan, needs no credential, and never imports the SDK; the sandbox is always
destroyed; provider credentials are forwarded by name to the review step only; and no
credential value appears in the file.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess

import pytest
from tests.ci.workflow_support import REPO_ROOT

_SCRIPT = REPO_ROOT / "scripts" / "railway_sandbox_spike.mjs"
# Low-entropy on purpose: a secret scanner should have no key-shaped literal to flag.
_CANARY = "placeholder-value-for-the-spike-test"
_SHA = "6197b478c0229a96777b0092febd7d1c3264319d"
pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


def _run(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    base = {k: v for k, v in os.environ.items() if not k.startswith("RAILWAY_")}
    return subprocess.run(
        ["node", str(_SCRIPT), *args],
        capture_output=True,
        text=True,
        check=False,
        env={**base, **(env or {})},
        timeout=60,
        cwd=REPO_ROOT,
    )


def test_dry_run_prints_the_whole_plan_in_order() -> None:
    completed = _run("--sha", _SHA, "--dry-run")

    assert completed.returncode == 0, completed.stderr
    steps = [line.split(":", 1)[0] for line in completed.stdout.splitlines()[1:]]
    assert steps == [
        "create",
        "clone",
        "checkout",
        "deps",
        "tests",
        "review",
        "read-artifact",
        "destroy",
    ]
    assert "nothing is billed" in completed.stdout


def test_dry_run_needs_no_railway_credential() -> None:
    completed = _run("--sha", _SHA, "--dry-run", env={"RAILWAY_API_TOKEN": ""})

    assert completed.returncode == 0
    assert "RAILWAY_API_TOKEN" not in completed.stderr


def test_a_real_run_without_credentials_stops_before_touching_the_sdk() -> None:
    completed = _run("--sha", _SHA)

    assert completed.returncode == 2
    assert "RAILWAY_API_TOKEN is not set" in completed.stderr


def test_a_checkpoint_skips_the_clone_and_a_capture_adds_a_step() -> None:
    completed = _run(
        "--sha", _SHA, "--checkpoint", "after-deps", "--capture-checkpoint", "next", "--dry-run"
    )

    steps = [line.split(":", 1)[0] for line in completed.stdout.splitlines()[1:]]
    assert "clone" not in steps
    assert "Sandbox.create(after-deps)" in completed.stdout
    assert steps.index("checkpoint") < steps.index("destroy")


def test_the_sandbox_is_destroyed_last_whatever_happens() -> None:
    completed = _run("--sha", _SHA, "--dry-run")

    assert completed.stdout.splitlines()[-1].startswith("destroy:")
    text = _SCRIPT.read_text(encoding="utf-8")
    assert "finally {" in text
    assert text.rindex("sandbox.destroy()") > text.index("finally {")


def test_provider_credentials_are_forwarded_by_name_to_the_review_step_only() -> None:
    completed = _run(
        "--sha",
        _SHA,
        "--pass-env",
        "OPENCODE_GO_API_KEY",
        "--dry-run",
        env={"OPENCODE_GO_API_KEY": _CANARY},
    )

    assert _CANARY not in completed.stdout + completed.stderr
    forwarded = [line for line in completed.stdout.splitlines() if "env forwarded" in line]
    assert len(forwarded) == 1
    assert forwarded[0].startswith("review:")


@pytest.mark.parametrize(
    "args",
    [
        ["--sha", "main"],
        ["--sha", "abc123"],
        ["--sha", _SHA, "--repo", "no slash"],
        ["--sha", _SHA, "--pass-env", "lower"],
    ],
)
def test_malformed_arguments_are_rejected(args: list[str]) -> None:
    completed = _run(*args, "--dry-run")

    assert completed.returncode == 2
    assert completed.stderr.startswith("error:")


def test_no_credential_is_written_into_the_script() -> None:
    text = _SCRIPT.read_text(encoding="utf-8")

    assert not re.search(r"(?:sk|ghp|rw)_[A-Za-z0-9]{16,}", text)
    assert "RAILWAY_API_TOKEN" in text  # read by name from the environment, never inlined
