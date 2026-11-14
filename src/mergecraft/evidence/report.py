"""Aggregate recorded review metrics from local evidence packets.

Exports:
    summarize_packets: Read stored evidence and return a JSON-ready report.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

_MAX_PACKET_BYTES = 16 * 1024 * 1024
_MAX_TOTAL_BYTES = 512 * 1024 * 1024
_MAX_ENTRIES = 100_000
_MAX_PACKETS = 10_000
_PR_CHANGE = re.compile(r"[^/#\s]+/[^/#\s]+#[1-9][0-9]*")
_SCHEMA_VERSION = re.compile(r"1\.[0-9]+\.[0-9]+")


@dataclass(frozen=True)
class _Run:
    change_id: str
    tier: str | None
    verdict: str | None
    duration: float | None
    cost: float | None
    cost_availability: str
    cost_notes: tuple[str, ...]


def _is_packet_name(name: str) -> bool:
    return (
        name in {"run-packet.json", "merge-evidence-packet.json"}
        or name.endswith("-merge-evidence-packet.json")
        or (name.startswith("packet-") and name.endswith(".json"))
    )


def _raise_walk_error(error: OSError) -> None:
    raise error


def _packet_paths(inputs: Sequence[Path]) -> Iterator[Path]:
    entries = 0
    for path in inputs:
        mode = path.lstat().st_mode
        if not stat.S_ISDIR(mode):
            yield path
            continue
        for directory, dirs, files in os.walk(path, followlinks=False, onerror=_raise_walk_error):
            entries += len(dirs) + len(files)
            if entries > _MAX_ENTRIES:
                raise ValueError(f"Packet directories exceed {_MAX_ENTRIES:,} entries")
            for name in files:
                if _is_packet_name(name):
                    yield Path(directory) / name


def _read_packet(path: Path, remaining_bytes: int) -> bytes:
    # Nonblocking and no-follow protect against a special file or symlink
    # replacing a discovered filename before it is opened.
    limit = min(_MAX_PACKET_BYTES, remaining_bytes)
    with open(path, "rb", opener=_packet_opener) as packet:
        return packet.read(limit + 1)


def _packet_opener(path: str, flags: int) -> int:
    fd = os.open(path, flags | os.O_NONBLOCK | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > _MAX_PACKET_BYTES:
            raise OSError("Expected a regular packet file of at most 16 MiB")
    except BaseException:
        os.close(fd)
        raise
    return fd


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _measurement(value: Any) -> float | None:
    if type(value) not in (int, float):
        return None
    try:
        return float(value) if value >= 0 and math.isfinite(value) else None
    except OverflowError:
        return None


def _parse_packet(raw: bytes) -> tuple[str, _Run] | None:
    packet = json.loads(raw)
    if not isinstance(packet, dict):
        raise ValueError("Expected a packet object")
    version = packet.get("schema_version")
    change = packet.get("change_id")
    if (
        not isinstance(version, str)
        or not _SCHEMA_VERSION.fullmatch(version)
        or not isinstance(change, str)
        or not isinstance(packet.get("agent"), dict)
    ):
        raise ValueError("Expected mergeCraft evidence packet metadata")
    if not _PR_CHANGE.fullmatch(change):
        return None
    run_id = packet.get("run_id")
    has_id = isinstance(run_id, str) and bool(run_id)
    if has_id:
        key = f"run:{run_id}"
    else:
        # Older packets have no run ID. Ignore differences in JSON whitespace
        # or field order when identifying multiple copies of the same packet.
        canonical = json.dumps(packet, sort_keys=True, separators=(",", ":"))
        key = f"legacy:{hashlib.sha256(canonical.encode()).hexdigest()}"

    metrics = _mapping(packet.get("run_metrics"))
    verdict = _mapping(packet.get("decision")).get("verdict")
    phases = _mapping(metrics.get("phase_elapsed_s"))
    duration = _measurement(phases.get("agent"))
    # The old emitter used 0.0 for runs with no agent start time.
    if not has_id and duration == 0:
        duration = None
    cost = _measurement(metrics.get("recorded_cost_usd"))
    availability = metrics.get("cost_availability")
    if cost is None:
        availability = "unavailable"
    elif availability not in ("available", "partial"):
        availability = "partial"
    notes = metrics.get("cost_notes")
    qualifiers = (
        tuple(sorted({note for note in notes if isinstance(note, str)}))
        if isinstance(notes, list)
        else ()
    )
    tier = _mapping(packet.get("triage")).get("tier")
    return key, _Run(
        change.casefold(),
        tier if tier in ("skip", "lite", "full") else None,
        verdict if verdict in ("success", "failure", "neutral") else None,
        duration,
        cost,
        availability,
        qualifiers,
    )


def _summarize(runs: list[_Run]) -> dict[str, object]:
    reviews = [run for run in runs if run.tier not in {"skip", "lite"}]
    verdicts = Counter(run.verdict for run in reviews)
    cost_runs = [run for run in runs if run.tier != "skip"]
    costs = Counter(run.cost_availability for run in cost_runs)
    by_pr: dict[str, list[_Run]] = defaultdict(list)
    for run in runs:
        by_pr[run.change_id].append(run)
    complete_pr_costs = [
        math.fsum(run.cost for run in attempts if run.tier != "skip" and run.cost is not None)
        for attempts in by_pr.values()
        if any(run.tier != "skip" for run in attempts)
        and all(run.cost_availability == "available" for run in attempts if run.tier != "skip")
    ]
    times = [run.duration for run in runs if run.tier != "skip" and run.duration is not None]
    decisive = verdicts["success"] + verdicts["failure"]
    return {
        "metric_definitions": {
            "acceptance_rate": (
                "Review pass rate: structural success divided by success plus failure among observed full reviews. "
                "Human adoption of findings is unavailable from packets."
            ),
            "cost_per_pr_usd": (
                "Mean of recorded reviewer model costs per PR with complete observed review "
                "costs. Recorded amounts can include provider estimates and omit invoice costs."
            ),
            "time_to_review_seconds": (
                "Mean of observed reviewer agent phase durations in seconds. "
                "Time from PR creation to review is unavailable from packets."
            ),
        },
        "acceptance_rate": verdicts["success"] / decisive if decisive else None,
        "cost_per_pr_usd": _mean(complete_pr_costs),
        "time_to_review_seconds": _mean(times),
        "runs": len(runs),
        "pull_requests": len(by_pr),
        "full_review_runs": len(reviews),
        "skipped_runs": sum(run.tier == "skip" for run in runs),
        "lite_runs": sum(run.tier == "lite" for run in runs),
        "passed_runs": verdicts["success"],
        "failed_runs": verdicts["failure"],
        "neutral_runs": verdicts["neutral"],
        "unknown_verdict_runs": verdicts[None],
        "timed_runs": len(times),
        "costed_pull_requests": len(complete_pr_costs),
        "complete_cost_runs": costs["available"],
        "partial_cost_runs": costs["partial"],
        "unknown_cost_runs": costs["unavailable"],
        "recorded_cost_usd": (
            math.fsum(run.cost for run in cost_runs if run.cost is not None)
            if costs["available"] or costs["partial"]
            else None
        ),
        "cost_notes": sorted({note for run in cost_runs for note in run.cost_notes}),
    }


def _mean(values: list[float]) -> float | None:
    return math.fsum(value / len(values) for value in values) if values else None


def summarize_packets(inputs: Sequence[Path]) -> dict[str, object]:
    """Summarize the PR runs represented by packets under the supplied paths.

    Args:
        inputs: Packet files or directories of extracted packet artifacts.

    Returns:
        The metrics, their sample counts, and artifact coverage counts.
    """
    versions: dict[str, set[_Run]] = defaultdict(set)
    counts: Counter[str] = Counter()
    remaining_bytes = _MAX_TOTAL_BYTES
    for count, path in enumerate(_packet_paths(inputs), start=1):
        if count > _MAX_PACKETS:
            raise ValueError(f"Packet inputs exceed {_MAX_PACKETS:,} files")
        try:
            raw = _read_packet(path, remaining_bytes)
        except OSError:
            counts["invalid_packets"] += 1
            continue
        remaining_bytes -= len(raw)
        if remaining_bytes < 0:
            raise ValueError(f"Packet inputs exceed {_MAX_TOTAL_BYTES // 2**20} MiB")
        try:
            if len(raw) > _MAX_PACKET_BYTES:
                raise ValueError("Packet exceeds 16 MiB")
            parsed = _parse_packet(raw)
        except (ValueError, RecursionError):
            counts["invalid_packets"] += 1
            continue
        if parsed is None:
            counts["non_pr_packets"] += 1
            continue
        key, run = parsed
        observed = versions[key]
        if run in observed:
            counts["duplicate_packets"] += 1
        observed.add(run)

    runs = [next(iter(observed)) for observed in versions.values() if len(observed) == 1]
    return {
        **_summarize(runs),
        "invalid_packets": counts["invalid_packets"],
        "non_pr_packets": counts["non_pr_packets"],
        "duplicate_packets": counts["duplicate_packets"],
        "conflicting_runs": len(versions) - len(runs),
    }
