"""GitLab ``ScmProvider`` adapter — demand-gated stub (DG9)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, NoReturn

from mergecraft.scm.errors import UnsupportedScmCapability
from mergecraft.scm.protocol import protocol_operation_names

if TYPE_CHECKING:
    from mergecraft.scm.protocol import ScmCapability

_PROVIDER = "GitLabScmAdapter"


def _unsupported(capability: str) -> NoReturn:
    raise UnsupportedScmCapability(
        capability,
        provider=_PROVIDER,
        message=(
            f"GitLab support is not available in this release"
            f" (capability {capability!r} was requested)"
        ),
    )


def _unsupported_method(name: str) -> Any:
    async def method(self: GitLabScmAdapter, *args: Any, **kwargs: Any) -> Any:
        _ = (self, args, kwargs)
        _unsupported(name)

    method.__name__ = name
    method.__qualname__ = f"{GitLabScmAdapter.__qualname__}.{name}"
    return method


class GitLabScmAdapter:
    """Second adapter declaring unsupported capabilities instead of emulating GitHub."""

    __slots__ = ("base_url", "token")

    def __init__(self, *, token: str, base_url: str) -> None:
        self.token = token
        self.base_url = base_url.rstrip("/")

    @property
    def capabilities(self) -> frozenset[ScmCapability]:
        return frozenset()

    async def aclose(self) -> None:
        return None


for _operation in protocol_operation_names():
    setattr(GitLabScmAdapter, _operation, _unsupported_method(_operation))
