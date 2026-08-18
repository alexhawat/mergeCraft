"""Policy exceptions — bounded waivers with expiry (DG5)."""

from __future__ import annotations

from datetime import UTC, datetime

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

from mergecraft.policy.schema import PolicyConfigError, RuleScope, _raise_config_error
from mergecraft.policy.scoping import ScopeContext, _scope_matches


class ExceptionScope(BaseModel):
    """Scope restriction for a policy exception waiver."""

    model_config = ConfigDict(extra="forbid")

    org: str | None = None
    repo: str | None = None
    branch: str | None = None
    path: str | None = None
    language: str | None = None


class PolicyException(BaseModel):
    """A time-bounded waiver for one policy rule."""

    model_config = ConfigDict(extra="forbid")

    id: str
    rule_id: str
    reason: str
    approver: str
    scope: ExceptionScope
    expires_at: datetime


def parse_exception(text: str) -> PolicyException:
    """Parse one YAML exception document."""
    try:
        loaded = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        msg = f"invalid YAML in policy exception: {exc}"
        raise PolicyConfigError(msg) from exc
    if not isinstance(loaded, dict):
        msg = "policy exception must be a YAML mapping"
        raise PolicyConfigError(msg)
    try:
        return PolicyException.model_validate(loaded)
    except ValidationError as exc:
        _raise_config_error(exc)


def parse_exceptions_document(text: str) -> list[PolicyException]:
    """Parse a policy exceptions bundle (``exceptions:`` list) or one document."""
    try:
        loaded = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        msg = f"invalid YAML in policy exceptions document: {exc}"
        raise PolicyConfigError(msg) from exc
    if loaded is None:
        msg = "policy exceptions document is empty"
        raise PolicyConfigError(msg)
    if isinstance(loaded, dict) and "exceptions" in loaded:
        exceptions_raw = loaded["exceptions"]
        if not isinstance(exceptions_raw, list):
            msg = "policy 'exceptions' key must be a list"
            raise PolicyConfigError(msg)
        parsed: list[PolicyException] = []
        for item in exceptions_raw:
            if not isinstance(item, dict):
                msg = "each policy exception must be a YAML mapping"
                raise PolicyConfigError(msg)
            try:
                parsed.append(PolicyException.model_validate(item))
            except ValidationError as exc:
                _raise_config_error(exc)
        return parsed
    return [parse_exception(text)]


def exception_applies(
    exc: PolicyException,
    *,
    context: ScopeContext,
    now: datetime,
) -> bool:
    """Return whether ``exc`` is active for ``context`` at ``now``."""
    expires = exc.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    current = now if now.tzinfo is not None else now.replace(tzinfo=UTC)
    if current >= expires:
        return False
    rule_scope = RuleScope(
        org=exc.scope.org,
        repo=exc.scope.repo,
        branch=exc.scope.branch,
        path=exc.scope.path,
        language=exc.scope.language,
    )
    return _scope_matches(rule_scope, context)


__all__ = [
    "ExceptionScope",
    "PolicyException",
    "exception_applies",
    "parse_exception",
    "parse_exceptions_document",
]
