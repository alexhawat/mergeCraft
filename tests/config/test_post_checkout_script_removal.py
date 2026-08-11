"""Plan W12.5 — ``postCheckoutScript`` removal (D5 default).

D5 (locked): the field is dead code — ``git_setup.py`` logged and never executed
it — so W12 removed the field, its docs, and the context plumbing.

Pinning the **removal** interpretation (the D-table default):

- ``RepoSettings`` accepts no ``postCheckoutScript`` key.
- ``ToolContext`` carries no ``post_checkout_script`` attribute.
- ``setup_git`` accepts no ``post_checkout_script`` parameter.
"""

from __future__ import annotations

import inspect

import pytest
from pydantic import ValidationError

from mergecraft.config.settings import RepoSettings
from mergecraft.mcp.context import ToolContext
from mergecraft.utils.git_setup import setup_git


def test_repo_settings_has_no_post_checkout_script() -> None:
    """D5 — the config surface no longer accepts the dead field."""
    with pytest.raises(ValidationError):
        RepoSettings.model_validate({"postCheckoutScript": "echo hi"})


def test_tool_context_has_no_post_checkout_script() -> None:
    """D5 — the runtime context drops the plumbing alongside the field."""
    assert "post_checkout_script" not in {
        field.name for field in ToolContext.__dataclass_fields__.values()
    }, "ToolContext still plumbs post_checkout_script"


def test_setup_git_has_no_post_checkout_script_param() -> None:
    """D5 — ``setup_git`` keeps no vestigial parameter for the dead hook."""
    assert "post_checkout_script" not in inspect.signature(setup_git).parameters
