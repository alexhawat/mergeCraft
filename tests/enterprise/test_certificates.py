"""W7.1 — custom CA / certificate handling (#381).

Intended public API (W7.2): ``mergecraft.enterprise.certificates``.
"""

from __future__ import annotations

from pathlib import Path
from ssl import SSLContext

import pytest

_W72 = pytest.mark.xfail(
    reason="green after W7.2: custom CA path (#381)",
    strict=False,
)

_BOGUS_PEM = "-----BEGIN CERTIFICATE-----\nnot-a-real-cert\n-----END CERTIFICATE-----\n"


@_W72
def test_load_custom_ca_missing_file_raises(tmp_path: Path) -> None:
    """Error: a missing CA file raises CustomCAError naming the certificate/CA."""
    from mergecraft.enterprise.certificates import CustomCAError, load_custom_ca

    missing = tmp_path / "missing-ca.pem"
    with pytest.raises(CustomCAError, match=r"CA|certificate"):
        load_custom_ca(missing)


@_W72
def test_load_custom_ca_rejects_invalid_pem(tmp_path: Path) -> None:
    """Error: a file that is not a usable CA PEM raises CustomCAError."""
    from mergecraft.enterprise.certificates import CustomCAError, load_custom_ca

    pem = tmp_path / "junk.pem"
    pem.write_text(_BOGUS_PEM, encoding="utf-8")
    with pytest.raises(CustomCAError, match=r"CA|certificate|PEM"):
        load_custom_ca(pem)


def _write_self_signed_ca(path: Path) -> None:
    """Write a throwaway self-signed CA PEM via openssl (keyless, local-only)."""
    import subprocess

    key = path.with_suffix(".key")
    completed = subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-keyout",
            str(key),
            "-out",
            str(path),
            "-days",
            "1",
            "-nodes",
            "-subj",
            "/CN=mergecraft-test-ca",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0 or not path.is_file():
        pytest.fail(f"openssl failed to mint a test CA: {completed.stderr}")


@_W72
def test_load_custom_ca_returns_ssl_context(tmp_path: Path) -> None:
    """Happy: a valid CA PEM returns an ssl.SSLContext."""
    from mergecraft.enterprise.certificates import load_custom_ca

    pem = tmp_path / "ca.pem"
    _write_self_signed_ca(pem)
    context = load_custom_ca(pem)
    assert isinstance(context, SSLContext)
