"""W1.3 / D10 — loud p0 credential skip degradation (wave 15, green after W4)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from tests.cli.support_provider_registry import scaffold_mergecraft_home
from tests.trust_credentials.support import NOUS_SLUG, W4_XFAIL, import_agent_resolve_symbol

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch


@W4_XFAIL
def test_skipped_p0_names_agent_slot_provider_and_env_var(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """D10 — a p0 skipped for missing credentials names agent, slot, provider, env var."""
    build = import_agent_resolve_symbol("build_missing_credential_degradation")
    scaffold_mergecraft_home(tmp_path)
    monkeypatch.chdir(tmp_path)
    for key in ("NOUS_API_KEY", "MERGECRAFT_CUSTOM_PROVIDER_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    message = build(
        agent_id="mergecraft-reviewer",
        slot="p0",
        slug=NOUS_SLUG,
        wired=True,
    )
    lowered = message.lower()
    assert "mergecraft-reviewer" in lowered or "reviewer" in lowered
    assert "p0" in lowered
    assert "nous" in lowered
    assert "mergecraft_custom_provider_api_key" in lowered or "nous_api_key" in lowered
