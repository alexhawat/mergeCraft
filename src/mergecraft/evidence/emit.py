"""I/O shell for the Merge Evidence Packet (W1.4 — convention 5).

The emitter is a thin wrapper around :func:`mergecraft.evidence.build.build_packet`
that writes the assembled packet to a run-local path and is ready to be
attached as a CI artifact. All I/O lives here; the builder is pure.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from mergecraft.evidence.packet import MergeEvidencePacket


def write_packet(
    packet: MergeEvidencePacket,
    *,
    output_path: Path,
) -> Path:
    """Write a :class:`MergeEvidencePacket` to ``output_path`` as pretty JSON.

    The output path is a run-local artifact (``output_path`` is typically
    inside the run's tempdir). Action surfaces, GitHub Actions uploads, and
    any other conveyor should treat this path as opaque — the schema is the
    contract, not the file location.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    serialized = packet.model_dump_json(indent=2, ensure_ascii=False)
    output_path.write_text(f"{serialized}\n", encoding="utf-8")
    logger.info(
        "wrote merge evidence packet to {} (schema_version={}, findings={}, checks={})",
        output_path,
        packet.schema_version,
        len(packet.findings),
        len(packet.deterministic_checks),
    )
    return output_path


__all__ = ["write_packet"]
