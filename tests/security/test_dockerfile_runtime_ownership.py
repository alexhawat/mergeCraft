"""The runtime tree stays root-owned; the agent user owns only its HOME (S8).

The action entrypoint runs as root and lazily imports ``/opt/mergecraft``.
Recursively chowning that tree to the agent user hands the agent's own sandbox
target the ability to rewrite the runtime it is dropped *from*. These checks
parse the ``RUN`` instructions so reformatting a comment cannot silently
reintroduce the chown.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DOCKERFILES = (_REPO_ROOT / "Dockerfile", _REPO_ROOT / "Dockerfile.analyzers")


def _run_bodies(dockerfile_text: str) -> list[str]:
    """Join each ``RUN`` instruction body, honouring line continuations."""
    bodies: list[str] = []
    buffer: list[str] = []
    in_run = False
    for raw in dockerfile_text.splitlines():
        stripped = raw.strip()
        if in_run:
            buffer.append(raw)
            if stripped.endswith("\\"):
                continue
            bodies.append("\n".join(buffer))
            buffer = []
            in_run = False
            continue
        if stripped.startswith("RUN "):
            buffer = [raw]
            in_run = True
            if stripped.endswith("\\"):
                continue
            bodies.append(raw)
            buffer = []
            in_run = False
    if in_run and buffer:
        bodies.append("\n".join(buffer))
    return bodies


@pytest.fixture(params=_DOCKERFILES, ids=[path.name for path in _DOCKERFILES])
def dockerfile_text(request: pytest.FixtureRequest) -> str:
    path: Path = request.param
    assert path.exists(), f"missing {path}"
    return path.read_text(encoding="utf-8")


def test_runtime_tree_is_not_recursively_chowned_to_the_agent_user(
    dockerfile_text: str,
) -> None:
    offenders = [
        body
        for body in _run_bodies(dockerfile_text)
        if "chown -R" in body and "/opt/mergecraft" in body and "mergecraft" in body
    ]
    assert not offenders, (
        "the runtime tree must stay root-owned; found a recursive chown:\n"
        + "\n---\n".join(offenders)
    )


def test_agent_user_and_precompiled_bytecode_remain(dockerfile_text: str) -> None:
    bodies = _run_bodies(dockerfile_text)
    assert any("useradd" in body and "mergecraft" in body for body in bodies), (
        "the image must still create the agent user"
    )
    assert any("compileall" in body and "/opt/mergecraft" in body for body in bodies), (
        "bytecode must be compiled before the ownership change"
    )


def test_action_dockerfile_still_asserts_the_privilege_drop() -> None:
    text = (_REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert any(
        "setpriv" in body and "mergecraft" in body and "exit 1" in body
        for body in _run_bodies(text)
    ), "the action image must refuse to build without setpriv + the agent user"
