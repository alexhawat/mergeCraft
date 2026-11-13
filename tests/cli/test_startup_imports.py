"""Fresh-process CLI startup contracts, without collection's warmed imports."""

from __future__ import annotations

import json
import os
import resource
import subprocess
import sys
import time
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "module",
    ["mergecraft.cli.app", "mergecraft.run_outcome", "mergecraft.mcp.endpoints"],
    ids=["cli", "exit-codes", "mcp-endpoints"],
)
def test_lightweight_imports_do_not_load_server(module: str, tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            f"import {module}; import sys,json; print(json.dumps(list(sys.modules)))",
        ],
        cwd=tmp_path,
        env={"PATH": os.defpath, "HOME": str(tmp_path)},
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    modules = json.loads(result.stdout)
    assert "mergecraft.mcp.server" not in modules
    assert "fastapi" not in modules
    if module == "mergecraft.cli.app":
        assert not [
            name for name in modules if name.startswith("mergecraft.cli.") and name.endswith("_cmd")
        ]


@pytest.mark.parametrize(
    "args",
    [["--version"], ["--help"], ["version", "--format", "json"]],
    ids=["version-flag", "root-help", "version-json"],
)
def test_cli_information_does_not_import_commands(args: list[str], tmp_path: Path) -> None:
    script = """
import json, sys
from mergecraft.cli.app import main
sys.argv = ["mergecraft", *json.loads(sys.argv[1])]
try:
    main()
except SystemExit as exc:
    assert exc.code in (None, 0), exc.code
print("MODULES=" + json.dumps(list(sys.modules)))
"""
    result = subprocess.run(
        [sys.executable, "-c", script, json.dumps(args)],
        cwd=tmp_path,
        env={"PATH": os.defpath, "HOME": str(tmp_path)},
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    output, modules_json = result.stdout.rsplit("MODULES=", 1)
    assert output.strip()
    modules = json.loads(modules_json)
    assert "mergecraft.mcp.server" not in modules
    assert not [
        name for name in modules if name.startswith("mergecraft.cli.") and name.endswith("_cmd")
    ]


def test_warm_version_startup_cpu_budget(tmp_path: Path) -> None:
    """Budget fresh-process CPU work, excluding parallel-worker scheduling delay.

    Wall times remain in the failure diagnostic. Each sample starts the real
    installed executable; only filesystem/bytecode caches are warm.
    """
    elapsed = []
    cpu_times = []
    for _ in range(4):
        start = time.perf_counter()
        before = resource.getrusage(resource.RUSAGE_CHILDREN)
        result = subprocess.run(
            [str(Path(sys.executable).with_name("mergecraft")), "--version"],
            cwd=tmp_path,
            env={"PATH": os.defpath, "HOME": str(tmp_path)},
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        after = resource.getrusage(resource.RUSAGE_CHILDREN)
        elapsed.append(time.perf_counter() - start)
        cpu_times.append(after.ru_utime + after.ru_stime - before.ru_utime - before.ru_stime)
        assert result.stdout.strip()
    assert min(cpu_times[1:]) < 0.3, {"cpu": cpu_times, "wall": elapsed}


def test_root_completion_discovers_commands_without_importing_them(tmp_path: Path) -> None:
    script = """
import click, json, sys
from typer.main import get_command
from mergecraft.cli.app import app
command = get_command(app)
items = command.shell_complete(click.Context(command), "rev")
print(json.dumps({"items": [item.value for item in items], "modules": list(sys.modules)}))
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env={"PATH": os.defpath, "HOME": str(tmp_path)},
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    payload = json.loads(result.stdout)
    assert "review" in payload["items"]
    assert "diff-review" not in payload["items"]
    assert not [
        name
        for name in payload["modules"]
        if name.startswith("mergecraft.cli.") and name.endswith("_cmd")
    ]


@pytest.mark.parametrize(
    "args",
    [["-v"], ["version", "--format", "json"], ["--help"], ["provider", "--help"]],
    ids=["short-version", "version-json", "help", "provider-help"],
)
def test_installed_entrypoint_preserves_parser_routes(args: list[str], tmp_path: Path) -> None:
    result = subprocess.run(
        [str(Path(sys.executable).with_name("mergecraft")), *args],
        cwd=tmp_path,
        env={"PATH": os.defpath, "HOME": str(tmp_path)},
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    assert result.stdout.strip()
    if args == ["version", "--format", "json"]:
        assert json.loads(result.stdout)["version"]
    elif args == ["provider", "--help"]:
        assert "auth" in result.stdout


def test_installed_entrypoint_keeps_invalid_option_errors(tmp_path: Path) -> None:
    result = subprocess.run(
        [str(Path(sys.executable).with_name("mergecraft")), "--version", "--unknown-option"],
        cwd=tmp_path,
        env={"PATH": os.defpath, "HOME": str(tmp_path)},
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 2
    assert "No such option" in result.stderr


def test_lazy_utility_exports_preserve_normalize_env_callable(tmp_path: Path) -> None:
    script = """
import mergecraft.utils.normalize_env
from mergecraft.utils import normalize_env
values = {"example_setting": "value"}
normalize_env(values)
assert values == {"EXAMPLE_SETTING": "value"}
"""
    subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env={"PATH": os.defpath, "HOME": str(tmp_path)},
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
