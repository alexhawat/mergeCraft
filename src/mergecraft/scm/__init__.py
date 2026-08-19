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
    resolve_scm_provider,
    validate_provider,
)

__all__ = [
    "ScmCapability",
    "ScmProvider",
    "UnsupportedScmCapability",
    "protocol_operation_names",
    "protocol_supports_github_operations",
    "resolve_scm_provider",
    "validate_provider",
]
