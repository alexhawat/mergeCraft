"""Control-weakening switches and the operator overrides that share their files.

:class:`ControlSwitches` holds the three switches that weaken a control. Each
field keeps its raw value and enables only for the literal string ``"1"``
(:class:`~mergecraft.config.env.ExactFlag`), because Pydantic's ``bool`` also
accepts ``true`` / ``yes`` / ``on`` / ``t`` / ``y`` and would widen a control an
operator never asked to widen. The model is deliberately hidden: it is not a
repo-settings field, no CLI surface renders it, and no docs describe it
(PS-D13).

:class:`RuntimeOverridesEnv` holds the operator knobs that live in the same
modules but are not exact-``"1"`` switches: the Codex sandbox request (raw,
stripped and lowercased; an unknown value is still ignored toward the
restrictive default in :mod:`mergecraft.agents.codex`), the agent user, the
egress DNS resolver override, and the operator linked-repos grant.

The package is a leaf (see :mod:`mergecraft.config.env`); this module imports
``pydantic`` and the package itself and nothing else.
"""

from __future__ import annotations

from typing import Annotated, Any, Final

from pydantic import BeforeValidator, Field
from pydantic_settings import SettingsConfigDict

from mergecraft.config.env._base import EnvSettings, ExactFlag

__all__ = ["ALLOW_UNSANDBOXED_SHELL_ENV", "ControlSwitches", "RuntimeOverridesEnv"]

#: The unsandboxed-shell override's variable name. It lives beside the model that
#: parses it so a module that only *labels* the override imports the name rather
#: than re-declaring an env-name literal the read inventory would see.
ALLOW_UNSANDBOXED_SHELL_ENV: Final[str] = "MERGECRAFT_ALLOW_UNSANDBOXED_SHELL"


def _strip_or_none(value: Any) -> Any:
    """Strip a free-form value; empty and whitespace-only become "absent"."""
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return value


def _sandbox_value(value: Any) -> Any:
    """Strip and lowercase the Codex sandbox request, keeping unknown spellings."""
    if value is None:
        return None
    text = str(value).strip().lower()
    return text or None


_Stripped = Annotated[str | None, BeforeValidator(_strip_or_none)]


class ControlSwitches(EnvSettings):
    """The exact-``"1"`` control switches. Never listed, never documented."""

    model_config = SettingsConfigDict(
        case_sensitive=True,
        extra="ignore",
        env_ignore_empty=True,
        arbitrary_types_allowed=True,
    )

    allow_unsandboxed_shell: Annotated[ExactFlag, BeforeValidator(ExactFlag)] = Field(
        default_factory=ExactFlag,
        validation_alias="MERGECRAFT_ALLOW_UNSANDBOXED_SHELL",
        json_schema_extra={"control_switch": True},
    )
    allow_root: Annotated[ExactFlag, BeforeValidator(ExactFlag)] = Field(
        default_factory=ExactFlag,
        validation_alias="MERGECRAFT_ALLOW_ROOT",
        json_schema_extra={"control_switch": True},
    )
    filtered_egress_opt_in: Annotated[ExactFlag, BeforeValidator(ExactFlag)] = Field(
        default_factory=ExactFlag,
        validation_alias="MERGECRAFT_FILTERED_EGRESS_ISOLATED_RUNTIME",
        json_schema_extra={"control_switch": True},
    )


class RuntimeOverridesEnv(EnvSettings):
    """Operator knobs in the control-switch modules that are not exact flags."""

    model_config = SettingsConfigDict(
        case_sensitive=True,
        extra="ignore",
        env_ignore_empty=True,
    )

    codex_sandbox: Annotated[str | None, BeforeValidator(_sandbox_value)] = Field(
        default=None, validation_alias="MERGECRAFT_CODEX_SANDBOX"
    )
    agent_user: _Stripped = Field(default=None, validation_alias="MERGECRAFT_AGENT_USER")
    egress_dns_resolvers: _Stripped = Field(
        default=None, validation_alias="MERGECRAFT_EGRESS_DNS_RESOLVERS"
    )
    authorized_linked_repos: _Stripped = Field(
        default=None, validation_alias="MERGECRAFT_AUTHORIZED_LINKED_REPOS"
    )
