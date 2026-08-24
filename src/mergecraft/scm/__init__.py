"""SCM provider abstraction (DG9 / D10).

Production call sites bind :class:`~mergecraft.scm.protocol.ScmProvider` on
:class:`~mergecraft.mcp.context.ToolContext.scm`.
"""

from mergecraft.scm.errors import UnsupportedScmCapability
from mergecraft.scm.protocol import (
    ScmCapability,
    ScmProvider,
    protocol_operation_names,
    protocol_supports_github_operations,
    validate_provider,
)
from mergecraft.scm.types import ListedItems

__all__ = [
    "ListedItems",
    "ScmCapability",
    "ScmProvider",
    "UnsupportedScmCapability",
    "protocol_operation_names",
    "protocol_supports_github_operations",
    "validate_provider",
]
