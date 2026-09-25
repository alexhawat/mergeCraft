"""The legacy installation-token script is gone; the composite keeps working.

Nothing invokes ``get-installation-token/main.py`` — the composite calls
``actions/create-github-app-token`` directly — and it emits the removed
``::set-output`` command. Deleting it must not disturb the composite, which
consumers reference as ``./get-installation-token``.
"""

from __future__ import annotations

import yaml

from tests.ci.workflow_support import REPO_ROOT

_MANIFEST = REPO_ROOT / "get-installation-token" / "action.yml"
_LEGACY_SCRIPT = REPO_ROOT / "get-installation-token" / "main.py"


def test_the_unused_legacy_script_is_deleted() -> None:
    assert not _LEGACY_SCRIPT.exists(), (
        "get-installation-token/main.py is never invoked and emits the deprecated "
        "::set-output command; it must be deleted"
    )


def test_the_composite_still_mints_and_validates_a_token() -> None:
    doc = yaml.safe_load(_MANIFEST.read_text(encoding="utf-8"))
    assert isinstance(doc, dict)
    runs = doc.get("runs")
    assert isinstance(runs, dict)
    assert runs.get("using") == "composite"
    step_ids = {str(step.get("id")) for step in runs.get("steps") or [] if isinstance(step, dict)}
    assert {"mint", "validate"} <= step_ids, "the composite's mint/validate steps must survive"
    text = _MANIFEST.read_text(encoding="utf-8")
    assert "actions/create-github-app-token@" in text, "the mint step must stay wired"
    assert "main.py" not in text, "the composite must not reference the deleted script"
