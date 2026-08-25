"""#458 — placeholder provenance pins must not provision, and catalog-check must reject them.

Locked D2 (open-issues-sweep-2026-08-24-a):

- ``make catalog-check`` / the ship gate rejects an all-zero ``sha256`` pin.
- ``checkov`` and ``yamllint`` ship ``provenance: {}`` (pip/repo-native, like semgrep).
- ``provision.py`` refuses an empty artifact name from a trailing-slash / directory-like
  URL and names that URL in ``ProvisionError`` — it must not write a directory
  (``Is a directory``).

These assertions fail until the AA implementation wave. Do not xfail: RED is the
point. Catalog YAML under ``src/mergecraft/analyzers/catalog/`` is product code.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from mergecraft.analyzers import catalog_docs, provision
from mergecraft.analyzers.manifest import (
    AnalyzerManifest,
    ManifestValidationError,
    load_manifest_file,
    validate_manifest,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CATALOG_DIR = _REPO_ROOT / "src" / "mergecraft" / "analyzers" / "catalog"
_ALL_ZERO_SHA256 = "0" * 64
_PLATFORM = "linux-amd64"
_PAYLOAD = b"#!/bin/sh\necho not-a-directory\n"
_PAYLOAD_SHA = hashlib.sha256(_PAYLOAD).hexdigest()
_TRAILING_SLASH_URLS = (
    "https://pypi.org/project/checkov/3.2.366/",
    "https://pypi.org/project/yamllint/1.35.1/",
    "https://example.invalid/releases/",
)
_PIP_CATALOG_IDS = ("checkov", "yamllint")


def _managed_manifest(
    *,
    tool_id: str = "faketool",
    url: str = "https://example.invalid/faketool",
    sha256: str = _PAYLOAD_SHA,
) -> AnalyzerManifest:
    return AnalyzerManifest.model_validate(
        {
            "id": tool_id,
            "category": "ci",
            "languages": [],
            "detect": {"files": ["**/*"]},
            "command": ["faketool", "{files}"],
            "scope": "diff",
            "parser": "sarif",
            "supports_fix": False,
            "default_enabled": "auto",
            "version": "1.0.0",
            "runtime": "managed",
            "timeout_s": 60,
            "trust": "untrusted",
            "severity_map": {"error": "Major", "warning": "Minor", "note": "Trivial"},
            "provenance": {_PLATFORM: {"url": url, "sha256": sha256}},
            "network_allowlist": [],
        }
    )


def _zero_pin_manifest_yaml(*, tool_id: str, url: str) -> str:
    """Minimal ship-gate-valid YAML whose only defect is an all-zero sha256 pin."""
    return (
        f"id: {tool_id}\n"
        "category: lint\n"
        "languages: [python]\n"
        "detect:\n"
        "  files: ['*.py']\n"
        "command: ['true']\n"
        "scope: diff\n"
        "parser: sarif\n"
        "supports_fix: false\n"
        "default_enabled: false\n"
        "version: '0.0.0'\n"
        "runtime: managed\n"
        "timeout_s: 60\n"
        "trust: untrusted\n"
        "severity_map:\n"
        "  error: Major\n"
        "  warning: Minor\n"
        "  note: Trivial\n"
        "provenance:\n"
        f"  {_PLATFORM}:\n"
        f"    url: {url}\n"
        f"    sha256: '{_ALL_ZERO_SHA256}'\n"
        "network_allowlist: []\n"
    )


def _prepare_ship_gate(tmp_path: Path, *, tool_id: str, url: str) -> Path:
    manifest_path = tmp_path / f"{tool_id}.yaml"
    manifest_path.write_text(_zero_pin_manifest_yaml(tool_id=tool_id, url=url), encoding="utf-8")
    native = tmp_path / "native"
    native.mkdir()
    (native / f"{tool_id}-minimal.json").write_text("{}", encoding="utf-8")
    (tmp_path / "ANALYZERS.md").write_text(f"| `{tool_id}` | lint | fixture |\n", encoding="utf-8")
    return manifest_path


def test_validate_manifest_rejects_all_zero_sha256_pin() -> None:
    """A 64-zero hex digest is a placeholder, not a pin — D2 catalog-check contract."""
    manifest = _managed_manifest(
        url="https://example.invalid/faketool.tar.gz", sha256=_ALL_ZERO_SHA256
    )

    with pytest.raises(ManifestValidationError, match=r"(?i)sha256|placeholder|all-?zero"):
        validate_manifest(manifest, check_provenance=True)


def test_validate_manifest_accepts_empty_provenance_and_real_pin() -> None:
    """``provenance: {}`` (semgrep) and a non-zero pin both remain valid."""
    empty = AnalyzerManifest.model_validate(
        {
            "id": "semgrep-like",
            "category": "security",
            "languages": ["python"],
            "detect": {"files": ["*.py"]},
            "command": ["semgrep"],
            "scope": "diff",
            "parser": "sarif",
            "supports_fix": False,
            "default_enabled": True,
            "version": "1.0.0",
            "runtime": "managed",
            "timeout_s": 60,
            "trust": "untrusted",
            "severity_map": {"error": "Major", "warning": "Minor", "note": "Trivial"},
            "provenance": {},
            "network_allowlist": [],
        }
    )
    validate_manifest(empty, check_provenance=True)

    pinned = _managed_manifest(sha256=_PAYLOAD_SHA)
    validate_manifest(pinned, check_provenance=True)


def test_catalog_ship_gate_rejects_all_zero_sha256(tmp_path: Path) -> None:
    """``make catalog-check`` goes through ``validate_manifest_ship_gate``.

    Fixture + ANALYZERS.md row are present so the only remaining defect is the
    all-zero pin. Today the gate ignores provenance hashes — this must fail.
    """
    url = "https://pypi.org/project/checkov/3.2.366/"
    manifest_path = _prepare_ship_gate(tmp_path, tool_id="zero-pin", url=url)

    with pytest.raises(
        (catalog_docs.CatalogIntegrityError, ManifestValidationError),
        match=r"(?i)sha256|placeholder|all-?zero",
    ):
        catalog_docs.validate_manifest_ship_gate(
            manifest_path,
            fixture_root=tmp_path,
            doc_path=tmp_path / "ANALYZERS.md",
        )


@pytest.mark.parametrize("tool_id", _PIP_CATALOG_IDS)
def test_checkov_and_yamllint_ship_empty_provenance_like_semgrep(tool_id: str) -> None:
    """D2: pip-installed catalog tools must not carry a fake binary pin."""
    semgrep = load_manifest_file(_CATALOG_DIR / "semgrep.yaml")
    loaded = load_manifest_file(_CATALOG_DIR / f"{tool_id}.yaml")

    assert dict(semgrep.provenance) == {}
    assert dict(loaded.provenance) == {}, (
        f"{tool_id} must ship provenance: {{}} like semgrep; got {loaded.provenance!r}"
    )


@pytest.fixture
def download_calls(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, Path]]:
    """Record download dests; writing onto a directory is the #458 bug."""
    calls: list[tuple[str, Path]] = []

    def _fake(url: str, dest: Path) -> None:
        calls.append((url, dest))
        dest.write_bytes(_PAYLOAD)

    monkeypatch.setattr(provision, "_download_pinned_url", _fake)
    return calls


