"""Coverage shard isolation and completeness contracts (#785)."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from coverage import Coverage

from tests.ci.workflow_support import REPO_ROOT, read_text


def _load_module() -> Any:
    path = REPO_ROOT / "scripts" / "coverage_shards.py"
    spec = importlib.util.spec_from_file_location("coverage_shards_785", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_fake_uv(path: Path) -> Path:
    path.write_text(
        "#!/bin/sh\n"
        'printf \'%s\\n\' "$*" >> "$MERGECRAFT_FAKE_UV_LOG"\n'
        'case "$*" in\n'
        "  *check_coverage_ratchet.py*) exit ${RATCHET_RC:-0} ;;\n"
        "  *check_coverage_floors.py*) exit ${FLOORS_RC:-0} ;;\n"
        "esac\n"
        "exit 0\n",
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


def test_make_exposes_explicit_combine_gate() -> None:
    result = subprocess.run(
        ["make", "-n", "coverage-combine-gate"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "coverage_shards.py combine" in result.stdout


def test_ci_keeps_sharding_inside_one_coverage_gate_stage() -> None:
    makefile = read_text("Makefile")
    steps = next(line for line in makefile.splitlines() if line.startswith("CI_STEPS :="))

    assert steps.split().count("coverage-gate") == 1
    assert "coverage-measure" not in steps
    assert "coverage-combine-gate" not in steps


def test_partial_coverage_measure_has_no_floor_commands() -> None:
    result = subprocess.run(
        ["make", "-n", "coverage-measure"],
        cwd=REPO_ROOT,
        env={
            "PATH": "/usr/bin:/bin",
            "MERGECRAFT_TEST_SPLITS": "2",
            "MERGECRAFT_TEST_GROUP": "1",
            "MERGECRAFT_COVERAGE_RUN_DIR": "/tmp/coverage-shard-contract",
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "coverage_shards.py measure" in result.stdout
    assert "check_coverage_ratchet.py" not in result.stdout
    assert "check_coverage_floors.py" not in result.stdout


def test_default_gate_stops_when_measurement_fails(tmp_path: Path) -> None:
    (tmp_path / "Makefile").write_text(read_text("Makefile"), encoding="utf-8")
    log = tmp_path / "uv.log"
    fake_uv = _write_fake_uv(tmp_path / "uv")
    result = subprocess.run(
        [
            "make",
            "coverage-gate",
            "PYTEST=/usr/bin/false",
            f"UV={fake_uv}",
        ],
        cwd=tmp_path,
        env={**os.environ, "MERGECRAFT_FAKE_UV_LOG": str(log)},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert not log.exists()


def test_default_gate_stops_before_floors_when_ratchet_fails(tmp_path: Path) -> None:
    (tmp_path / "Makefile").write_text(read_text("Makefile"), encoding="utf-8")
    log = tmp_path / "uv.log"
    fake_uv = _write_fake_uv(tmp_path / "uv")
    result = subprocess.run(
        ["make", "coverage-gate", "PYTEST=/usr/bin/true", f"UV={fake_uv}"],
        cwd=tmp_path,
        env={
            **os.environ,
            "MERGECRAFT_FAKE_UV_LOG": str(log),
            "RATCHET_RC": "1",
            "FLOORS_RC": "0",
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    commands = log.read_text(encoding="utf-8")
    assert "check_coverage_ratchet.py" in commands
    assert "check_coverage_floors.py" not in commands


@pytest.mark.parametrize("value", ["0", "-1", "nope", "1.5"])
def test_split_counts_must_be_positive_integers(value: str) -> None:
    module = _load_module()

    with pytest.raises(SystemExit):
        module.main(["combine", "--run-dir", "/tmp/run", "--splits", value])


def test_group_must_not_exceed_split_count(tmp_path: Path) -> None:
    module = _load_module()

    with pytest.raises(module.ShardError, match="between 1 and 2"):
        module.measure_shard(
            REPO_ROOT,
            tmp_path,
            splits=2,
            group=3,
            jobs="0",
            seed="424242",
        )


@pytest.mark.parametrize(
    "arguments",
    [
        ["measure", "--splits", "2"],
        ["measure", "--group", "1"],
        ["combine", "--run-dir", "/tmp/run"],
    ],
)
def test_missing_split_or_group_values_are_rejected(arguments: list[str]) -> None:
    module = _load_module()

    with pytest.raises(SystemExit):
        module.main(arguments)


def test_coverage_gate_rejects_one_partial_group() -> None:
    result = subprocess.run(
        ["make", "coverage-gate"],
        cwd=REPO_ROOT,
        env={
            **os.environ,
            "MERGECRAFT_TEST_SPLITS": "2",
            "MERGECRAFT_TEST_GROUP": "1",
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "refuses a partial shard" in result.stderr


def _manifest(
    module: Any,
    run_dir: Path,
    *,
    group: int,
    splits: int = 2,
    nodeids: list[str] | None = None,
) -> dict[str, Any]:
    group_dir = run_dir / f"group-{group}"
    group_dir.mkdir(parents=True, exist_ok=True)
    raw = group_dir / f".coverage.group-{group}"
    raw.write_bytes(f"raw-{group}".encode())
    selected = nodeids if nodeids is not None else [f"tests/test_demo.py::test_{group}"]
    manifest = module._metadata(REPO_ROOT, splits=splits, jobs="0", seed="424242")
    manifest.update(
        {
            "group": group,
            "raw_path": str(raw),
            "raw_sha256": hashlib.sha256(raw.read_bytes()).hexdigest(),
            "nodeids": selected,
            "nodeids_sha256": hashlib.sha256("\0".join(selected).encode()).hexdigest(),
        }
    )
    (group_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return manifest


@pytest.mark.parametrize("mode", ["missing", "extra", "duplicate"])
def test_manifest_groups_must_be_exactly_once(tmp_path: Path, mode: str) -> None:
    module = _load_module()
    _manifest(module, tmp_path, group=1)
    if mode == "extra":
        _manifest(module, tmp_path, group=3)
    elif mode == "duplicate":
        duplicate = _manifest(module, tmp_path, group=2)
        duplicate["group"] = 1
        (tmp_path / "group-2" / "manifest.json").write_text(json.dumps(duplicate), encoding="utf-8")

    with pytest.raises(module.ShardError):
        module.validate_manifests(REPO_ROOT, tmp_path, splits=2, collect=False)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("source_head", "mismatched shard metadata"),
        ("raw_sha256", "raw coverage data missing or changed"),
        ("nodeids_sha256", "node ID hash mismatch"),
    ],
)
def test_manifest_mismatch_or_tampering_fails_closed(
    tmp_path: Path,
    mutation: str,
    message: str,
) -> None:
    module = _load_module()
    _manifest(module, tmp_path, group=1)
    second = _manifest(module, tmp_path, group=2)
    second[mutation] = "tampered"
    (tmp_path / "group-2" / "manifest.json").write_text(json.dumps(second), encoding="utf-8")

    with pytest.raises(module.ShardError, match=message):
        module.validate_manifests(REPO_ROOT, tmp_path, splits=2, collect=False)


def test_overlap_and_incomplete_union_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    _manifest(module, tmp_path, group=1, nodeids=["test_a"])
    _manifest(module, tmp_path, group=2, nodeids=["test_b"])
    monkeypatch.setattr(module, "_collect_nodeids", lambda *args, **kwargs: ["test_a", "test_c"])

    with pytest.raises(module.ShardError, match="incomplete"):
        module.validate_manifests(REPO_ROOT, tmp_path, splits=2)

    second_path = tmp_path / "group-2" / "manifest.json"
    second = json.loads(second_path.read_text(encoding="utf-8"))
    second["nodeids"] = ["test_a"]
    second["nodeids_sha256"] = hashlib.sha256(b"test_a").hexdigest()
    second_path.write_text(json.dumps(second), encoding="utf-8")
    with pytest.raises(module.ShardError, match="overlapping"):
        module.validate_manifests(REPO_ROOT, tmp_path, splits=2, collect=False)


def test_duplicate_nodeids_inside_one_manifest_fail_closed(tmp_path: Path) -> None:
    module = _load_module()
    first = _manifest(module, tmp_path, group=1, nodeids=["test_a", "test_a"])
    _manifest(module, tmp_path, group=2, nodeids=["test_b"])
    first["nodeids_sha256"] = hashlib.sha256(b"test_a\0test_a").hexdigest()
    (tmp_path / "group-1" / "manifest.json").write_text(json.dumps(first), encoding="utf-8")

    with pytest.raises(module.ShardError, match="duplicate node IDs within group 1"):
        module.validate_manifests(REPO_ROOT, tmp_path, splits=2, collect=False)


def test_identical_raw_hashes_are_allowed_for_distinct_groups(tmp_path: Path) -> None:
    module = _load_module()
    first = _manifest(module, tmp_path, group=1)
    second = _manifest(module, tmp_path, group=2)
    second_raw = Path(second["raw_path"])
    second_raw.write_bytes(Path(first["raw_path"]).read_bytes())
    second["raw_sha256"] = hashlib.sha256(second_raw.read_bytes()).hexdigest()
    (tmp_path / "group-2" / "manifest.json").write_text(json.dumps(second), encoding="utf-8")

    manifests = module.validate_manifests(REPO_ROOT, tmp_path, splits=2, collect=False)

    assert len(manifests) == 2


def test_atomic_writers_do_not_replace_sibling_artifacts(tmp_path: Path) -> None:
    module = _load_module()
    paths = [tmp_path / f"group-{group}" / "manifest.json" for group in range(1, 5)]
    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(lambda path: module._atomic_json(path, {"path": str(path)}), paths))

    assert [json.loads(path.read_text(encoding="utf-8"))["path"] for path in paths] == [
        str(path) for path in paths
    ]


def test_source_fingerprint_handles_spaces_and_unicode(tmp_path: Path) -> None:
    module = _load_module()
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    source = tmp_path / "src" / "sp ace" / "ünicode.py"
    source.parent.mkdir(parents=True)
    source.write_text("VALUE = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", str(source.relative_to(tmp_path))], cwd=tmp_path, check=True)

    before = module._source_fingerprint(tmp_path)
    source.write_text("VALUE = 2\n", encoding="utf-8")

    assert module._source_fingerprint(tmp_path) != before


@pytest.mark.parametrize(("jobs", "cpu_count"), [("auto", 8), ("20", 8), ("0", 8)])
def test_orchestration_bounds_group_and_xdist_workers(
    monkeypatch: pytest.MonkeyPatch,
    jobs: str,
    cpu_count: int,
) -> None:
    module = _load_module()
    monkeypatch.setattr(module.os, "cpu_count", lambda: cpu_count)

    group_workers, child_jobs = module._bounded_jobs(jobs, splits=4)

    assert group_workers <= cpu_count
    if child_jobs != "0":
        assert group_workers * int(child_jobs) <= cpu_count


def test_source_change_during_measurement_leaves_no_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    metadata = {"source_fingerprint": "before"}
    monkeypatch.setattr(
        module,
        "_metadata",
        lambda *args, **kwargs: (
            metadata if not (tmp_path / "ran").exists() else {"source_fingerprint": "after"}
        ),
    )

    def fake_run(
        command: list[str],
        *,
        root: Path,
        env: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> None:
        assert env is not None
        Path(env["COVERAGE_FILE"]).write_bytes(b"raw")
        nodeids = Path(command[command.index("--mergecraft-nodeids") + 1])
        nodeids.write_text('["test_a"]', encoding="utf-8")
        (tmp_path / "ran").touch()

    monkeypatch.setattr(module, "_run", fake_run)

    with pytest.raises(module.ShardError, match="changed while"):
        module.measure_shard(
            REPO_ROOT,
            tmp_path / "run",
            splits=2,
            group=1,
            jobs="0",
            seed="424242",
        )
    assert not (tmp_path / "run" / "group-1" / "manifest.json").exists()


def test_empty_group_is_allowed_only_when_collection_is_smaller_than_splits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    _manifest(module, tmp_path, group=1, nodeids=["test_a"])
    _manifest(module, tmp_path, group=2, nodeids=[])
    monkeypatch.setattr(module, "_collect_nodeids", lambda *args, **kwargs: ["test_a"])

    assert len(module.validate_manifests(REPO_ROOT, tmp_path, splits=2)) == 2

    monkeypatch.setattr(
        module,
        "_collect_nodeids",
        lambda *args, **kwargs: ["test_a", "test_b"],
    )
    with pytest.raises(module.ShardError):
        module.validate_manifests(REPO_ROOT, tmp_path, splits=2)


def test_combine_uses_only_manifested_raw_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    raw_paths = []
    manifests = []
    for group in (1, 2):
        raw = tmp_path / f"group-{group}" / f".coverage.group-{group}"
        raw.parent.mkdir()
        raw.write_bytes(b"raw")
        raw_paths.append(str(raw))
        manifests.append({"raw_path": str(raw)})
    extra = tmp_path / "group-1" / ".coverage.unmanifested"
    extra.write_bytes(b"must-not-combine")
    monkeypatch.setattr(module, "validate_manifests", lambda *args, **kwargs: manifests)
    commands: list[list[str]] = []
    monkeypatch.setattr(module, "_run", lambda command, **kwargs: commands.append(command))

    module.combine_and_gate(REPO_ROOT, tmp_path, splits=2)

    combine = commands[0]
    assert all(path in combine for path in raw_paths)
    assert str(extra) not in combine


def test_xdist_split_reports_match_unsharded_real_branch_data(tmp_path: Path) -> None:
    package = tmp_path / "fixturepkg"
    package.mkdir()
    (package / "__init__.py").write_text(
        "def choose(value: int) -> int:\n    if value % 2:\n        return 1\n    return 0\n",
        encoding="utf-8",
    )
    suite = tmp_path / "test_fixture.py"
    suite.write_text(
        "import pytest\n"
        "from fixturepkg import choose\n\n"
        "@pytest.mark.parametrize('value', range(6))\n"
        "def test_value(value):\n"
        "    assert choose(value) in {0, 1}\n",
        encoding="utf-8",
    )
    environment = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join((str(tmp_path), str(REPO_ROOT / "src"))),
    }

    def run_measurement(
        raw: Path,
        nodeids: Path,
        *,
        group: int | None = None,
    ) -> set[str]:
        command = [
            sys.executable,
            "-m",
            "pytest",
            str(suite),
            "-q",
            "-n",
            "2",
            "--randomly-seed=424242",
            "--cov=fixturepkg",
            "--cov-branch",
            "--cov-config=/dev/null",
            "--cov-report=",
            "--cov-fail-under=0",
            "-p",
            "scripts.coverage_shards",
            "--mergecraft-nodeids",
            str(nodeids),
        ]
        if group is not None:
            command.extend(
                [
                    "--splits",
                    "2",
                    "--group",
                    str(group),
                    "--splitting-algorithm",
                    "least_duration",
                ]
            )
        result = subprocess.run(
            command,
            cwd=REPO_ROOT,
            env={**environment, "COVERAGE_FILE": str(raw)},
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert raw.is_file()
        return set(json.loads(nodeids.read_text(encoding="utf-8")))

    unsharded_data = tmp_path / ".coverage.unsharded"
    all_nodeids = run_measurement(unsharded_data, tmp_path / "all-nodeids.json")
    groups: list[set[str]] = []
    for group in (1, 2):
        groups.append(
            run_measurement(
                tmp_path / f".coverage.group-{group}",
                tmp_path / f"group-{group}-nodeids.json",
                group=group,
            )
        )

    assert groups[0]
    assert groups[1]
    assert groups[0].isdisjoint(groups[1])
    assert groups[0] | groups[1] == all_nodeids

    combined_data = tmp_path / ".coverage.combined"
    combined = Coverage(data_file=str(combined_data), branch=True, config_file=False)
    combined.combine(
        [str(tmp_path / ".coverage.group-1"), str(tmp_path / ".coverage.group-2")],
        strict=True,
        keep=True,
    )
    combined.save()
    combined_json = tmp_path / "combined.json"
    combined.json_report(outfile=str(combined_json))

    unsharded = Coverage(data_file=str(unsharded_data), branch=True, config_file=False)
    unsharded.load()
    unsharded_json = tmp_path / "unsharded.json"
    unsharded.json_report(outfile=str(unsharded_json))

    combined_report = json.loads(combined_json.read_text(encoding="utf-8"))
    unsharded_report = json.loads(unsharded_json.read_text(encoding="utf-8"))
    assert combined_report["totals"] == unsharded_report["totals"]
    assert combined_report["files"] == unsharded_report["files"]


def test_orchestrated_child_failure_never_combines(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    combined = False

    def fake_run(command: list[str], **kwargs: Any) -> SimpleNamespace:
        group = command[command.index("--group") + 1]
        return SimpleNamespace(returncode=1 if group == "2" else 0)

    def fake_combine(*args: Any, **kwargs: Any) -> None:
        nonlocal combined
        combined = True

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    monkeypatch.setattr(module, "combine_and_gate", fake_combine)

    with pytest.raises(module.ShardError, match="group 2 failed"):
        module.orchestrate(
            REPO_ROOT,
            tmp_path / "run",
            splits=2,
            jobs="0",
            seed="424242",
        )
    assert combined is False
