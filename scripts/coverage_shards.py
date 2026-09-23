#!/usr/bin/env python3
"""Create, validate, combine, and gate isolated coverage shards."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import subprocess
import sys
import tempfile
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from coverage import Coverage

if TYPE_CHECKING:
    from collections.abc import Generator

SCHEMA_VERSION = 1
MARKER = "not integration"
SPLITTING_ALGORITHM = "least_duration"
_FINGERPRINT_PATHS = (
    "src",
    "tests",
    "scripts",
    "evals",
    ".mergecraft",
    ".gitignore",
    ".python-version",
    "Makefile",
    "conftest.py",
    "pyproject.toml",
    "uv.lock",
    ".test_durations",
    ".coveragerc",
    "pytest.ini",
    "setup.cfg",
    "tox.ini",
)
_COMPATIBILITY_KEYS = (
    "schema_version",
    "source_head",
    "source_fingerprint",
    "coverage_config_hash",
    "versions",
    "selection",
    "splits",
)


class ShardError(RuntimeError):
    """Raised when a shard collection is incomplete or incompatible."""


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        msg = f"expected a positive integer, got {value!r}"
        raise argparse.ArgumentTypeError(msg) from exc
    if parsed <= 0:
        msg = f"expected a positive integer, got {value!r}"
        raise argparse.ArgumentTypeError(msg)
    return parsed


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise ShardError(result.stderr.strip() or f"git {' '.join(args)} failed")
    return result.stdout.strip()


def _source_fingerprint(root: Path) -> str:
    command = [
        "git",
        "ls-files",
        "-z",
        "-co",
        "--exclude-standard",
        "--",
        *_FINGERPRINT_PATHS,
    ]
    result = subprocess.run(command, cwd=root, capture_output=True, check=False)
    if result.returncode != 0:
        detail = result.stderr.decode(errors="replace").strip()
        raise ShardError(detail or "could not enumerate source inputs")
    digest = hashlib.sha256()
    encoded_paths = sorted(set(result.stdout.split(b"\0")) - {b""})
    for encoded_relative in encoded_paths:
        relative = os.fsdecode(encoded_relative)
        path = root / relative
        if not path.is_file():
            continue
        digest.update(encoded_relative)
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _version(distribution: str) -> str:
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError as exc:
        raise ShardError(f"required package is unavailable: {distribution}") from exc


def _metadata(root: Path, *, splits: int, jobs: str, seed: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "source_head": _git(root, "rev-parse", "HEAD"),
        "source_fingerprint": _source_fingerprint(root),
        "coverage_config_hash": _sha256(root / "pyproject.toml"),
        "versions": {
            "python": ".".join(str(part) for part in sys.version_info[:3]),
            "coverage": _version("coverage"),
            "pytest": _version("pytest"),
            "pytest_cov": _version("pytest-cov"),
            "pytest_split": _version("pytest-split"),
            "pytest_xdist": _version("pytest-xdist"),
        },
        "selection": {
            "root": "tests",
            "marker": MARKER,
            "seed": seed,
            "splitting_algorithm": SPLITTING_ALGORITHM,
            "xdist_jobs": jobs,
        },
        "splits": splits,
    }


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("mergecraft coverage shards")
    group.addoption("--mergecraft-nodeids", type=Path, default=None)


@pytest.hookimpl(hookwrapper=True, trylast=True)
def pytest_collection_modifyitems(
    config: pytest.Config,
    items: list[pytest.Item],
) -> Generator[None, None, None]:
    yield
    config._mergecraft_coverage_nodeids = sorted(item.nodeid for item in items)  # type: ignore[attr-defined]


def pytest_xdist_node_collection_finished(node: Any, ids: list[str]) -> None:
    """Record one agreed post-split collection on the xdist controller."""
    config = node.config
    selected = sorted(ids)
    existing = getattr(config, "_mergecraft_coverage_nodeids", None)
    if existing is not None and existing != selected:
        raise pytest.UsageError("xdist workers selected different coverage shard node IDs")
    config._mergecraft_coverage_nodeids = selected


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    destination = session.config.getoption("--mergecraft-nodeids")
    if (
        destination is None
        or exitstatus not in {pytest.ExitCode.OK, pytest.ExitCode.NO_TESTS_COLLECTED}
        or hasattr(session.config, "workerinput")
        or not hasattr(session.config, "_mergecraft_coverage_nodeids")
    ):
        return
    nodeids = session.config._mergecraft_coverage_nodeids
    _atomic_json(destination, nodeids)


def _pytest_command(
    *,
    nodeids_path: Path,
    seed: str,
    jobs: str,
    splits: int | None = None,
    group: int | None = None,
    coverage: bool,
    collect_only: bool = False,
) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "pytest",
        "tests",
        "-q",
        "--tb=short",
        "--strict-markers",
        "-m",
        MARKER,
        f"--randomly-seed={seed}",
        "-p",
        "scripts.coverage_shards",
        "--mergecraft-nodeids",
        str(nodeids_path),
    ]
    if jobs != "0":
        command.extend(["-n", jobs])
    if splits is not None and group is not None:
        command.extend(
            [
                "--splits",
                str(splits),
                "--group",
                str(group),
                "--splitting-algorithm",
                SPLITTING_ALGORITHM,
            ]
        )
    if coverage:
        command.extend(
            [
                "--cov=mergecraft",
                "--cov-branch",
                "--cov-report=",
                "--cov-fail-under=0",
                "-rX",
            ]
        )
    if collect_only:
        command.append("--collect-only")
    return command


def _run(
    command: list[str],
    *,
    root: Path,
    env: dict[str, str] | None = None,
    allowed: frozenset[int] = frozenset({0}),
) -> None:
    result = subprocess.run(command, cwd=root, env=env, check=False)
    if result.returncode not in allowed:
        raise ShardError(f"command failed ({result.returncode}): {' '.join(command)}")


def measure_shard(
    root: Path,
    run_dir: Path,
    *,
    splits: int,
    group: int,
    jobs: str,
    seed: str,
) -> Path:
    if group > splits:
        raise ShardError(f"group must be between 1 and {splits}, got {group}")
    group_dir = run_dir / f"group-{group}"
    if group_dir.exists():
        raise ShardError(f"shard output already exists: {group_dir}")
    group_dir.mkdir(parents=True)
    raw_path = group_dir / f".coverage.group-{group}"
    nodeids_path = group_dir / "nodeids.json"
    manifest_path = group_dir / "manifest.json"
    environment = os.environ.copy()
    environment["COVERAGE_FILE"] = str(raw_path)
    metadata_before = _metadata(root, splits=splits, jobs=jobs, seed=seed)
    _run(
        _pytest_command(
            nodeids_path=nodeids_path,
            seed=seed,
            jobs=jobs,
            splits=splits,
            group=group,
            coverage=True,
        ),
        root=root,
        env=environment,
        allowed=frozenset({0, int(pytest.ExitCode.NO_TESTS_COLLECTED)}),
    )
    if (
        nodeids_path.is_file()
        and json.loads(nodeids_path.read_text(encoding="utf-8")) == []
        and not raw_path.is_file()
    ):
        Coverage(
            data_file=str(raw_path),
            config_file=str(root / "pyproject.toml"),
        ).save()
    if not raw_path.is_file() or not nodeids_path.is_file():
        raise ShardError(f"successful shard {group} did not produce raw data and node IDs")
    metadata_after = _metadata(root, splits=splits, jobs=jobs, seed=seed)
    if metadata_after != metadata_before:
        raise ShardError("source or coverage inputs changed while the shard was running")
    nodeids = json.loads(nodeids_path.read_text(encoding="utf-8"))
    if not isinstance(nodeids, list) or any(not isinstance(item, str) for item in nodeids):
        raise ShardError(f"invalid node ID record for group {group}")
    manifest = metadata_before
    manifest.update(
        {
            "group": group,
            "raw_path": str(raw_path.resolve()),
            "raw_sha256": _sha256(raw_path),
            "nodeids": nodeids,
            "nodeids_sha256": hashlib.sha256("\0".join(nodeids).encode()).hexdigest(),
        }
    )
    _atomic_json(manifest_path, manifest)
    return manifest_path


def _load_manifests(run_dir: Path, splits: int) -> list[dict[str, Any]]:
    paths = sorted(run_dir.glob("group-*/manifest.json"))
    manifests: list[dict[str, Any]] = []
    for path in paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ShardError(f"invalid manifest {path}: {exc}") from exc
        if not isinstance(payload, dict):
            raise ShardError(f"invalid manifest object: {path}")
        manifests.append(payload)
    groups: list[int] = []
    for manifest in manifests:
        group = manifest.get("group")
        if not isinstance(group, int) or isinstance(group, bool):
            raise ShardError(f"manifest group identity must be an integer: {group!r}")
        groups.append(group)
    expected = set(range(1, splits + 1))
    actual = set(groups)
    if len(groups) != len(actual):
        raise ShardError(f"duplicate shard groups: {groups}")
    if actual != expected:
        raise ShardError(f"shard groups must be exactly {sorted(expected)}, got {sorted(actual)}")
    return manifests


def _collect_nodeids(root: Path, *, seed: str, jobs: str, destination: Path) -> list[str]:
    destination.unlink(missing_ok=True)
    _run(
        _pytest_command(
            nodeids_path=destination,
            seed=seed,
            jobs=jobs,
            coverage=False,
            collect_only=True,
        ),
        root=root,
        allowed=frozenset({0, int(pytest.ExitCode.NO_TESTS_COLLECTED)}),
    )
    nodeids = json.loads(destination.read_text(encoding="utf-8"))
    if not isinstance(nodeids, list) or any(not isinstance(item, str) for item in nodeids):
        raise ShardError("complete collection produced invalid node IDs")
    return nodeids


def _assert_metadata_current(
    root: Path,
    manifest: dict[str, Any],
    *,
    splits: int,
    stage: str,
) -> None:
    selection = manifest.get("selection")
    if not isinstance(selection, dict):
        raise ShardError("manifest selection metadata is missing or invalid")
    current = _metadata(
        root,
        splits=splits,
        jobs=str(selection.get("xdist_jobs", "")),
        seed=str(selection.get("seed", "")),
    )
    for key in _COMPATIBILITY_KEYS:
        if manifest.get(key) != current[key]:
            raise ShardError(f"source or coverage inputs changed {stage}: {key}")


def validate_manifests(
    root: Path,
    run_dir: Path,
    *,
    splits: int,
    collect: bool = True,
) -> list[dict[str, Any]]:
    manifests = _load_manifests(run_dir, splits)
    expected_meta = _metadata(
        root,
        splits=splits,
        jobs=str(manifests[0]["selection"]["xdist_jobs"]),
        seed=str(manifests[0]["selection"]["seed"]),
    )
    first = manifests[0]
    for key in _COMPATIBILITY_KEYS:
        if first.get(key) != expected_meta[key]:
            raise ShardError(f"manifest metadata is stale or incompatible: {key}")
    raw_paths: set[Path] = set()
    seen_nodeids: set[str] = set()
    for manifest in manifests:
        for key in _COMPATIBILITY_KEYS:
            if manifest.get(key) != first.get(key):
                raise ShardError(f"mismatched shard metadata: {key}")
        raw_path = Path(str(manifest.get("raw_path", ""))).resolve()
        try:
            raw_path.relative_to(run_dir.resolve())
        except ValueError as exc:
            raise ShardError(f"raw coverage path escapes run directory: {raw_path}") from exc
        if raw_path in raw_paths:
            raise ShardError(f"duplicate raw coverage path: {raw_path}")
        raw_paths.add(raw_path)
        if not raw_path.is_file() or _sha256(raw_path) != manifest.get("raw_sha256"):
            raise ShardError(f"raw coverage data missing or changed: {raw_path}")
        nodeids = manifest.get("nodeids")
        if not isinstance(nodeids, list) or any(not isinstance(item, str) for item in nodeids):
            raise ShardError(f"invalid node IDs for group {manifest.get('group')}")
        if len(nodeids) != len(set(nodeids)):
            raise ShardError(f"duplicate node IDs within group {manifest.get('group')}")
        expected_hash = hashlib.sha256("\0".join(nodeids).encode()).hexdigest()
        if expected_hash != manifest.get("nodeids_sha256"):
            raise ShardError(f"node ID hash mismatch for group {manifest.get('group')}")
        overlap = seen_nodeids.intersection(nodeids)
        if overlap:
            raise ShardError(f"overlapping shard node IDs: {sorted(overlap)[:3]}")
        seen_nodeids.update(nodeids)
    if collect:
        selection = first["selection"]
        collected_nodeids = _collect_nodeids(
            root,
            seed=str(selection["seed"]),
            jobs=str(selection["xdist_jobs"]),
            destination=run_dir / "complete-nodeids.json",
        )
        _assert_metadata_current(
            root,
            first,
            splits=splits,
            stage="during complete test collection",
        )
        expected_nodeids = set(collected_nodeids)
        if seen_nodeids != expected_nodeids:
            missing = sorted(expected_nodeids - seen_nodeids)
            extra = sorted(seen_nodeids - expected_nodeids)
            raise ShardError(
                f"shard node IDs are incomplete (missing={missing[:3]}, extra={extra[:3]})"
            )
        if len(expected_nodeids) >= splits and any(
            not manifest["nodeids"] for manifest in manifests
        ):
            raise ShardError("empty shard is invalid when the collection has at least N tests")
    _assert_metadata_current(
        root,
        first,
        splits=splits,
        stage="during manifest validation",
    )
    return manifests


def combine_and_gate(root: Path, run_dir: Path, *, splits: int) -> None:
    manifests = validate_manifests(root, run_dir, splits=splits)
    first = manifests[0]
    _assert_metadata_current(root, first, splits=splits, stage="before coverage combine")
    combined_dir = run_dir / "combined"
    combined_dir.mkdir(exist_ok=True)
    combined_data = combined_dir / ".coverage"
    combined_data.unlink(missing_ok=True)
    environment = os.environ.copy()
    environment["COVERAGE_FILE"] = str(combined_data)
    raw_paths = [str(Path(str(item["raw_path"]))) for item in manifests]
    _run(
        [sys.executable, "-m", "coverage", "combine", "--keep", *raw_paths],
        root=root,
        env=environment,
    )
    _assert_metadata_current(root, first, splits=splits, stage="during coverage combine")
    report = root / "coverage.json"
    report.unlink(missing_ok=True)
    _run(
        [sys.executable, "-m", "coverage", "json", "-o", str(report)],
        root=root,
        env=environment,
    )
    _assert_metadata_current(root, first, splits=splits, stage="during coverage report")
    _run([sys.executable, "scripts/check_coverage_ratchet.py", str(report)], root=root)
    _assert_metadata_current(root, first, splits=splits, stage="during coverage ratchet check")
    _run([sys.executable, "scripts/check_coverage_floors.py", str(report)], root=root)
    _assert_metadata_current(root, first, splits=splits, stage="during coverage floors check")


def _bounded_jobs(jobs: str, *, splits: int) -> tuple[int, str]:
    cpu_limit = max(1, os.cpu_count() or 1)
    group_workers = min(splits, cpu_limit)
    if jobs == "0":
        return group_workers, "0"
    per_group_limit = max(1, cpu_limit // group_workers)
    if jobs == "auto":
        return group_workers, str(per_group_limit)
    try:
        requested = int(jobs)
    except ValueError as exc:
        raise ShardError(f"xdist jobs must be 'auto', 0, or a positive integer: {jobs!r}") from exc
    if requested <= 0:
        raise ShardError(f"xdist jobs must be 'auto', 0, or a positive integer: {jobs!r}")
    return group_workers, str(min(requested, per_group_limit))


def orchestrate(root: Path, run_dir: Path, *, splits: int, jobs: str, seed: str) -> None:
    run_dir.mkdir(parents=True, exist_ok=False)
    failures: list[str] = []
    group_workers, child_jobs = _bounded_jobs(jobs, splits=splits)

    def _one(group: int) -> None:
        log_path = run_dir / f"group-{group}.log"
        command = [
            sys.executable,
            str(Path(__file__).resolve()),
            "measure",
            "--root",
            str(root),
            "--run-dir",
            str(run_dir),
            "--splits",
            str(splits),
            "--group",
            str(group),
            "--jobs",
            child_jobs,
            "--seed",
            seed,
        ]
        with log_path.open("w", encoding="utf-8") as log:
            result = subprocess.run(
                command, cwd=root, stdout=log, stderr=subprocess.STDOUT, check=False
            )
        if result.returncode != 0:
            raise ShardError(f"group {group} failed; see {log_path}")

    with ThreadPoolExecutor(max_workers=group_workers) as executor:
        futures = {executor.submit(_one, group): group for group in range(1, splits + 1)}
        for future in as_completed(futures):
            try:
                future.result()
            except Exception as exc:
                failures.append(str(exc))
    if failures:
        raise ShardError("; ".join(failures))
    combine_and_gate(root, run_dir, splits=splits)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("measure", "combine", "orchestrate"):
        subparser = subparsers.add_parser(name)
        subparser.add_argument("--root", type=Path, default=Path.cwd())
        subparser.add_argument("--run-dir", type=Path, required=name == "combine")
        subparser.add_argument("--splits", type=_positive_int, required=True)
        if name in {"measure", "orchestrate"}:
            subparser.add_argument("--jobs", default="0")
            subparser.add_argument("--seed", default="424242")
        if name == "measure":
            subparser.add_argument("--group", type=_positive_int, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root = args.root.resolve()
    try:
        if args.command == "measure":
            run_dir = args.run_dir
            if run_dir is None:
                base = root / ".coverage-shards"
                base.mkdir(exist_ok=True)
                run_dir = Path(tempfile.mkdtemp(prefix="run-", dir=base))
            else:
                run_dir = run_dir.resolve()
                run_dir.mkdir(parents=True, exist_ok=True)
            print(f"coverage shard artifact directory: {run_dir}")
            measure_shard(
                root,
                run_dir,
                splits=args.splits,
                group=args.group,
                jobs=args.jobs,
                seed=args.seed,
            )
        elif args.command == "combine":
            combine_and_gate(root, args.run_dir.resolve(), splits=args.splits)
        else:
            run_dir = args.run_dir
            if run_dir is None:
                base = root / ".coverage-shards"
                base.mkdir(exist_ok=True)
                run_dir = base / f"run-{uuid.uuid4().hex}"
            else:
                run_dir = run_dir.resolve()
            print(f"coverage shard artifact directory: {run_dir}")
            orchestrate(
                root,
                run_dir,
                splits=args.splits,
                jobs=args.jobs,
                seed=args.seed,
            )
    except (OSError, KeyError, ShardError, json.JSONDecodeError) as exc:
        print(f"coverage shard error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