@pytest.mark.parametrize("url", _TRAILING_SLASH_URLS)
def test_trailing_slash_url_is_refused_and_names_the_url(
    tmp_path: Path, download_calls: list[tuple[str, Path]], url: str
) -> None:
    """A directory-like artifact URL must not be used as a write destination.

    ``url.rsplit('/', 1)[-1]`` is empty when the URL ends in ``/``, so
    ``tmp / ''`` is the temporary directory itself. Writing then raises
    ``Is a directory``. D2: refuse the empty artifact name and name the URL
    before any download.
    """
    manifest = _managed_manifest(url=url, sha256=_PAYLOAD_SHA)

    with pytest.raises(provision.ProvisionError) as exc_info:
        provision.provision_managed_binary(
            manifest=manifest,
            platform=_PLATFORM,
            cache_dir=tmp_path / "cache",
        )

    message = str(exc_info.value)
    assert url in message, f"ProvisionError must name the URL, got {message!r}"
    assert "Is a directory" not in message
    assert download_calls == []


def test_empty_artifact_name_is_refused_before_download(
    tmp_path: Path, download_calls: list[tuple[str, Path]]
) -> None:
    """Explicit empty last path segment (trailing slash) never reaches the downloader."""
    url = "https://example.invalid/catalog/"
    manifest = _managed_manifest(url=url, sha256=_PAYLOAD_SHA)

    with pytest.raises(provision.ProvisionError, match=r"https://example\.invalid/catalog/"):
        provision.provision_managed_binary(
            manifest=manifest,
            platform=_PLATFORM,
            cache_dir=tmp_path / "cache",
        )

    assert download_calls == []
    cache_root = tmp_path / "cache"
    if cache_root.exists():
        for path in cache_root.rglob("*"):
            assert path.name != "", path
