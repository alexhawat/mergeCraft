"""BR1.4 / BR5 — bounded SARIF archive reads (MCB-14, D11/D16)."""

from __future__ import annotations

import zipfile
from io import BytesIO

from mergecraft.ci.intelligence import (
    ARCHIVE_MAX_MEMBER_BYTES,
    ARCHIVE_MAX_TOTAL_BYTES,
    _sarif_documents,
)

_TRUNCATION_MARKER = "truncat"


def _build_sarif_zip(*, documents: list[tuple[str, bytes]]) -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, payload in documents:
            archive.writestr(name, payload)
    return buffer.getvalue()


def test_sarif_documents_share_the_same_caps() -> None:
    """MCB-14: SARIF extraction uses the same bounded-read controls as log archives."""
    max_member = ARCHIVE_MAX_MEMBER_BYTES
    max_total = ARCHIVE_MAX_TOTAL_BYTES

    oversized = b"{" + b'"runs":[]' + b"," + b'"x":"' + (b"S" * (max_member + 2048)) + b'"}'
    raw = _build_sarif_zip(
        documents=[
            ("results.sarif", oversized),
            ("second.sarif", b'{"version":"2.1.0","runs":[]}'),
        ]
    )
    documents = _sarif_documents(raw)
    joined = "\n".join(documents)
    assert len(joined.encode("utf-8")) <= max_total + 512
    assert _TRUNCATION_MARKER in joined.casefold()
