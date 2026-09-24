"""The private httpcore backend the egress transport subclasses must stay pinned.

``src/mergecraft/security/egress.py`` subclasses
``httpcore._backends.base.NetworkBackend`` — a private API. The package only
arrives transitively through httpx, so a lock resolution can drop it without
any declared dependency breaking the build. This test pins the private symbol
and requires the package to be declared directly.
"""

from __future__ import annotations

import re
import tomllib
from typing import Final

from tests.ci.workflow_support import REPO_ROOT

_PYPROJECT: Final = REPO_ROOT / "pyproject.toml"
_EGRESS: Final = REPO_ROOT / "src" / "mergecraft" / "security" / "egress.py"


def _runtime_dependency_names() -> set[str]:
    data = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
    names: set[str] = set()
    for entry in data["project"]["dependencies"]:
        match = re.match(r"^([A-Za-z0-9._-]+)", entry.strip())
        assert match is not None, f"cannot parse dependency {entry!r}"
        names.add(match.group(1).lower().replace("_", "-"))
    return names


def test_httpcore_network_backend_is_importable_and_declared() -> None:
    assert "httpcore" in _runtime_dependency_names(), (
        "security/egress.py couples to httpcore private APIs; httpcore must be a "
        "declared direct dependency, not a transitive accident"
    )
    source = _EGRESS.read_text(encoding="utf-8")
    assert "httpcore._backends.base" in source, (
        "the coupling under test moved; re-anchor this test to the new private import"
    )

    from httpcore._backends.base import NetworkBackend

    connect_tcp = getattr(NetworkBackend, "connect_tcp", None)
    assert callable(connect_tcp), (
        "httpcore._backends.base.NetworkBackend must still expose connect_tcp; "
        "the pinned version no longer matches the subclass contract"
    )
