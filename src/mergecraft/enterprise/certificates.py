"""Custom CA and certificate handling for enterprise deployments (#381).

Exports:
    CustomCAError: Raised when a CA file is missing or invalid.
    load_custom_ca: Load a PEM CA file and return an ssl.SSLContext.
"""

from __future__ import annotations

import ssl
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    "CustomCAError",
    "load_custom_ca",
]


class CustomCAError(Exception):
    """Raised when a CA certificate file is missing or cannot be loaded."""


def load_custom_ca(ca_path: Path) -> ssl.SSLContext:
    """Load a PEM-encoded CA certificate and return an :class:`ssl.SSLContext`.

    Args:
        ca_path: Path to the PEM CA file.

    Returns:
        An ``ssl.SSLContext`` with the CA loaded.

    Raises:
        CustomCAError: When the file is missing or is not a valid CA PEM.
    """
    if not ca_path.is_file():
        msg = f"CA certificate file not found: {ca_path}"
        raise CustomCAError(msg)

    ctx = ssl.create_default_context()
    try:
        ctx.load_verify_locations(cafile=str(ca_path))
    except ssl.SSLError as exc:
        msg = f"CA PEM could not be loaded as a certificate authority: {exc}"
        raise CustomCAError(msg) from exc

    # Verify at least one CA was loaded.
    if not ctx.get_ca_certs():
        msg = "PEM file did not contain any usable CA certificates"
        raise CustomCAError(msg)

    return ctx
