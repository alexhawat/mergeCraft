"""I/O shell for the Merge Evidence Packet (W1.4 — convention 5).

The emitter is a thin wrapper around :func:`mergecraft.evidence.build.build_packet`
that writes the assembled packet to a run-local path and is ready to be
attached as a CI artifact. All I/O lives here; the builder is pure.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from loguru import logger

from mergecraft.evidence.build import build_packet

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


def write_packet_from_sources(
    *,
    output_path: Path,
    **build_kwargs: object,
) -> Path:
    """Compose a packet from sources and write it to ``output_path``.

    Convenience wrapper that ties the pure builder to the I/O shell —
    callers should prefer this when the source data is already in hand
    and only the artifact is needed.
    """
    packet = build_packet(**build_kwargs)  # type: ignore[arg-type]  # — build_kwargs matches build_packet signature; TypedDict ** spread not fully supported by mypy
    return write_packet(packet, output_path=output_path)


def load_packet(path: Path) -> dict[str, Any]:
    """Load a packet from a JSON file and return it as a dict.

    Pure-deserialisation; re-validating against ``MergeEvidencePacket`` is
    the caller's job (the emitter does not validate the round-trip — the
    separate tests at ``tests/evidence/test_packet_round_trip.py`` do).
    """
    return cast(  # json.loads returns Any; packet files are always JSON objects
        "dict[str, Any]", json.loads(Path(path).read_text(encoding="utf-8"))
    )


__all__ = ["load_packet", "write_packet", "write_packet_from_sources"]
